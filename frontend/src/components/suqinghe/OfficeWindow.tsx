"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type PointerEvent as ReactPointerEvent } from "react";

import styles from "./Office.module.css";
import {
  CARD_STATUS_LABEL,
  STATE_LABEL,
  VIA_LABEL,
  addGoal,
  controlOffice,
  decideCard,
  instructOffice,
  officeErrorMessage,
  patchGoal,
  portraitFor,
  type OfficeCard,
  type OfficeRead,
  type OfficeState,
} from "./office-api";

const POSITION_KEY = "suqinghe-office-position";
const MOBILE_QUERY = "(max-width: 760px)";

// 彩蛋:连点肖像 5 下。纯前端、固定台词,不调 AI。口吻是女强人 + 温柔大姐姐,不撒娇不暧昧。
const EASTER_LINES = [
  "今天的活我扛着，你去喝口水。",
  "别急，先把最要紧的一件做完，剩下的交给我。",
  "数据我盯着呢，有事我第一时间说。",
  "你定方向，细活我来跑。",
  "今天也辛苦了，早点休息，明天见。",
  "卡片我都排好序了，你挑最上面那张就行。",
];

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

function minutesAgo(seconds: number | null): string {
  if (seconds == null) return "从没上过线";
  if (seconds < 60) return "刚刚";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟没动静`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} 小时没动静` : `${Math.round(hours / 24)} 天没动静`;
}

