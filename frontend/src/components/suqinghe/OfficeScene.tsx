"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import partStyles from "./Office.module.css";
import styles from "./OfficeScene.module.css";
import {
  CARD_STATUS_LABEL,
  MEMORY_KIND_LABEL,
  STATE_LABEL,
  VIA_LABEL,
  getMemory,
  getSnapshot,
  getSnapshots,
  officeErrorMessage,
  type MemoryItem,
  type MemoryKind,
  type OfficeRead,
  type OfficeState,
  type SnapshotDetail,
  type SnapshotSummary,
} from "./office-api";
import { CardItem, GoalForm, GoalList, InstructForm, PauseButton, minutesAgo, pickEasterLine, timeText, type Runner } from "./OfficeParts";

/**
 * 苏青禾的 2.5D 办公室场景。
 *
 * 五张整幅场景图(每张都画好了她在椅子上的样子)按真实状态切换,上面叠可点的物件热区。
 * 热区坐标是对着美术定稿手工标的,单位是舞台百分比 [left, top, width, height],
 * 随舞台缩放自动跟着走。动画层只由后端算好的 office.state / paused 驱动,不自己演。
 */

const STATES: OfficeState[] = ["working", "thinking", "raised", "night", "offline"];

export function sceneFor(state: OfficeState): string {
  return `/assets/agents/suqinghe/office/scene_${state}.webp`;
}

type Box = [number, number, number, number];

export type HotspotId =
  | "door"
  | "bookshelf"
  | "whiteboard"
  | "calendar"
  | "monitor"
  | "inbox"
  | "coffee"
  | "phone"
  | "cat"
  | "suqinghe";

export type PanelId = "door" | "bookshelf" | "whiteboard" | "calendar" | "monitor" | "inbox" | "coffee" | "phone";

export const HOTSPOTS: { id: HotspotId; label: string; box: Box; panel: PanelId | null }[] = [
  { id: "door", label: "门口铭牌", box: [5.7, 23.4, 12.0, 42.0], panel: "door" },
  { id: "bookshelf", label: "书柜 · 工作日志", box: [17.9, 10.9, 17.7, 50.3], panel: "bookshelf" },
  { id: "whiteboard", label: "白板 · 今日计划", box: [37.3, 9.4, 16.7, 13.5], panel: "whiteboard" },
  { id: "calendar", label: "日历 · 每日快照", box: [89.4, 27.0, 6.4, 19.6], panel: "calendar" },
  { id: "monitor", label: "显示器 · 她在做什么", box: [56.3, 44.1, 9.2, 16.1], panel: "monitor" },
  { id: "inbox", label: "收件筐 · 待审卡", box: [42.0, 54.7, 9.1, 12.0], panel: "inbox" },
  { id: "coffee", label: "咖啡杯 · 今天花了多少", box: [50.4, 52.8, 4.2, 7.2], panel: "coffee" },
  { id: "phone", label: "电话 · 交代一句", box: [65.6, 49.4, 5.6, 7.8], panel: "phone" },
  { id: "cat", label: "橘猫", box: [74.2, 65.3, 12.3, 12.5], panel: null },
  { id: "suqinghe", label: "苏青禾", box: [41.7, 23.4, 14.6, 29.7], panel: null },
];

const PANEL_TITLE: Record<PanelId, string> = {
  door: "🚪 门口铭牌",
  bookshelf: "📚 书柜 · 工作日志",
  whiteboard: "📋 白板 · 今日计划",
  calendar: "🗓 日历 · 每日快照",
  monitor: "🖥 显示器 · 她在做什么",
  inbox: "📥 收件筐",
  coffee: "☕ 咖啡杯 · 今天的账",
  phone: "☎️ 电话",
};

const CAT_LINES = ["喵……（翻了个身）", "喵！（她说今天的卡都排好了）", "呼噜呼噜……", "喵？（老板来啦）"];

const HINT_KEY = "suqinghe-office-hinted";

const SECTION_LABEL: Record<string, string> = {
  products: "产品流水线",
  content: "内容",
  workers: "后台进程",
  keys: "钥匙",
  ai: "AI 花费",
  approvals: "待审批",
  goals: "目标",
};

function boxStyle([left, top, width, height]: Box): CSSProperties {
  return { left: `${left}%`, top: `${top}%`, width: `${width}%`, height: `${height}%` };
}

function centerOf(id: PanelId): string {
  const spot = HOTSPOTS.find((item) => item.id === id);
  if (!spot) return "50% 50%";
  const [left, top, width, height] = spot.box;
  return `${left + width / 2}% ${top + height / 2}%`;
}

