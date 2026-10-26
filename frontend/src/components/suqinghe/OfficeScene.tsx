"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import partStyles from "./Office.module.css";
import styles from "./OfficeScene.module.css";
import {
  CARD_STATUS_LABEL,
  MEMORY_KIND_LABEL,
  STATE_LABEL,
  VIA_LABEL,
  DOSSIER_IN_PROGRESS,
  dossierStatusOf,
  getDossier,
  getDossiers,
  getMemory,
  getSnapshot,
  getSnapshots,
  officeErrorMessage,
  redoDossier,
  submitDossier,
  type DossierDetail,
  type DossierStatus,
  type DossierSummary,
  type MemoryItem,
  type MemoryKind,
  type OfficeRead,
  type OfficeState,
  type SnapshotDetail,
  type SnapshotSummary,
  listChat,
  openSuqingheChat,
} from "./office-api";
import { useAuth } from "@/components/auth-provider";

import { OfficeChat } from "./OfficeChat";
import { CardItem, GoalForm, GoalList, InstructForm, PauseButton, minutesAgo, pickEasterLine, timeText, type Runner } from "./OfficeParts";
import { buildDossierView, type SourceLine, type ValueRow } from "./dossier-view";

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
  | "cabinet"
  | "whiteboard"
  | "calendar"
  | "monitor"
  | "inbox"
  | "coffee"
  | "phone"
  | "cat"
  | "suqinghe";

export type PanelId = "door" | "bookshelf" | "cabinet" | "whiteboard" | "calendar" | "monitor" | "inbox" | "coffee" | "phone";

export const HOTSPOTS: { id: HotspotId; label: string; box: Box; panel: PanelId | null }[] = [
  { id: "door", label: "门口铭牌", box: [5.7, 23.4, 12.0, 42.0], panel: "door" },
  // 书柜上半是工作日志;下半的柜门是「档案柜」(1688 → K 档案),两块不重叠。
  { id: "bookshelf", label: "书柜 · 工作日志", box: [17.9, 10.9, 17.7, 29.0], panel: "bookshelf" },
  { id: "cabinet", label: "档案柜 · 1688 档案", box: [20.0, 40.5, 14.5, 20.5], panel: "cabinet" },
  { id: "whiteboard", label: "白板 · 今日计划", box: [37.3, 9.4, 16.7, 13.5], panel: "whiteboard" },
  { id: "calendar", label: "日历 · 每日快照", box: [89.4, 27.0, 6.4, 19.6], panel: "calendar" },
  { id: "monitor", label: "显示器 · 她在做什么", box: [56.3, 44.1, 9.2, 16.1], panel: "monitor" },
  { id: "inbox", label: "收件筐 · 待审卡", box: [42.0, 54.7, 9.1, 12.0], panel: "inbox" },
  { id: "coffee", label: "咖啡杯 · 今天花了多少", box: [50.4, 52.8, 4.2, 7.2], panel: "coffee" },
  { id: "phone", label: "电话 · 和她聊天", box: [65.6, 49.4, 5.6, 7.8], panel: "phone" },
  { id: "cat", label: "橘猫", box: [74.2, 65.3, 12.3, 12.5], panel: null },
  { id: "suqinghe", label: "苏青禾", box: [41.7, 23.4, 14.6, 29.7], panel: null },
];

