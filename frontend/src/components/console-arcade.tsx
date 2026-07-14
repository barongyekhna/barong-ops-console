"use client";

import {
  Apple,
  Bird,
  Bomb,
  ChevronDown,
  ChevronLeft,
  CircleDot,
  Crosshair,
  Disc,
  Gamepad2,
  Gauge,
  Gem,
  Grid2x2,
  Grid3x3,
  LoaderCircle,
  Orbit,
  Rocket,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type CSSProperties,
} from "react";

import { Game2048 } from "@/components/arcade-2048";
import { AsteroidsGame } from "@/components/arcade-asteroids";
import { BreakoutGame } from "@/components/arcade-breakout";
import { FlappyGame } from "@/components/arcade-flappy";
import { Match3Game } from "@/components/arcade-match3";
import { MinesGame } from "@/components/arcade-mines";
import { PongGame } from "@/components/arcade-pong";
import { RunnerGame } from "@/components/arcade-runner";
import { ShmupGame } from "@/components/arcade-shmup";
import { SnakeGame } from "@/components/arcade-snake";
import { TankGame } from "@/components/arcade-tank";
import { TetrisGame } from "@/components/arcade-tetris";
import { useAuth } from "@/components/auth-provider";
import {
  listArcadeHighScores,
  submitArcadeHighScore,
} from "@/lib/arcade-high-scores-api";
import {
  mergeArcadeHighScores,
  optimisticArcadeHighScore,
  reconcileArcadeHighScore,
  type ArcadeGameId,
  type ArcadeHighScoreMap,
} from "@/lib/arcade-high-score-state";
import { ApiError, ApiTimeoutError, isApiAbortError } from "@/lib/api";

type ArcadeGameProps = {
  onExit: () => void;
  onScoreChange?: (score: number) => void;
};

type PendingArcadeScore = {
  identityKey: string;
  score: number;
  userId: number;
};

type ScoreSyncController = {
  controller: AbortController;
  generation: number;
};

const SCORE_SYNC_DELAY_MS = 350;
const SCORE_RETRY_DELAY_MS = 5_000;
const SCORE_REFRESH_INTERVAL_MS = 15_000;

const GAMES: Array<{
  id: ArcadeGameId;
  name: string;
  en: string;
  desc: string;
  accent: string;
  Icon: LucideIcon;
  Game: ComponentType<ArcadeGameProps>;
}> = [
  { id: "shmup", name: "深空空战", en: "SKY RAID", desc: "WASD 飞行 · 自动开火 · 吃道具扫屏", accent: "#39d4ff", Icon: Rocket, Game: ShmupGame },
  { id: "snake", name: "贪吃蛇", en: "SNAKE", desc: "WASD 转向 · 吃光点变长 · 别咬到自己", accent: "#4dffa1", Icon: Apple, Game: SnakeGame },
  { id: "tetris", name: "俄罗斯方块", en: "TETRIS", desc: "A/D 移动 · W 旋转 · 空格瞬降 · 消行", accent: "#a893ff", Icon: Grid3x3, Game: TetrisGame },
  { id: "tank", name: "坦克大战", en: "TANK", desc: "WASD 移动转向 · 空格开火 · 打穿砖墙", accent: "#ffb13b", Icon: Crosshair, Game: TankGame },
  { id: "asteroids", name: "小行星", en: "ASTEROIDS", desc: "A/D 转向 · W 推进 · 空格开火 · 边缘穿越", accent: "#5b8cff", Icon: Orbit, Game: AsteroidsGame },
  { id: "breakout", name: "打砖块", en: "BREAKOUT", desc: "A/D 挡板 · 空格发射 · 接道具砸墙", accent: "#ff6b8a", Icon: CircleDot, Game: BreakoutGame },
  { id: "2048", name: "2048", en: "2048", desc: "WASD 滑动合并数字 · 凑到 2048", accent: "#ffd23b", Icon: Grid2x2, Game: Game2048 },
  { id: "runner", name: "星际跑酷", en: "RUNNER", desc: "W / 空格 起跳 · 躲陨石 · 拼最远距离", accent: "#ff9a5f", Icon: Gauge, Game: RunnerGame },
  { id: "match3", name: "宝石迷阵", en: "MATCH-3", desc: "空格选中 · 方向交换 · 凑三连消除", accent: "#ff8ac0", Icon: Gem, Game: Match3Game },
  { id: "mines", name: "扫雷", en: "MINESWEEPER", desc: "WASD 移动 · 空格挖 · F 插旗", accent: "#6ec7ff", Icon: Bomb, Game: MinesGame },
  { id: "flappy", name: "星舰穿梭", en: "FLAPPY", desc: "W / 空格 上浮 · 穿过能量门缝隙", accent: "#ffd23b", Icon: Bird, Game: FlappyGame },
  { id: "pong", name: "弹球对战", en: "PONG", desc: "W/S 球拍 · 对战 AI · 先到 7 分", accent: "#4dffa1", Icon: Disc, Game: PongGame },
];