export function OfficeScene({
  office,
  busy,
  run,
  isMobile,
  onSceneFailed,
}: {
  office: OfficeRead;
  busy: boolean;
  run: Runner;
  isMobile: boolean;
  onSceneFailed: () => void;
}) {
  const state = office.state;
  const canCommand = Boolean(office.can_command);
  const [openPanel, setOpenPanel] = useState<PanelId | null>(null);
  const [loaded, setLoaded] = useState<Set<OfficeState>>(() => new Set([state]));
  const [hint, setHint] = useState<HotspotId | null>(null);
  const [bubble, setBubble] = useState<string | null>(null);
  const [catLine, setCatLine] = useState<string | null>(null);
  const [catPurr, setCatPurr] = useState(false);
  const herClicks = useRef<number[]>([]);
  const catClicks = useRef<number[]>([]);

  // 当前状态的图一定要有;其余四张等首屏画完再悄悄预载,切换时直接淡入。
  useEffect(() => {
    setLoaded((prev) => (prev.has(state) ? prev : new Set([...prev, state])));
  }, [state]);
  const preloadRest = useCallback(() => {
    window.setTimeout(() => setLoaded(new Set(STATES)), 1200);
  }, []);

  // 第一次进办公室:各物件轮流闪一下,告诉人哪些能点。
  useEffect(() => {
    let seen = false;
    try {
      seen = window.localStorage.getItem(HINT_KEY) === "1";
      if (!seen) window.localStorage.setItem(HINT_KEY, "1");
    } catch {
      seen = true;
    }
    if (seen) return;
    const order = HOTSPOTS.map((item) => item.id);
    let index = 0;
    const timer = window.setInterval(() => {
      if (index >= order.length) {
        window.clearInterval(timer);
        setHint(null);
        return;
      }
      setHint(order[index]);
      index += 1;
    }, 480);
    return () => window.clearInterval(timer);
  }, []);

  // 有面板开着时,Esc 只关面板,不关整个办公室。
  useEffect(() => {
    if (!openPanel) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopImmediatePropagation();
        setOpenPanel(null);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [openPanel]);

  const onHotspot = (id: HotspotId, panel: PanelId | null) => {
    if (id === "suqinghe") {
      const now = Date.now();
      herClicks.current = [...herClicks.current.filter((at) => now - at < 3000), now];
      if (herClicks.current.length >= 5) {
        herClicks.current = [];
        setBubble(pickEasterLine());
        window.setTimeout(() => setBubble(null), 4500);
      }
      return;
    }
    if (id === "cat") {
      const now = Date.now();
      catClicks.current = [...catClicks.current.filter((at) => now - at < 3000), now];
      setCatLine(CAT_LINES[Math.floor(Math.random() * CAT_LINES.length)]);
      window.setTimeout(() => setCatLine(null), 3200);
      if (catClicks.current.length >= 3) {
        catClicks.current = [];
        setCatPurr(true);
        window.setTimeout(() => setCatPurr(false), 2600);
      }
      return;
    }
    setOpenPanel(panel);
  };

  const doorText = state === "offline" ? `联系不上 · ${minutesAgo(office.heartbeat.silent_seconds)}` : office.paused ? "暂停中" : "在岗";
  const pending = office.pending_cards.length;

  return (
    <div className={styles.scene}>
      <div
        className={styles.stage}
        data-paused={office.paused ? "true" : "false"}
        data-state={state}
      >
        {STATES.filter((item) => loaded.has(item)).map((item) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            alt={item === state ? `苏青禾的办公室 · ${STATE_LABEL[item]}` : ""}
            aria-hidden={item !== state}
            className={styles.layer}
            data-active={item === state ? "true" : "false"}
            draggable={false}
            height={1024}
            key={item}
            onError={item === state ? onSceneFailed : undefined}
            onLoad={item === state ? preloadRest : undefined}
            src={sceneFor(item)}
            width={1536}
          />
        ))}

        {/* 动画层:只跟着真实状态走,不挡点击 */}
        <div aria-hidden className={styles.fx}>
          {state === "working" ? (
            <>
              <span className={styles.screenGlow} />
              <span className={styles.steam}>
                <i />
                <i />
                <i />
              </span>
            </>
          ) : null}
          {state === "thinking" ? (
            <span className={styles.thought}>
              <i />
              <i />
              <i />
            </span>
          ) : null}
          {state === "raised" ? <span className={styles.exclaim}>!</span> : null}
          {state === "night" ? (
            <>
              <span className={styles.lampGlow} />
            </>
          ) : null}
          {state === "offline" ? <span className={styles.screenOff} /> : null}
          {catPurr ? <span className={styles.purr}>♪</span> : null}
        </div>

        <span className={styles.doorTag} data-tone={state === "offline" ? "bad" : office.paused ? "warn" : "ok"}>
          {doorText}
        </span>
        {pending > 0 ? (
          <span aria-hidden className={styles.inboxBadge}>
            {pending}
          </span>
        ) : null}

        {HOTSPOTS.map((spot) => (
          <button
            aria-label={spot.label}
            className={styles.hotspot}
            data-hint={hint === spot.id ? "true" : "false"}
            data-id={spot.id}
            data-pulse={spot.id === "inbox" && state === "raised" ? "true" : "false"}
            key={spot.id}
            onClick={() => onHotspot(spot.id, spot.panel)}
            style={boxStyle(spot.box)}
            type="button"
          >
            <span className={styles.hotspotName}>{spot.label}</span>
          </button>
        ))}

        {bubble ? <div className={styles.speech}>{bubble}</div> : null}
        {catLine ? <div className={styles.catSpeech}>{catLine}</div> : null}

      </div>
      <p className={styles.caption}>
        <span className={styles.stateDot} data-state={state} />
        {STATE_LABEL[state]}
        {office.paused ? " · 暂停中" : ""} · {office.task || "在岗待命"}
      </p>
      {/* 面板放在舞台外面:舞台掉线时带 grayscale 滤镜,滤镜会让 fixed 定位的手机抽屉跟着舞台走、也跟着变灰 */}
        {openPanel ? (
          <>
            <button aria-label="关上" className={styles.scrim} onClick={() => setOpenPanel(null)} type="button" />
            <section
              aria-label={PANEL_TITLE[openPanel]}
              className={`${styles.panel} ${isMobile ? styles.panelSheet : ""}`}
              role="dialog"
              style={{ transformOrigin: centerOf(openPanel) }}
            >
              <header className={styles.panelHeader}>
                <strong>
                  {PANEL_TITLE[openPanel]}
                  {openPanel === "inbox" ? ` · 待审 ${pending}` : ""}
                </strong>
                <button aria-label="关上" className={styles.panelClose} onClick={() => setOpenPanel(null)} type="button">
                  ×
                </button>
              </header>
              <div className={styles.panelBody}>
                <PanelContent busy={busy} canCommand={canCommand} office={office} panel={openPanel} run={run} />
              </div>
            </section>
          </>
        ) : null}
    </div>
  );
}