const PANEL_TITLE: Record<PanelId, string> = {
  door: "🚪 门口铭牌",
  bookshelf: "📚 书柜 · 工作日志",
  cabinet: "🗄 档案柜 · 1688 档案",
  whiteboard: "📋 白板 · 今日计划",
  calendar: "🗓 日历 · 每日快照",
  monitor: "🖥 显示器 · 她在做什么",
  inbox: "📥 收件筐",
  coffee: "☕ 咖啡杯 · 今天的账",
  phone: "☎️ 和苏青禾聊天",
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
  const [dossierFocus, setDossierFocus] = useState<number | null>(null);
  const openDossier = useCallback((id: number | null) => {
    setDossierFocus(id);
    setOpenPanel("cabinet");
  }, []);
  const [loaded, setLoaded] = useState<Set<OfficeState>>(() => new Set([state]));
  const [hint, setHint] = useState<HotspotId | null>(null);
  const [bubble, setBubble] = useState<string | null>(null);
  const [catLine, setCatLine] = useState<string | null>(null);
  const [catPurr, setCatPurr] = useState(false);
  const { chatPing, markSeen } = useChatPing(openPanel === "phone");
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

        {bubble ? <div className={styles.speech}>{bubble}</div> : chatPing ? <div className={styles.speech}>{chatPing}</div> : null}
        {chatPing ? <span aria-hidden className={styles.phoneDot} style={{ left: "70.6%", top: "48.6%" }} /> : null}
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
                <PanelContent
                  busy={busy}
                  canCommand={canCommand}
                  dossierFocus={dossierFocus}
                  office={office}
                  onChatSeen={markSeen}
                  onOpenDossier={openDossier}
                  onOpenPanel={setOpenPanel}
                  panel={openPanel}
                  run={run}
                  setDossierFocus={setDossierFocus}
                />
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
  dossierFocus,
  setDossierFocus,
  onOpenDossier,
  onOpenPanel,
  onChatSeen,
}: {
  panel: PanelId;
  office: OfficeRead;
  canCommand: boolean;
  busy: boolean;
  run: Runner;
  dossierFocus: number | null;
  setDossierFocus: (id: number | null) => void;
  onOpenDossier: (id: number | null) => void;
  onOpenPanel: (panel: PanelId) => void;
  onChatSeen: (sequence: number) => void;
}) {
  switch (panel) {
    case "inbox":
      return <InboxPanel busy={busy} canCommand={canCommand} office={office} onOpenDossier={onOpenDossier} run={run} />;
    case "bookshelf":
      return <BookshelfPanel />;
    case "cabinet":
      return <CabinetPanel canCommand={canCommand} focus={dossierFocus} onOpenInbox={() => onOpenPanel("inbox")} setFocus={setDossierFocus} />;
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
      return <PhonePanel busy={busy} canCommand={canCommand} onSeen={onChatSeen} onSubmitted={() => onOpenDossier(null)} run={run} />;
    default:
      return null;
  }
}

function InboxPanel({
  office,
  canCommand,
  busy,
  run,
  onOpenDossier,
}: {
  office: OfficeRead;
  canCommand: boolean;
  busy: boolean;
  run: Runner;
  onOpenDossier: (id: number) => void;
}) {
  return (
    <>
      {office.pending_cards.length === 0 ? <p className={partStyles.muted}>收件筐是空的，暂时没有要批的。</p> : null}
      {office.pending_cards.map((card) => (
        <CardItem busy={busy} canCommand={canCommand} card={card} key={card.ref} onOpenDossier={onOpenDossier} run={run} />
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
      Object.entries(payload)
        .filter(([key]) => !["headline", "blockers", "generated_at", "date"].includes(key))
        .sort(([a], [b]) => sectionRank(a) - sectionRank(b)),
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
          <h3>那天的全局情况</h3>
          <dl className={styles.summary}>
            {sections.map(([key, value]) => (
              <SummaryRow key={key} label={SECTION_LABEL[key] ?? key} lines={describeSection(key, value)} />
            ))}
          </dl>
        </section>
      ) : null}
    </>
  );
}

const SECTION_ORDER = ["products", "goals", "content", "approvals", "workers", "keys", "ai"];
const sectionRank = (key: string): number => {
  const index = SECTION_ORDER.indexOf(key);
  return index < 0 ? SECTION_ORDER.length : index;
};

const STAGE_TEXT: Record<string, string> = {
  k_draft: "K 建档中",
  k_workflow: "K 流水线进行中",
  blocked_gate: "卡在 P 闸门",
  ready_to_upload: "可以上架",
  uploaded_draft: "已上传但还是草稿",
  published: "已发布",
  uploaded_unknown: "已上传（Woo 状态核不了）",
};

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const num = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);
const usd = (value: unknown): string => (typeof value === "number" ? `$${value < 0.01 && value > 0 ? value.toFixed(4) : value.toFixed(2)}` : "—");