export function ConsoleArcade() {
  const { user } = useAuth();
  const [active, setActive] = useState<ArcadeGameId | null>(null);
  const [collapsed, setCollapsed] = useState(true);
  const [highScores, setHighScores] = useState<ArcadeHighScoreMap>({});
  const [scoresLoading, setScoresLoading] = useState(false);
  const [scoresUnavailable, setScoresUnavailable] = useState(false);
  const highScoresRef = useRef<ArcadeHighScoreMap>({});
  const confirmedHighScoresRef = useRef<ArcadeHighScoreMap>({});
  const pendingScoresRef = useRef<Partial<Record<ArcadeGameId, PendingArcadeScore>>>({});
  const inFlightScoresRef = useRef<Partial<Record<ArcadeGameId, PendingArcadeScore>>>({});
  const syncTimersRef = useRef<Partial<Record<ArcadeGameId, ReturnType<typeof setTimeout>>>>({});
  const syncingGamesRef = useRef<Partial<Record<ArcadeGameId, number>>>({});
  const syncControllersRef = useRef<Partial<Record<ArcadeGameId, ScoreSyncController>>>({});
  const mountedRef = useRef(true);
  const identityGenerationRef = useRef(0);
  const refreshGenerationRef = useRef(0);
  const currentUserIdRef = useRef<number | null>(user?.id ?? null);
  const identityKey = `${user?.id ?? "anonymous"}:${user?.organization_id ?? "no-org"}`;
  const currentIdentityKeyRef = useRef(identityKey);
  const previousIdentityKeyRef = useRef(identityKey);
  currentUserIdRef.current = user?.id ?? null;
  currentIdentityKeyRef.current = identityKey;
  const current = GAMES.find((g) => g.id === active) ?? null;
  const currentHighScore = current ? highScores[current.id] : undefined;

  const updateHighScores = useCallback(
    (updater: (currentScores: ArcadeHighScoreMap) => ArcadeHighScoreMap) => {
      const next = updater(highScoresRef.current);
      highScoresRef.current = next;
      setHighScores(next);
    },
    [],
  );

  const clearScoreSyncState = useCallback(() => {
    for (const timer of Object.values(syncTimersRef.current)) {
      if (timer !== undefined) clearTimeout(timer);
    }
    for (const entry of Object.values(syncControllersRef.current)) {
      entry?.controller.abort();
    }
    pendingScoresRef.current = {};
    inFlightScoresRef.current = {};
    syncTimersRef.current = {};
    syncingGamesRef.current = {};
    syncControllersRef.current = {};
  }, []);

  useEffect(() => {
    if (previousIdentityKeyRef.current === identityKey) return;

    previousIdentityKeyRef.current = identityKey;
    identityGenerationRef.current += 1;
    refreshGenerationRef.current += 1;
    clearScoreSyncState();
    confirmedHighScoresRef.current = {};
    highScoresRef.current = {};
    setActive(null);
    setHighScores({});
    setScoresLoading(false);
    setScoresUnavailable(false);
  }, [clearScoreSyncState, identityKey]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      const userId = currentUserIdRef.current;
      const currentIdentityKey = currentIdentityKeyRef.current;
      if (userId !== null) {
        for (const game of GAMES) {
          const pending = pendingScoresRef.current[game.id];
          const inFlight = inFlightScoresRef.current[game.id];
          const pendingScore =
            pending?.userId === userId && pending.identityKey === currentIdentityKey
              ? pending.score
              : 0;
          const inFlightScore =
            inFlight?.userId === userId && inFlight.identityKey === currentIdentityKey
              ? inFlight.score
              : 0;
          const score = Math.max(pendingScore, inFlightScore);
          if (score > 0) {
            void submitArcadeHighScore(game.id, score, { keepalive: true }).catch(
              () => undefined,
            );
          }
        }
      }
      mountedRef.current = false;
      identityGenerationRef.current += 1;
      refreshGenerationRef.current += 1;
      clearScoreSyncState();
    };
  }, [clearScoreSyncState]);

  const refreshHighScores = useCallback(async (signal?: AbortSignal) => {
    const requestGeneration = refreshGenerationRef.current + 1;
    const identityGeneration = identityGenerationRef.current;
    refreshGenerationRef.current = requestGeneration;
    setScoresLoading(true);
    try {
      const items = await listArcadeHighScores({ signal });
      if (
        signal?.aborted ||
        !mountedRef.current ||
        identityGenerationRef.current !== identityGeneration
      ) return;
      confirmedHighScoresRef.current = mergeArcadeHighScores(
        confirmedHighScoresRef.current,
        items,
      );
      updateHighScores((existing) => mergeArcadeHighScores(existing, items));
      if (
        refreshGenerationRef.current === requestGeneration &&
        Object.keys(pendingScoresRef.current).length === 0 &&
        Object.keys(syncingGamesRef.current).length === 0
      ) {
        setScoresUnavailable(false);
      }
    } catch {
      if (
        !signal?.aborted &&
        mountedRef.current &&
        identityGenerationRef.current === identityGeneration &&
        refreshGenerationRef.current === requestGeneration
      ) setScoresUnavailable(true);
    } finally {
      if (
        !signal?.aborted &&
        mountedRef.current &&
        identityGenerationRef.current === identityGeneration &&
        refreshGenerationRef.current === requestGeneration
      ) setScoresLoading(false);
    }
  }, [updateHighScores]);

  useEffect(() => {
    if (collapsed) return;

    const controller = new AbortController();
    void refreshHighScores(controller.signal);
    const intervalId = window.setInterval(() => {
      void refreshHighScores(controller.signal);
    }, SCORE_REFRESH_INTERVAL_MS);
    const refreshOnFocus = () => void refreshHighScores(controller.signal);
    window.addEventListener("focus", refreshOnFocus);

    return () => {
      controller.abort();
      window.clearInterval(intervalId);
      window.removeEventListener("focus", refreshOnFocus);
    };
  }, [collapsed, identityKey, refreshHighScores]);

  const flushHighScore = useCallback(async (gameId: ArcadeGameId) => {
    const generation = identityGenerationRef.current;
    if (syncingGamesRef.current[gameId] === generation) return;
    const pending = pendingScoresRef.current[gameId];
    if (
      pending === undefined ||
      pending.userId !== currentUserIdRef.current ||
      pending.identityKey !== currentIdentityKeyRef.current ||
      !mountedRef.current
    ) {
      delete pendingScoresRef.current[gameId];
      return;
    }

    delete pendingScoresRef.current[gameId];
    inFlightScoresRef.current[gameId] = pending;
    syncingGamesRef.current[gameId] = generation;
    const controller = new AbortController();
    syncControllersRef.current[gameId] = { controller, generation };
    let nextSyncDelay = SCORE_SYNC_DELAY_MS;
    let syncFailed = false;
    try {
      const authoritative = await submitArcadeHighScore(
        gameId,
        pending.score,
        { signal: controller.signal },
      );
      if (
        !mountedRef.current ||
        identityGenerationRef.current !== generation ||
        currentUserIdRef.current !== pending.userId ||
        currentIdentityKeyRef.current !== pending.identityKey
      ) return;
      confirmedHighScoresRef.current = {
        ...confirmedHighScoresRef.current,
        [gameId]: reconcileArcadeHighScore(
          confirmedHighScoresRef.current[gameId],
          authoritative,
        ),
      };
      updateHighScores((existing) => ({
        ...existing,
        [gameId]: reconcileArcadeHighScore(existing[gameId], authoritative),
      }));
    } catch (error) {
      if (
        !mountedRef.current ||
        identityGenerationRef.current !== generation ||
        currentUserIdRef.current !== pending.userId ||
        currentIdentityKeyRef.current !== pending.identityKey ||
        (isApiAbortError(error) && !(error instanceof ApiTimeoutError))
      ) return;
      syncFailed = true;
      setScoresUnavailable(true);
      const retryable =
        !(error instanceof ApiError) ||
        error.status === 429 ||
        error.status >= 500;
      if (retryable) {
        const queued = pendingScoresRef.current[gameId];
        pendingScoresRef.current[gameId] = {
          score: Math.max(
            queued?.userId === pending.userId &&
              queued.identityKey === pending.identityKey
              ? queued.score
              : 0,
            pending.score,
          ),
          identityKey: pending.identityKey,
          userId: pending.userId,
        };
        nextSyncDelay = SCORE_RETRY_DELAY_MS;
      } else if (pendingScoresRef.current[gameId] === undefined) {
        const confirmed = confirmedHighScoresRef.current[gameId];
        updateHighScores((existing) => {
          const next = { ...existing };
          if (confirmed) next[gameId] = confirmed;
          else delete next[gameId];
          return next;
        });
      }
    } finally {
      if (syncingGamesRef.current[gameId] === generation) {
        delete syncingGamesRef.current[gameId];
      }
      if (syncControllersRef.current[gameId]?.generation === generation) {
        delete syncControllersRef.current[gameId];
      }
      if (inFlightScoresRef.current[gameId] === pending) {
        delete inFlightScoresRef.current[gameId];
      }
      const identityChanged =
        !mountedRef.current ||
        identityGenerationRef.current !== generation ||
        currentUserIdRef.current !== pending.userId ||
        currentIdentityKeyRef.current !== pending.identityKey;
      if (!identityChanged) {
        if (
          pendingScoresRef.current[gameId] !== undefined &&
          syncTimersRef.current[gameId] === undefined
        ) {
          syncTimersRef.current[gameId] = setTimeout(() => {
            delete syncTimersRef.current[gameId];
            void flushHighScore(gameId);
          }, nextSyncDelay);
        } else if (
          !syncFailed &&
          Object.keys(pendingScoresRef.current).length === 0 &&
          Object.keys(syncingGamesRef.current).length === 0
        ) {
          setScoresUnavailable(false);
        }
      }
    }
  }, [updateHighScores]);

  const handleScoreChange = useCallback((gameId: ArcadeGameId, score: number) => {
    if (!user) return;
    const username = user.username;
    const optimistic = optimisticArcadeHighScore(
      highScoresRef.current[gameId],
      { gameId, score, username },
    );
    if (optimistic === highScoresRef.current[gameId]) return;

    updateHighScores((existing) => ({ ...existing, [gameId]: optimistic }));
    const queued = pendingScoresRef.current[gameId];
    pendingScoresRef.current[gameId] = {
      score: Math.max(
        queued?.userId === user.id && queued.identityKey === identityKey
          ? queued.score
          : 0,
        optimistic?.score ?? 0,
      ),
      identityKey,
      userId: user.id,
    };

    if (syncTimersRef.current[gameId] === undefined) {
      syncTimersRef.current[gameId] = setTimeout(() => {
        delete syncTimersRef.current[gameId];
        void flushHighScore(gameId);
      }, SCORE_SYNC_DELAY_MS);
    }
  }, [flushHighScore, identityKey, updateHighScores, user]);

  const flushPendingHighScore = useCallback((gameId: ArcadeGameId) => {
    const timer = syncTimersRef.current[gameId];
    if (timer !== undefined) clearTimeout(timer);
    delete syncTimersRef.current[gameId];
    void flushHighScore(gameId);
  }, [flushHighScore]);

  const exitActiveGame = useCallback(() => {
    if (active !== null) flushPendingHighScore(active);
    setActive(null);
  }, [active, flushPendingHighScore]);

  const handleActiveScoreChange = useCallback((score: number) => {
    if (active !== null) handleScoreChange(active, score);
  }, [active, handleScoreChange]);

  return (
    <section className={`cc-arcade${collapsed ? " collapsed" : ""}`} aria-label="控制台游戏厅">
      <div className="cc-arcade-head">
        <div className="cc-arcade-title">
          <Gamepad2 aria-hidden="true" size={16} />
          <div>
            <span className="cc-arcade-eyebrow">忙里偷闲</span>
            <strong>{current ? current.name : "控制台游戏厅 · ARCADE"}</strong>
          </div>
        </div>
        <div className="cc-arcade-head-right">
          {current ? (
            <div
              className="cc-arcade-record"
              title={currentHighScore ? `纪录保持者：${currentHighScore.username}` : undefined}
            >
              <Trophy aria-hidden="true" size={14} />
              <span>历史最高</span>
              {currentHighScore ? (
                <strong>{currentHighScore.score} · {currentHighScore.username}</strong>
              ) : scoresLoading ? (
                <span className="cc-arcade-record-pending">
                  <LoaderCircle aria-hidden="true" className="cc-arcade-record-loading" size={13} />
                  加载中
                </span>
              ) : (
                <strong>暂无纪录</strong>
              )}
              {scoresUnavailable ? <em>未同步</em> : null}
            </div>
          ) : null}
          {current ? (
            <button className="cc-arcade-exit" onClick={exitActiveGame} type="button">
              <ChevronLeft aria-hidden="true" size={15} />
              返回游戏厅
            </button>
          ) : null}
          <button
            className="cc-arcade-toggle"
            onClick={() => {
              if (active !== null) flushPendingHighScore(active);
              setActive(null);
              setCollapsed((c) => !c);
            }}
            type="button"
          >
            {collapsed ? "展开游戏厅" : "收起"}
            <ChevronDown
              aria-hidden="true"
              className={collapsed ? "cc-arcade-chev" : "cc-arcade-chev up"}
              size={15}
            />
          </button>
        </div>
      </div>

      {collapsed ? null : current ? (
        <current.Game
          onExit={exitActiveGame}
          onScoreChange={handleActiveScoreChange}
        />
      ) : (
        <div className="cc-arcade-menu">
          {GAMES.map((g) => (
            <button
              className="cc-game-card"
              key={g.id}
              onClick={() => setActive(g.id)}
              style={{ "--accent": g.accent } as CSSProperties}
              type="button"
            >
              <span className="cc-game-icon">
                <g.Icon aria-hidden="true" size={22} />
              </span>
              <strong>{g.name}</strong>
              <span className="cc-game-en">{g.en}</span>
              <small>{g.desc}</small>
              <span className="cc-game-record">
                <Trophy aria-hidden="true" size={12} />
                {highScores[g.id]
                  ? `历史最高 ${highScores[g.id]?.score} · ${highScores[g.id]?.username}`
                  : scoresLoading
                    ? "纪录加载中"
                    : "暂无历史纪录"}
              </span>
              <span className="cc-game-play">▶ 开始</span>
            </button>
          ))}
          {scoresUnavailable ? (
            <div className="cc-arcade-sync-note" role="status">
              纪录同步暂时不可用；本局新纪录仍会即时显示，并在下次刷新时重新校准。
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