function PanelContent({
  panel,
  office,
  canCommand,
  busy,
  run,
}: {
  panel: PanelId;
  office: OfficeRead;
  canCommand: boolean;
  busy: boolean;
  run: Runner;
}) {
  switch (panel) {
    case "inbox":
      return <InboxPanel busy={busy} canCommand={canCommand} office={office} run={run} />;
    case "bookshelf":
      return <BookshelfPanel />;
    case "whiteboard":
      return <WhiteboardPanel busy={busy} canCommand={canCommand} office={office} run={run} />;
    case "calendar":
      return <CalendarPanel />;
    case "monitor":
      return <MonitorPanel office={office} />;
    case "coffee":
      return <CoffeePanel office={office} />;
    case "door":
      return <DoorPanel busy={busy} canCommand={canCommand} office={office} run={run} />;
    case "phone":
      return <PhonePanel busy={busy} canCommand={canCommand} run={run} />;
    default:
      return null;
  }
}

function InboxPanel({ office, canCommand, busy, run }: { office: OfficeRead; canCommand: boolean; busy: boolean; run: Runner }) {
  return (
    <>
      {office.pending_cards.length === 0 ? <p className={partStyles.muted}>收件筐是空的，暂时没有要批的。</p> : null}
      {office.pending_cards.map((card) => (
        <CardItem busy={busy} canCommand={canCommand} card={card} key={card.ref} run={run} />
      ))}
      {!canCommand && office.pending_cards.length > 0 ? <p className={partStyles.muted}>只有老板能批这些卡。</p> : null}
      {office.recent_cards.length > 0 ? (
        <section className={partStyles.section}>
          <h3>最近定下的</h3>
          <ul className={partStyles.list}>
            {office.recent_cards.map((card) => (
              <li key={card.ref}>
                <span>
                  #{card.ref} {card.title}
                </span>
                <span className={partStyles.tag} data-status={card.status}>
                  {CARD_STATUS_LABEL[card.status] ?? card.status}
                  {card.decided_via ? ` · ${VIA_LABEL[card.decided_via] ?? card.decided_via}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

function BookshelfPanel() {
  const [kind, setKind] = useState<MemoryKind | "">("");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const timer = window.setTimeout(() => {
      getMemory({ kind: kind || undefined, q: query, limit: 60 })
        .then((data) => {
          if (alive) {
            setItems(data.items);
            setError(null);
          }
        })
        .catch((err: unknown) => alive && setError(officeErrorMessage(err, "工作日志读取失败")));
    }, query ? 400 : 0);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [kind, query]);

  return (
    <>
      <div className={styles.chips}>
        <button data-active={kind === "" ? "true" : "false"} onClick={() => setKind("")} type="button">
          全部
        </button>
        {Object.entries(MEMORY_KIND_LABEL).map(([key, label]) => (
          <button data-active={kind === key ? "true" : "false"} key={key} onClick={() => setKind(key as MemoryKind)} type="button">
            {label}
          </button>
        ))}
      </div>
      <input
        aria-label="在工作日志里搜"
        className={styles.search}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="搜一搜：SKU、产品名、驳回原因…"
        value={query}
      />
      {error ? <p className={partStyles.error}>{error}</p> : null}
      {items === null && !error ? <p className={partStyles.muted}>翻书中…</p> : null}
      {items !== null && items.length === 0 ? <p className={partStyles.muted}>没翻到。</p> : null}
      <ol className={styles.memoryList}>
        {(items ?? []).map((item) => (
          <li key={item.id}>
            <div className={styles.memoryMeta}>
              <span className={partStyles.tag}>{MEMORY_KIND_LABEL[item.kind] ?? item.kind}</span>
              <time>{timeText(item.created_at)}</time>
            </div>
            {item.subject ? <strong>{item.subject}</strong> : null}
            <p>{item.body}</p>
          </li>
        ))}
      </ol>
    </>
  );
}

function WhiteboardPanel({ office, canCommand, busy, run }: { office: OfficeRead; canCommand: boolean; busy: boolean; run: Runner }) {
  const [plan, setPlan] = useState<MemoryItem | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    getMemory({ kind: "plan", limit: 1 })
      .then((data) => alive && setPlan(data.items[0] ?? null))
      .catch(() => alive && setPlan(null));
    return () => {
      alive = false;
    };
  }, []);
  return (
    <>
      <section className={partStyles.section}>
        <h3>{plan?.subject || "今日计划"}</h3>
        {plan === undefined ? <p className={partStyles.muted}>擦白板中…</p> : null}
        {plan === null ? <p className={partStyles.muted}>今天的计划还没写（她每天洛杉矶早上 7 点出计划）。</p> : null}
        {plan ? <p className={styles.planText}>{plan.body}</p> : null}
      </section>
      <section className={partStyles.section}>
        <h3>目标</h3>
        <GoalList busy={busy} canCommand={canCommand} goals={office.goals} run={run} />
        {canCommand ? <GoalForm busy={busy} run={run} /> : null}
      </section>
    </>
  );
}

function CalendarPanel() {
  const [days, setDays] = useState<SnapshotSummary[] | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [detail, setDetail] = useState<SnapshotDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getSnapshots(30)
      .then((data) => {
        if (!alive) return;
        setDays(data.items);
        if (data.items[0]) setPicked(data.items[0].date);
      })
      .catch((err: unknown) => alive && setError(officeErrorMessage(err, "日历读取失败")));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!picked) return;
    let alive = true;
    setDetail(null);
    getSnapshot(picked)
      .then((data) => alive && setDetail(data))
      .catch((err: unknown) => alive && setError(officeErrorMessage(err, "这一天的快照读取失败")));
    return () => {
      alive = false;
    };
  }, [picked]);

  return (
    <>
      {error ? <p className={partStyles.error}>{error}</p> : null}
      {days !== null && days.length === 0 ? <p className={partStyles.muted}>日历还是空的。</p> : null}
      <div className={styles.chips}>
        {(days ?? []).map((day) => (
          <button data-active={picked === day.date ? "true" : "false"} key={day.date} onClick={() => setPicked(day.date)} type="button">
            {day.date.slice(5)}
          </button>
        ))}
      </div>
      {detail ? <SnapshotView detail={detail} /> : picked ? <p className={partStyles.muted}>翻到 {picked}…</p> : null}
    </>
  );
}

function SnapshotView({ detail }: { detail: SnapshotDetail }) {
  const payload = detail.payload ?? {};
  const blockers = Array.isArray(payload.blockers) ? (payload.blockers as { product?: unknown; stage?: unknown; reasons?: unknown }[]) : [];
  const sections = useMemo(
    () =>
      Object.entries(payload).filter(([key]) => !["headline", "blockers", "generated_at", "date"].includes(key)),
    [payload],
  );
  return (
    <>
      <section className={partStyles.section}>
        <h3>{detail.date}</h3>
        <p>{detail.headline || "这一天没有标题。"}</p>
      </section>
      <section className={partStyles.section}>
        <h3>卡在哪（{blockers.length}）</h3>
        {blockers.length === 0 ? <p className={partStyles.muted}>这一天没有卡点。</p> : null}
        <ul className={partStyles.list}>
          {blockers.map((item, index) => (
            <li key={index}>
              <span>
                <strong>{String(item.product ?? "?")}</strong> · {String(item.stage ?? "")}
              </span>
              <span className={styles.reasons}>{Array.isArray(item.reasons) ? item.reasons.map(String).join("；") : String(item.reasons ?? "")}</span>
            </li>
          ))}
        </ul>
      </section>
      {sections.length > 0 ? (
        <section className={partStyles.section}>
          <h3>其他</h3>
          <dl className={styles.summary}>
            {sections.map(([key, value]) => (
              <SummaryRow key={key} label={SECTION_LABEL[key] ?? key} value={value} />
            ))}
          </dl>
        </section>
      ) : null}
    </>
  );
}

function SummaryRow({ label, value }: { label: string; value: unknown }) {
  let text: string;
  if (value && typeof value === "object" && "error" in (value as Record<string, unknown>)) {
    text = String((value as Record<string, unknown>).error || "读不到");
  } else {
    try {
      text = JSON.stringify(value);
    } catch {
      text = String(value);
    }
    if (text.length > 220) text = `${text.slice(0, 220)}…`;
  }
  return (
    <>
      <dt>{label}</dt>
      <dd>{text}</dd>
    </>
  );
}

function MonitorPanel({ office }: { office: OfficeRead }) {
  return (
    <>
      <section className={partStyles.section}>
        <h3>此刻</h3>
        <p>{office.task || (office.paused ? "暂停中，等老板发话" : "在岗待命")}</p>
        {typeof office.progress === "number" ? (
          <div aria-label={`进度 ${office.progress}%`} className={partStyles.progress} role="progressbar">
            <span style={{ width: `${Math.max(0, Math.min(100, office.progress))}%` }} />
          </div>
        ) : null}
        {office.state === "offline" ? <p className={partStyles.offlineLine}>她联系不上了 · {minutesAgo(office.heartbeat.silent_seconds)}</p> : null}
      </section>
      <section className={partStyles.section}>
        <h3>流水</h3>
        {office.activity.length === 0 ? <p className={partStyles.muted}>还没有记录。</p> : null}
        <ol className={partStyles.stream}>
          {office.activity.map((item) => (
            <li key={item.id}>
              <time>{timeText(item.at)}</time>
              <span>{item.text}</span>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

function CoffeePanel({ office }: { office: OfficeRead }) {
  return (
    <>
      <section className={partStyles.kpis}>
        <div>
          <b>{office.today.claude_usd == null ? "—" : `$${office.today.claude_usd.toFixed(2)}`}</b>
          <span>今天 AI 花费</span>
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
          <b>{office.today.cards_pending}</b>
          <span>待批</span>
        </div>
      </section>
      {office.snapshot.headline ? (
        <section className={partStyles.section}>
          <h3>今日快照 {office.snapshot.date ?? ""}</h3>
          <p>{office.snapshot.headline}</p>
        </section>
      ) : null}
    </>
  );
}

function DoorPanel({ office, canCommand, busy, run }: { office: OfficeRead; canCommand: boolean; busy: boolean; run: Runner }) {
  return (
    <section className={partStyles.section}>
      <p>
        现在：<strong>{STATE_LABEL[office.state]}</strong>
        {office.paused ? " · 暂停中" : ""}
      </p>
      <p className={partStyles.muted}>最近一次干成活：{office.heartbeat.last_success_at ? timeText(office.heartbeat.last_success_at) : "还没有"}</p>
      {canCommand ? (
        <div className={partStyles.inlineActions}>
          <PauseButton busy={busy} office={office} run={run} />
        </div>
      ) : (
        <p className={partStyles.muted}>只有老板能让她暂停或接着干。</p>
      )}
    </section>
  );
}

function PhonePanel({ canCommand, busy, run }: { canCommand: boolean; busy: boolean; run: Runner }) {
  return (
    <section className={partStyles.section}>
      {canCommand ? (
        <>
          <p className={partStyles.muted}>交代的事她会记下来；影子期只记录，不动手。</p>
          <InstructForm busy={busy} run={run} />
        </>
      ) : (
        <p className={partStyles.muted}>只有老板能给她打电话。</p>
      )}
    </section>
  );
}