function timeText(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour: "2-digit", minute: "2-digit", month: "numeric", day: "numeric" });
  } catch {
    return iso;
  }
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

  useEffect(() => {
    const media = window.matchMedia(MOBILE_QUERY);
    const sync = () => setIsMobile(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    const stored = readPosition();
    const width = 420;
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
      setBubble(EASTER_LINES[Math.floor(Math.random() * EASTER_LINES.length)]);
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

  return (
    <section
      aria-label="苏青禾的办公室"
      className={`${styles.window} ${isMobile ? styles.windowSheet : ""}`}
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
        <button aria-label="关闭办公室" className={styles.close} onClick={onClose} type="button">
          ×
        </button>
      </header>

      <div className={styles.body}>
        {!office ? (
          <p className={styles.muted}>{loadError ?? "正在推开办公室的门…"}</p>
        ) : (
          <>
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
              {office.goals.length === 0 ? <p className={styles.muted}>还没有目标。</p> : null}
              <ul className={styles.list}>
                {office.goals.map((goal) => (
                  <li key={goal.id}>
                    <span>
                      {goal.text}
                      {goal.status === "paused" ? <em className={styles.tag}>暂停</em> : null}
                    </span>
                    {canCommand ? (
                      <span className={styles.inlineActions}>
                        <button
                          disabled={busy}
                          onClick={() =>
                            void run("调整目标失败", () => patchGoal(goal.id, { status: goal.status === "paused" ? "active" : "paused" }))
                          }
                          type="button"
                        >
                          {goal.status === "paused" ? "恢复" : "暂停"}
                        </button>
                        <button disabled={busy} onClick={() => void run("调整目标失败", () => patchGoal(goal.id, { status: "done" }))} type="button">
                          完成
                        </button>
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>

            <section className={styles.section}>
              <h3>等老板批的卡（{office.pending_cards.length}）</h3>
              {office.pending_cards.length === 0 ? <p className={styles.muted}>暂时没有要批的。</p> : null}
              {office.pending_cards.map((card) => (
                <CardItem busy={busy} canCommand={canCommand} card={card} key={card.ref} run={run} />
              ))}
            </section>

            {office.recent_cards.length > 0 ? (
              <section className={styles.section}>
                <h3>最近定下的</h3>
                <ul className={styles.list}>
                  {office.recent_cards.map((card) => (
                    <li key={card.ref}>
                      <span>
                        #{card.ref} {card.title}
                      </span>
                      <span className={styles.tag} data-status={card.status}>
                        {CARD_STATUS_LABEL[card.status] ?? card.status}
                        {card.decided_via ? ` · ${VIA_LABEL[card.decided_via] ?? card.decided_via}` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

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

type Runner = (label: string, action: () => Promise<unknown>) => Promise<boolean>;

function CardItem({ card, canCommand, busy, run }: { card: OfficeCard; canCommand: boolean; busy: boolean; run: Runner }) {
  const [expanded, setExpanded] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  return (
    <article className={styles.card}>
      <button className={styles.cardHead} onClick={() => setExpanded((value) => !value)} type="button">
        <span className={styles.cardRef}>#{card.ref}</span>
        <strong>{card.title}</strong>
      </button>
      <p>{card.conclusion}</p>
      {expanded ? (
        <dl className={styles.cardDetail}>
          {card.why ? (
            <>
              <dt>为什么</dt>
              <dd>{card.why}</dd>
            </>
          ) : null}
          {card.if_not ? (
            <>
              <dt>不做会怎样</dt>
              <dd>{card.if_not}</dd>
            </>
          ) : null}
          <dt>能不能撤回</dt>
          <dd>{card.reversible ? "能" : "不能"}</dd>
          <dt>把握</dt>
          <dd>{card.confidence === "high" ? "高" : card.confidence === "low" ? "低" : "中"}</dd>
          <dt>证据</dt>
          <dd>
            <pre>{JSON.stringify(card.evidence, null, 2)}</pre>
          </dd>
        </dl>
      ) : null}
      {canCommand ? (
        rejecting ? (
          <form
            className={styles.rejectForm}
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              if (!reason.trim()) return;
              void run("驳回失败", () => decideCard(card.ref, "reject", reason.trim())).then((ok) => {
                if (ok) {
                  setRejecting(false);
                  setReason("");
                }
              });
            }}
          >
            <textarea
              aria-label="驳回原因"
              onChange={(event) => setReason(event.target.value)}
              placeholder="驳回原因（必填，她会记住）"
              rows={2}
              value={reason}
            />
            <div className={styles.inlineActions}>
              <button disabled={busy || !reason.trim()} type="submit">
                确认驳回
              </button>
              <button onClick={() => setRejecting(false)} type="button">
                取消
              </button>
            </div>
          </form>
        ) : (
          <div className={styles.inlineActions}>
            <button className={styles.primary} disabled={busy} onClick={() => void run("批准失败", () => decideCard(card.ref, "approve"))} type="button">
              批
            </button>
            <button disabled={busy} onClick={() => setRejecting(true)} type="button">
              驳
            </button>
          </div>
        )
      ) : null}
    </article>
  );
}

function OwnerControls({ office, busy, run }: { office: OfficeRead; busy: boolean; run: Runner }) {
  const [instruction, setInstruction] = useState("");
  const [goalText, setGoalText] = useState("");
  const [metric, setMetric] = useState("");
  const [target, setTarget] = useState("");

  return (
    <section className={`${styles.section} ${styles.owner}`}>
      <div className={styles.inlineActions}>
        <button
          disabled={busy}
          onClick={() => void run(office.paused ? "恢复失败" : "暂停失败", () => controlOffice(office.paused ? "resume" : "pause"))}
          type="button"
        >
          {office.paused ? "让她接着干" : "先停一停"}
        </button>
      </div>
      <form
        className={styles.row}
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          const text = instruction.trim();
          if (!text) return;
          void run("交代失败", () => instructOffice(text)).then((ok) => ok && setInstruction(""));
        }}
      >
        <input aria-label="交代一句" onChange={(event) => setInstruction(event.target.value)} placeholder="交代一句…" value={instruction} />
        <button disabled={busy || !instruction.trim()} type="submit">
          交代
        </button>
      </form>
      <form
        className={styles.row}
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          const text = goalText.trim();
          if (text.length < 2) return;
          const numericTarget = target.trim() ? Number(target) : undefined;
          void run("加目标失败", () =>
            addGoal(text, metric.trim() || undefined, Number.isFinite(numericTarget) ? numericTarget : undefined),
          ).then((ok) => {
            if (ok) {
              setGoalText("");
              setMetric("");
              setTarget("");
            }
          });
        }}
      >
        <input aria-label="新目标" onChange={(event) => setGoalText(event.target.value)} placeholder="新目标，如：店里做到 30 个品" value={goalText} />
        <input aria-label="指标（可选）" className={styles.narrow} onChange={(event) => setMetric(event.target.value)} placeholder="指标" value={metric} />
        <input aria-label="目标值（可选）" className={styles.narrow} inputMode="decimal" onChange={(event) => setTarget(event.target.value)} placeholder="数值" value={target} />
        <button disabled={busy || goalText.trim().length < 2} type="submit">
          加目标
        </button>
      </form>
    </section>
  );
}
