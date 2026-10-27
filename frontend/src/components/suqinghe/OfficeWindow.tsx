"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import styles from "./Office.module.css";
import {
  STATE_LABEL,
  officeErrorMessage,
  portraitFor,
  type OfficeRead,
  type OfficeState,
} from "./office-api";
import { GoalList, Inbox, OwnerControls, minutesAgo, pickEasterLine, timeText } from "./OfficeParts";
import { OfficeScene } from "./OfficeScene";

const POSITION_KEY = "suqinghe-office-position";
const VIEW_KEY = "suqinghe-office-view";
const SIZE_KEY = "suqinghe-office-size";
const MOBILE_QUERY = "(max-width: 760px)";

type View = "scene" | "list";
type Size = "normal" | "large";

function readPref<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw && (allowed as readonly string[]).includes(raw) ? (raw as T) : fallback;
  } catch {
    return fallback;
  }
}

function writePref(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* 存不了就算了,只是偏好 */
  }
}

type Position = { x: number; y: number };

function readPosition(): Position | null {
  try {
    const raw = window.localStorage.getItem(POSITION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Position;
    return typeof parsed?.x === "number" && typeof parsed?.y === "number" ? parsed : null;
  } catch {
    return null;
  }
}

function savePosition(position: Position) {
  try {
    window.localStorage.setItem(POSITION_KEY, JSON.stringify(position));
  } catch {
    /* 隐私模式等存不了就算了,位置只是方便 */
  }
}

function clamp(position: Position, width: number, height: number): Position {
  const maxX = Math.max(8, window.innerWidth - width - 8);
  const maxY = Math.max(8, window.innerHeight - 48);
  return { x: Math.min(Math.max(8, position.x), maxX), y: Math.min(Math.max(8, position.y), maxY) };
}

function StatusAnimation({ state }: { state: OfficeState }) {
  if (state === "working") return <span aria-hidden className={styles.caret} />;
  if (state === "thinking")
    return (
      <span aria-hidden className={styles.dots}>
        <i />
        <i />
        <i />
      </span>
    );
  return null;
}

export function OfficeWindow({
  office,
  loadError,
  onClose,
  onChanged,
}: {
  office: OfficeRead | null;
  loadError: string | null;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const panelRef = useRef<HTMLElement | null>(null);
  const [position, setPosition] = useState<Position | null>(null);
  const [isMobile, setIsMobile] = useState(false);
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);
  const [shownState, setShownState] = useState<OfficeState | null>(null);
  const [fadeKey, setFadeKey] = useState(0);
  const clicksRef = useRef<number[]>([]);
  const [bubble, setBubble] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // 默认场景视图;列表视图是快速浏览和图片加载失败时的兜底。
  const [view, setView] = useState<View>("scene");
  const [size, setSize] = useState<Size>("normal");
  const [sceneFailed, setSceneFailed] = useState(false);

  useEffect(() => {
    setView(readPref<View>(VIEW_KEY, ["scene", "list"], "scene"));
    setSize(readPref<Size>(SIZE_KEY, ["normal", "large"], "normal"));
  }, []);

  useEffect(() => {
    const media = window.matchMedia(MOBILE_QUERY);
    const sync = () => setIsMobile(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    const stored = readPosition();
    const width = Math.min(880, window.innerWidth - 16);
    setPosition(clamp(stored ?? { x: window.innerWidth - width - 24, y: 80 }, width, 200));
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const state = office?.state ?? "offline";
  useEffect(() => {
    if (shownState !== state) {
      setShownState(state);
      setFadeKey((key) => key + 1);
    }
  }, [state, shownState]);

  const onPointerDown = (event: ReactPointerEvent<HTMLElement>) => {
    if (isMobile || !position || (event.target as HTMLElement).closest("button")) return;
    dragRef.current = { dx: event.clientX - position.x, dy: event.clientY - position.y };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLElement>) => {
    if (!dragRef.current || !panelRef.current) return;
    const rect = panelRef.current.getBoundingClientRect();
    setPosition(clamp({ x: event.clientX - dragRef.current.dx, y: event.clientY - dragRef.current.dy }, rect.width, rect.height));
  };
  const onPointerUp = () => {
    if (dragRef.current && position) savePosition(position);
    dragRef.current = null;
  };

  const onPortraitClick = () => {
    const now = Date.now();
    clicksRef.current = [...clicksRef.current.filter((at) => now - at < 3000), now];
    if (clicksRef.current.length >= 5) {
      clicksRef.current = [];
      setBubble(pickEasterLine());
      window.setTimeout(() => setBubble(null), 4500);
    }
  };

  const run = useCallback(
    async (label: string, action: () => Promise<unknown>) => {
      setBusy(true);
      setActionError(null);
      try {
        await action();
        await onChanged();
        return true;
      } catch (error) {
        setActionError(officeErrorMessage(error, label));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [onChanged],
  );

  const panelStyle =
    !isMobile && position ? { left: `${position.x}px`, top: `${position.y}px` } : undefined;
  const canCommand = Boolean(office?.can_command);
  const showScene = view === "scene" && !sceneFailed;
  const switchView = (next: View) => {
    setView(next);
    if (next === "scene") setSceneFailed(false);
    writePref(VIEW_KEY, next);
  };
  const toggleSize = () => {
    const next: Size = size === "large" ? "normal" : "large";
    setSize(next);
    writePref(SIZE_KEY, next);
    if (position && panelRef.current) {
      const width = Math.min(next === "large" ? 1200 : 880, window.innerWidth - 16);
      setPosition(clamp(position, width, panelRef.current.getBoundingClientRect().height));
    }
  };

  return (
    <section
      aria-label="苏青禾的办公室"
      className={`${styles.window} ${showScene ? (size === "large" ? styles.windowLarge : styles.windowScene) : ""} ${isMobile ? styles.windowSheet : ""}`}
      data-state={state}
      ref={panelRef}
      role="dialog"
      style={panelStyle}
    >
      <header
        className={styles.header}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <div>
          <strong>苏青禾的办公室</strong>
          <span className={styles.subtitle}>独立站运营总管</span>
        </div>
        <div className={styles.headerTools}>
          <div aria-label="视图" className={styles.viewToggle} role="group">
            <button aria-pressed={showScene} onClick={() => switchView("scene")} type="button">
              场景
            </button>
            <button aria-pressed={!showScene} onClick={() => switchView("list")} type="button">
              列表
            </button>
          </div>
          {showScene && !isMobile ? (
            <button className={styles.sizeToggle} onClick={toggleSize} type="button">
              {size === "large" ? "缩小" : "放大"}
            </button>
          ) : null}
          <button aria-label="关闭办公室" className={styles.close} onClick={onClose} type="button">
            ×
          </button>
        </div>
      </header>

      <div className={styles.body}>
        {!office ? (
          <p className={styles.muted}>{loadError ?? "正在推开办公室的门…"}</p>
        ) : showScene ? (
          <>
            {actionError ? (
              <p className={styles.error} role="alert">
                {actionError}
              </p>
            ) : null}
            <OfficeScene busy={busy} isMobile={isMobile} office={office} onSceneFailed={() => setSceneFailed(true)} run={run} />
            {canCommand ? null : <p className={styles.muted}>只有老板能指挥她，你可以在这里看她干活、点开东西看。</p>}
          </>
        ) : (
          <>
            {sceneFailed && view === "scene" ? <p className={styles.muted}>办公室的画没加载出来，先用列表看。</p> : null}
            <div className={styles.stage} data-state={state}>
              <button aria-label="苏青禾的肖像" className={styles.portraitButton} onClick={onPortraitClick} type="button">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  alt={`苏青禾 · ${STATE_LABEL[state]}`}
                  className={styles.portrait}
                  data-state={state}
                  height={480}
                  key={fadeKey}
                  src={portraitFor(state)}
                  width={480}
                />
              </button>
              {state === "night" ? (
                <span aria-hidden className={styles.moon}>
                  ☾
                </span>
              ) : null}
              {office.paused ? <span className={styles.pausedChip}>已暂停</span> : null}
              {bubble ? <div className={styles.bubble}>{bubble}</div> : null}
              <span className={styles.stateChip} data-state={state}>
                {STATE_LABEL[state]}
              </span>
            </div>

            {state === "offline" ? (
              <p className={styles.offlineLine}>她联系不上了 · {minutesAgo(office.heartbeat.silent_seconds)}</p>
            ) : null}

            <section className={styles.section}>
              <div className={styles.task}>
                <span>{office.task || (office.paused ? "暂停中，等老板发话" : "在岗待命")}</span>
                <StatusAnimation state={state} />
              </div>
              {typeof office.progress === "number" ? (
                <div aria-label={`进度 ${office.progress}%`} className={styles.progress} role="progressbar">
                  <span style={{ width: `${Math.max(0, Math.min(100, office.progress))}%` }} />
                </div>
              ) : null}
            </section>

            <section className={styles.kpis}>
              <div>
                <b>{office.today.cards_pending}</b>
                <span>待批</span>
              </div>
              <div>
                <b>{office.today.cards_created}</b>
                <span>今天出卡</span>
              </div>
              <div>
                <b>{office.today.cards_decided}</b>
                <span>今天已定</span>
              </div>
              <div>
                <b>{office.today.claude_usd == null ? "—" : `$${office.today.claude_usd.toFixed(2)}`}</b>
                <span>今天 AI 花费</span>
              </div>
            </section>

            {office.snapshot.headline ? (
              <section className={styles.section}>
                <h3>今日快照 {office.snapshot.date ?? ""}</h3>
                <p>{office.snapshot.headline}</p>
              </section>
            ) : null}

            {actionError ? (
              <p className={styles.error} role="alert">
                {actionError}
              </p>
            ) : null}

            {canCommand ? (
              <OwnerControls busy={busy} office={office} run={run} />
            ) : (
              <p className={styles.muted}>只有老板能指挥她，你可以在这里看她干活。</p>
            )}

            <section className={styles.section}>
              <h3>目标</h3>
              <GoalList busy={busy} canCommand={canCommand} goals={office.goals} run={run} />
            </section>

            <section className={styles.section}>
              <h3>收件筐（待审 {office.pending_cards.length}）</h3>
              <Inbox busy={busy} canCommand={canCommand} office={office} run={run} />
            </section>

            <section className={styles.section}>
              <h3>流水</h3>
              {office.activity.length === 0 ? <p className={styles.muted}>还没有记录。</p> : null}
              <ol className={styles.stream}>
                {office.activity.map((item) => (
                  <li key={item.id}>
                    <time>{timeText(item.at)}</time>
                    <span>{item.text}</span>
                  </li>
                ))}
              </ol>
            </section>
          </>
        )}
      </div>
    </section>
  );
}