/** 快照里每一块数据 → 几行人话。认不出的结构只给一句「有数据但这里不展示」,绝不把 JSON 原样摊出来。 */
export function describeSection(key: string, value: unknown): string[] {
  if (isRec(value) && "error" in value) return [String(value.error || "读不到")];
  switch (key) {
    case "products": {
      if (!isRec(value)) break;
      const byStage = isRec(value.by_stage) ? value.by_stage : {};
      const counts = Object.entries(byStage)
        .filter(([, n]) => num(n) > 0)
        .map(([stage, n]) => `${STAGE_TEXT[stage] ?? stage} ${num(n)}`);
      const lines = [`一共 ${num(value.total)} 个产品${counts.length ? `：${counts.join(" · ")}` : ""}`];
      if (value.woo_checked === false) lines.push("这一天 Woo 没核上，已上传的状态不确定。");
      const items = Array.isArray(value.items) ? (value.items as Rec[]) : [];
      for (const item of items.slice(0, 40)) {
        const label = String(item.stage_label ?? STAGE_TEXT[String(item.stage)] ?? item.stage ?? "");
        lines.push(`${item.sku ? `${String(item.sku)} · ` : ""}${String(item.name ?? "未命名")} —— ${label}`);
      }
      if (items.length > 40) lines.push(`……还有 ${items.length - 40} 个`);
      return lines;
    }
    case "goals": {
      const goals = Array.isArray(value) ? (value as Rec[]) : [];
      if (goals.length === 0) return ["还没定目标。"];
      return goals.map((goal) => {
        const metric = isRec(goal.metric) ? goal.metric : {};
        const target = typeof metric.target === "number" ? metric.target : null;
        const current = typeof goal.current === "number" ? goal.current : null;
        const progress = target !== null && current !== null ? `（现在 ${current} / 目标 ${target}）` : "";
        return `${String(goal.text ?? "")}${progress}`;
      });
    }
    case "content": {
      if (!isRec(value)) break;
      return [
        `已上线 ${num(value.live)} · 已生成 ${num(value.generated)} · 待审 ${num(value.pending_review)} · 批了没发 ${num(value.approved_unpublished)}`,
      ];
    }
    case "approvals": {
      if (!isRec(value)) break;
      return [num(value.pending) ? `控制台里还有 ${num(value.pending)} 条审批等人处理` : "控制台里没有积压的审批。"];
    }
    case "workers": {
      if (!isRec(value)) break;
      const stale = Array.isArray(value.stale) ? value.stale.map(String) : [];
      const lines = [stale.length ? `${num(value.total)} 个后台进程里有 ${stale.length} 个掉线：` : `${num(value.total)} 个后台进程都在干活。`];
      return lines.concat(stale.map((name) => `· ${name}`));
    }
    case "keys": {
      if (!isRec(value)) break;
      const counts = isRec(value.counts) ? value.counts : {};
      const failing = Array.isArray(value.failing) ? (value.failing as Rec[]) : [];
      const lines = [`一共 ${num(counts.total)} 把钥匙，健康 ${num(counts.healthy)} 把。`];
      if (failing.length === 0) lines.push("在用的钥匙都没问题。");
      else lines.push(`在用的坏了 ${failing.length} 把：`);
      for (const key of failing) {
        const usedBy = Array.isArray(key.used_by) && key.used_by.length ? `（${key.used_by.map(String).join("、")} 在用）` : "";
        lines.push(`· ${String(key.name ?? "?")}${usedBy}`);
      }
      if (num(value.failing_but_unused)) lines.push(`另有 ${num(value.failing_but_unused)} 把已经不用的旧钥匙坏了，不算故障。`);
      return lines;
    }
    case "ai": {
      if (!isRec(value)) break;
      return [`Claude 当天花了 ${usd(value.claude_usd_today)}，每日上限 ${usd(value.claude_daily_budget_usd)}。`];
    }
    default:
      break;
  }
  if (value === null || value === undefined) return ["没有数据。"];
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return [String(value)];
  return ["有数据，这里先不展示。"];
}

function SummaryRow({ label, lines }: { label: string; lines: string[] }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>
        {lines.map((line, index) => (
          <span className={styles.summaryLine} key={index}>
            {line}
          </span>
        ))}
      </dd>
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

function PhonePanel({
  canCommand,
  busy,
  run,
  onSubmitted,
  onSeen,
}: {
  canCommand: boolean;
  busy: boolean;
  run: Runner;
  onSubmitted: () => void;
  onSeen: (sequence: number) => void;
}) {
  return (
    <>
      <OfficeChat onSeen={onSeen} />
      {canCommand ? (
        <details className={partStyles.section}>
          <summary>其他交代方式（不用聊天）</summary>
          <p className={partStyles.muted}>交代的事她会记下来；影子期只记录，不动手。</p>
          <InstructForm busy={busy} run={run} />
          <DossierLinkForm busy={busy} onSubmitted={onSubmitted} run={run} />
        </details>
      ) : (
        <p className={partStyles.muted}>她只听老板的安排；你也可以和她聊，她会告诉你她在忙什么。</p>
      )}
    </>
  );
}

// ---------------------------------------------------------------- 新消息提醒

const CHAT_PING_POLL_MS = 15000;
const seenKey = (userId: string) => `suqinghe-chat-seen:${userId}`;

function readSeen(userId: string): number {
  try {
    return Number(window.localStorage.getItem(seenKey(userId)) || 0) || 0;
  } catch {
    return 0;
  }
}

/** 聊天窗没开时,每 15 秒看一眼她有没有发来新消息:有就在她头顶冒气泡、电话上亮红点。 */
function useChatPing(chatOpen: boolean) {
  const { user } = useAuth();
  const userId = String(user?.id ?? "");
  const [chatPing, setChatPing] = useState<string | null>(null);
  const conversationRef = useRef<string | null>(null);

  const markSeen = useCallback(
    (sequence: number) => {
      try {
        if (sequence > readSeen(userId)) window.localStorage.setItem(seenKey(userId), String(sequence));
      } catch {
        /* 浏览器不让存就算了,只是提醒 */
      }
      setChatPing(null);
    },
    [userId],
  );

  useEffect(() => {
    if (chatOpen || !userId) return undefined;
    let alive = true;
    const check = async () => {
      if (document.hidden) return;
      try {
        conversationRef.current = conversationRef.current ?? (await openSuqingheChat());
        if (!conversationRef.current || !alive) return;
        const recent = await listChat(conversationRef.current, 5);
        const hers = recent.filter((message) => String(message.sender_user_id) !== userId);
        const latest = hers.at(-1);
        if (alive && latest && latest.sequence > readSeen(userId)) {
          const text = latest.content_type === "text" ? latest.content : "（发来一个附件）";
          setChatPing(text.length > 40 ? `${text.slice(0, 40)}…` : text);
        }
      } catch {
        /* 提醒是锦上添花,拉不到就等下一轮 */
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), CHAT_PING_POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [chatOpen, userId]);

  return { chatPing, markSeen };
}

// ---------------------------------------------------------------- 档案柜(1688 → K 档案)

/** 客户端只做最粗的一道:像 1688 商品链接才发。真正的解析和拒绝在后端。 */
export function looksLike1688Offer(value: string): boolean {
  const text = value.trim();
  return /1688\.com\/offer\/\d+/i.test(text) || /[?&](offerId|offer_id)=\d+/i.test(text);
}

function DossierLinkForm({ busy, onSubmitted }: { busy: boolean; run: Runner; onSubmitted: () => void }) {
  const [url, setUrl] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const valid = looksLike1688Offer(url);
  return (
    <form
      className={styles.linkForm}
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid || sending) return;
        setSending(true);
        setError(null);
        submitDossier(url.trim())
          .then(() => {
            setUrl("");
            onSubmitted();
          })
          .catch((err: unknown) => setError(officeErrorMessage(err, "没交上")))
          .finally(() => setSending(false));
      }}
    >
      <label htmlFor="sqh-1688-link">丢一个 1688 链接给她</label>
      <input
        id="sqh-1688-link"
        onChange={(event) => setUrl(event.target.value)}
        placeholder="https://detail.1688.com/offer/……html"
        value={url}
      />
      {url && !valid ? <p className={partStyles.muted}>这看起来不像 1688 商品链接（要有 1688.com/offer/数字）。</p> : null}
      {error ? <p className={partStyles.error}>{error}</p> : null}
      <button className={partStyles.primary} disabled={busy || sending || !valid} type="submit">
        {sending ? "交给她…" : "交给她整理成 K 档案"}
      </button>
    </form>
  );
}

function CabinetPanel({
  canCommand,
  focus,
  setFocus,
  onOpenInbox,
}: {
  canCommand: boolean;
  focus: number | null;
  setFocus: (id: number | null) => void;
  onOpenInbox: () => void;
}) {
  const [items, setItems] = useState<DossierSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inProgress = (items ?? []).some((item) => DOSSIER_IN_PROGRESS.includes(item.status) || item.building);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getDossiers(40)
        .then((data) => {
          if (alive) {
            setItems(data.items);
            setError(null);
          }
        })
        .catch((err: unknown) => alive && setError(officeErrorMessage(err, "档案柜打不开")));
    void load();
    const timer = inProgress ? window.setInterval(load, 5000) : null;
    return () => {
      alive = false;
      if (timer) window.clearInterval(timer);
    };
  }, [inProgress]);

  if (focus !== null) {
    return <DossierView canCommand={canCommand} id={focus} onBack={() => setFocus(null)} onOpenInbox={onOpenInbox} onRedone={setFocus} />;
  }
  return (
    <>
      {error ? <p className={partStyles.error}>{error}</p> : null}
      {items === null && !error ? <p className={partStyles.muted}>开柜门…</p> : null}
      {items !== null && items.length === 0 ? (
        <p className={partStyles.muted}>柜子是空的。老板可以在电话里丢一个 1688 链接给她。</p>
      ) : null}
      <ul className={styles.dossierList}>
        {(items ?? []).map((item) => (
          <li key={item.id}>
            <button onClick={() => setFocus(item.id)} type="button">
              <span className={styles.dossierTitle}>{item.title || `1688 · ${item.offer_id}`}</span>
              <span className={styles.dossierMeta}>
                <span className={styles.dossierStatus} data-status={dossierStatusOf(item).key}>
                  {dossierStatusOf(item).label}
                </span>
                {item.flagged_count > 0 ? <span className={styles.flagBadge}>标红 {item.flagged_count}</span> : null}
                {typeof item.cost_usd === "number" && item.cost_usd > 0 ? <span>${item.cost_usd.toFixed(3)}</span> : null}
                <time>{timeText(item.created_at)}</time>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

/** 哪些状态能「重新整理」:待批、没整理成、被拦、已驳回。建进 K 的要去 K 里改;还在整理的等它做完。 */
const REDO_STATUSES: DossierStatus[] = ["ready", "failed", "blocked", "rejected"];

function DossierView({
  id,
  canCommand,
  onBack,
  onOpenInbox,
  onRedone,
}: {
  id: number;
  canCommand: boolean;
  onBack: () => void;
  onOpenInbox: () => void;
  onRedone: (id: number) => void;
}) {
  const [detail, setDetail] = useState<DossierDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [redoing, setRedoing] = useState(false);
  const [redoNote, setRedoNote] = useState<string | null>(null);
  const inProgress = detail ? DOSSIER_IN_PROGRESS.includes(detail.status) || Boolean(detail.building) : true;
  // 草稿 → 界面那一层是纯函数(dossier-view.ts),用真档案测过;这里只管画。
  const view = useMemo(() => buildDossierView(detail?.draft), [detail]);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getDossier(id)
        .then((data) => {
          if (alive) {
            setDetail(data);
            setError(null);
          }
        })
        .catch((err: unknown) => alive && setError(officeErrorMessage(err, "这份档案打不开")));
    void load();
    const timer = inProgress ? window.setInterval(load, 5000) : null;
    return () => {
      alive = false;
      if (timer) window.clearInterval(timer);
    };
  }, [id, inProgress]);

  const redo = () => {
    if (!detail || redoing) return;
    setRedoing(true);
    setRedoNote(null);
    redoDossier(detail.id)
      .then((next) => {
        setRedoNote(next.reply ?? "重新排上了。");
        onRedone(next.id);
      })
      .catch((err: unknown) => setRedoNote(officeErrorMessage(err, "没能重新整理")))
      .finally(() => setRedoing(false));
  };

  const okBasics = view.basics.filter((row) => row.status === "ok");
  const okSpecs = view.specs.filter((row) => row.status === "ok");
  const hasVariantSpecs = view.variants.some((row) => row.specs !== "—");

  return (
    <>
      <button className={partStyles.linkButton} onClick={onBack} type="button">
        ← 回档案柜
      </button>
      {error ? <p className={partStyles.error}>{error}</p> : null}
      {!detail && !error ? <p className={partStyles.muted}>翻档案…</p> : null}
      {detail ? (
        <>
          <section className={partStyles.section}>
            <h3>{detail.title || `1688 · ${detail.offer_id}`}</h3>
            <p className={styles.dossierHead}>
              <span className={styles.dossierStatus} data-status={dossierStatusOf(detail).key}>
                {dossierStatusOf(detail).label}
              </span>
              {detail.flagged_count > 0 ? <span className={styles.flagBadge}>标红 {detail.flagged_count}</span> : null}
              {typeof detail.cost_usd === "number" && detail.cost_usd > 0 ? <span>花了 ${detail.cost_usd.toFixed(3)}</span> : null}
              {detail.source_url ? (
                <a href={detail.source_url} rel="noreferrer" target="_blank">
                  1688 原页面 ↗
                </a>
              ) : null}
            </p>
            {view.summary ? <p>{view.summary}</p> : null}
            <p className={styles.readingLine}>
              {view.reading.text}
              {view.reading.problem ? <em>{view.reading.problem}</em> : null}
              {view.reading.ignored ? <small>{view.reading.ignored}</small> : null}
            </p>
            {detail.status === "failed" && detail.error ? <p className={partStyles.error}>没整理成:{detail.error}</p> : null}
            {inProgress ? (
              <p className={partStyles.muted}>{detail.building ? "批了，她正在建进 K，" : "她还在整理，"}这里每 5 秒刷新一次。</p>
            ) : null}
            {view.version < 2 && !inProgress && detail.status !== "created" ? (
              <p className={styles.oldRulesNote}>
                这份是按旧规则整理的(10-26 之前){canCommand ? ",点「重新整理」按新规则重做。" : ",老板可以让她按新规则重做。"}
              </p>
            ) : null}
            <div className={partStyles.inlineActions}>
              {detail.card_ref && detail.status === "ready" && !detail.building ? (
                <button className={partStyles.primary} onClick={onOpenInbox} type="button">
                  去收件筐批（#{detail.card_ref}）
                </button>
              ) : null}
              {canCommand && REDO_STATUSES.includes(detail.status) && !detail.building ? (
                <button disabled={redoing} onClick={redo} type="button">
                  {redoing ? "重新排队…" : "重新整理"}
                </button>
              ) : null}
            </div>
            {redoNote ? <p className={partStyles.muted}>{redoNote}</p> : null}
            {detail.k_product_id ? (
              <p>
                已建进 K：<a href="/products">去 K 系列看</a>（产品 {detail.k_product_id}）
              </p>
            ) : null}
          </section>

          {view.attention.length > 0 ? (
            <section className={partStyles.section}>
              <h3>要你看的（{view.attention.length}）</h3>
              <div className={styles.fieldTable}>
                {view.attention.map((row) => (
                  <DossierRow key={`attention-${row.key}`} row={row} />
                ))}
              </div>
            </section>
          ) : null}

          {okBasics.length > 0 ? (
            <section className={partStyles.section}>
              <h3>基本信息</h3>
              <div className={styles.fieldTable}>
                {okBasics.map((row) => (
                  <DossierRow key={row.key} row={row} />
                ))}
              </div>
            </section>
          ) : null}

          {okSpecs.length > 0 ? (
            <section className={partStyles.section}>
              <h3>规格</h3>
              <div className={styles.fieldTable}>
                {okSpecs.map((row) => (
                  <DossierRow key={row.key} row={row} />
                ))}
              </div>
            </section>
          ) : null}

          {view.variants.length > 0 ? (
            <section className={partStyles.section}>
              <h3>规格 / 变体（{view.variants.length}）</h3>
              <div className={styles.scrollX}>
                <table className={styles.dossierTable}>
                  <thead>
                    <tr>
                      <th>1688 规格名</th>
                      <th>英文</th>
                      <th>进价</th>
                      {hasVariantSpecs ? <th>参数</th> : null}
                      <th>包装重量</th>
                      <th>包装尺寸</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.variants.map((row, index) => (
                      <tr key={`${row.nameZh}-${index}`}>
                        <td>{row.nameZh}</td>
                        <td>{row.nameEn}</td>
                        <td>{row.cost}</td>
                        {hasVariantSpecs ? <td>{row.specs}</td> : null}
                        <td>{row.packWeight}</td>
                        <td>{row.packDims}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className={partStyles.muted}>包装重量和尺寸来自 1688「包装信息」,是一件的发货包装,不是产品本身。</p>
            </section>
          ) : null}

          <section className={partStyles.section}>
            <h3>进价（1688，仅供参考）</h3>
            <p>{view.pricing.text}</p>
            {view.pricing.tiers.length > 1 ? (
              <ul className={partStyles.list}>
                {view.pricing.tiers.map((tier) => (
                  <li key={tier.qty}>
                    <span>≥ {tier.qty} 件</span>
                    <span>{tier.price}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>

          {view.otherAttributes.length > 0 ? (
            <section className={partStyles.section}>
              <h3>页面上的其他属性</h3>
              <div className={styles.fieldTable}>
                {view.otherAttributes.map((attr) => (
                  <div className={styles.fieldRow} data-status="ok" key={attr.name}>
                    <span className={styles.fieldLabel}>{attr.name}</span>
                    <span className={styles.fieldValue}>{attr.value}</span>
                    <span />
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {view.supplier ? (
            <section className={partStyles.section}>
              <h3>供应商</h3>
              <p>
                {view.supplier.name}
                {view.supplier.detail ? <small className={styles.fieldNote}>{view.supplier.detail}</small> : null}
                {view.supplier.url ? (
                  <a href={view.supplier.url} rel="noreferrer" target="_blank">
                    店铺 ↗
                  </a>
                ) : null}
              </p>
            </section>
          ) : null}

          {view.images.length > 0 ? (
            <section className={partStyles.section}>
              <h3>参考图（{view.images.length}）</h3>
              <div className={styles.refImages}>
                {view.images.slice(0, 12).map((url) => (
                  <a href={url} key={url} rel="noreferrer" target="_blank">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img alt="参考图" loading="lazy" referrerPolicy="no-referrer" src={url} />
                  </a>
                ))}
              </div>
            </section>
          ) : null}
        </>
      ) : null}
    </>
  );
}

function sourceText(source: SourceLine): string {
  return source.raw ? `${source.where}：「${source.raw}」` : source.where;
}

/** 一行:标签 | 值(+ 标红原因)| 出处按钮。说法不一的直接摊一张「说法 / 谁说的」小表。 */
function DossierRow({ row }: { row: ValueRow }) {
  const [open, setOpen] = useState(false);
  const conflict = row.status === "conflict" && row.candidates.length > 0;
  const extra = row.sources.length + row.alternatives.length + row.perVariant.length;
  return (
    <div className={styles.fieldRow} data-status={row.status}>
      <span className={styles.fieldLabel}>{row.label}</span>
      <span className={styles.fieldValue}>
        {conflict ? null : row.value}
        {row.statusLabel ? <em className={styles.fieldFlag}>{row.statusLabel}</em> : null}
        {row.note && !conflict ? <small className={styles.fieldNote}>{row.note}</small> : null}
      </span>
      {extra > 0 && !conflict ? (
        <button className={styles.sourceToggle} onClick={() => setOpen((value) => !value)} type="button">
          {open ? "收起" : `出处 ${row.sources.length}`}
        </button>
      ) : (
        <span />
      )}
      {conflict ? (
        <div className={styles.choiceBlock}>
          <table className={styles.dossierTable}>
            <thead>
              <tr>
                <th>说法</th>
                <th>谁说的</th>
              </tr>
            </thead>
            <tbody>
              {row.candidates.map((choice, index) => (
                <tr key={index}>
                  <td>{choice.value}</td>
                  <td>{choice.sources.map(sourceText).join("；") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {row.alternatives.length > 0 ? (
            <small className={styles.fieldNote}>
              另外还有(把握低,不算数):{row.alternatives.map((alt) => alt.value).join("、")}
            </small>
          ) : null}
        </div>
      ) : null}
      {open ? (
        <div className={styles.choiceBlock}>
          {row.perVariant.length > 0 ? (
            <small className={styles.fieldNote}>按规格:{row.perVariant.map(([name, value]) => `${name} = ${value}`).join("；")}</small>
          ) : null}
          {row.sources.length > 0 ? (
            <ul className={styles.sourceList}>
              {row.sources.map((source, index) => (
                <li key={index}>{sourceText(source)}</li>
              ))}
            </ul>
          ) : null}
          {row.alternatives.length > 0 ? (
            <small className={styles.fieldNote}>
              其他说法(不标红):{row.alternatives.map((alt) => (alt.why ? `${alt.value}(${alt.why})` : alt.value)).join("；")}
            </small>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
