"use client";

import { ApiError, apiRequest } from "@/lib/api";
import {
  createC19DirectConversation,
  listC19Directory,
  listC19MessageHistory,
  sendC19Message,
} from "@/modules/c19/api";
import type { C19MessageRecord } from "@/modules/c19/types";

/** 与后端 `modules/agent_series/suqinghe/office.py` 的 office_payload 一一对应。 */
export type OfficeState = "working" | "thinking" | "raised" | "night" | "offline";

export type OfficeCard = {
  ref: string;
  kind: string;
  title: string;
  conclusion: string;
  why: string;
  if_not: string;
  reversible: boolean;
  confidence: "low" | "medium" | "high" | string;
  evidence: unknown;
  status: "pending" | "approved" | "rejected" | "stale" | "expired" | string;
  decided_via: "web" | "c19" | "mcp" | null;
  decision_reason: string | null;
  decided_at: string | null;
  created_at: string | null;
};

export type OfficeGoal = {
  id: number;
  text: string;
  metric: { metric?: string; target?: number } | Record<string, never>;
  status: "active" | "paused" | "done" | "dropped" | string;
};

export type OfficeActivity = { id: number; kind: string; text: string; at: string | null };

export type OfficeRead = {
  state: OfficeState;
  paused: boolean;
  task: string;
  progress: number | null;
  state_updated_at: string | null;
  heartbeat: { last_success_at: string | null; silent_seconds: number | null; stale: boolean };
  today: { cards_created: number; cards_decided: number; cards_pending: number; claude_usd: number | null };
  snapshot: { date: string | null; headline: string | null };
  goals: OfficeGoal[];
  pending_cards: OfficeCard[];
  recent_cards: OfficeCard[];
  activity: OfficeActivity[];
  /** 她的登录浏览器此刻的状态(10-28);老后端没有这个字段 */
  browser?: BrowserStatus;
  /** 运营看板(10-30):最新一天 / 最新一周的标题和异常;老后端没有这个字段 */
  digest?: { day: DigestSummary | null; week: DigestSummary | null };
  can_command: boolean;
  server_time: string;
};

/** 后端 /suqinghe/browser(office.browser_payload)。 */
export type BrowserStatus = {
  status: "idle" | "fetching" | "needs_human" | "interactive" | "asking_seller" | string;
  reason: string | null;
  url: string | null;
  title: string | null;
  dossier_id: number | null;
  frame_at: string | null;
  viewer_seen_at: string | null;
  logged_in_at: string | null;
};

const BASE = "/suqinghe";

/** 后端错误是 `{code, message}`;把 message 拿出来给人看,拿不到再退回标签。 */
export function officeErrorMessage(error: unknown, label: string): string {
  if (error instanceof ApiError) {
    const detail = error.detail as { message?: unknown } | string | null;
    if (detail && typeof detail === "object" && typeof detail.message === "string") {
      return detail.message;
    }
    if (typeof detail === "string" && detail) {
      return detail;
    }
    return `${label}（${error.status}）`;
  }
  return error instanceof Error && error.message ? error.message : label;
}

export function getOffice() {
  return apiRequest<OfficeRead>(`${BASE}/office`, { fallbackMessage: "苏青禾的办公室加载失败" });
}

export function decideCard(ref: string, decision: "approve" | "reject", reason?: string) {
  return apiRequest<{ changed: boolean; card: OfficeCard }>(`${BASE}/cards/${encodeURIComponent(ref)}/decide`, {
    body: { decision, reason: reason ?? null },
    method: "POST",
  });
}

/** 白板上能跟踪进度的数。后端快照只认这些键(snapshot.goals_section),别让老板手打英文键名。 */
export const GOAL_METRICS: { value: string; label: string }[] = [
  { value: "", label: "不跟踪" },
  { value: "published_products", label: "店里发布的品数" },
];

export function addGoal(text: string, metric?: string, target?: number) {
  return apiRequest<OfficeGoal>(`${BASE}/goals`, {
    body: { text, metric: metric || null, target: target ?? null },
    method: "POST",
  });
}

export function patchGoal(id: number, patch: { status?: OfficeGoal["status"]; text?: string }) {
  return apiRequest<OfficeGoal>(`${BASE}/goals/${id}`, { body: patch, method: "PATCH" });
}

export function controlOffice(action: "pause" | "resume") {
  return apiRequest<{ paused: boolean }>(`${BASE}/control`, { body: { action }, method: "POST" });
}

export function instructOffice(text: string) {
  return apiRequest<{ id: number; queued: boolean }>(`${BASE}/instruct`, { body: { text }, method: "POST" });
}

/** 书柜:她的硬记忆(后端 GET /suqinghe/memory)。 */
export type MemoryKind = "plan" | "suggestion" | "decision" | "note" | "dictation" | "observation";

export type MemoryItem = {
  id: number;
  kind: MemoryKind | string;
  subject: string;
  body: string;
  refs: Record<string, unknown>;
  source: string;
  created_at: string | null;
};

export function getMemory(params: { kind?: MemoryKind; q?: string; limit?: number } = {}) {
  const query = new URLSearchParams();
  if (params.kind) query.set("kind", params.kind);
  if (params.q && params.q.trim()) query.set("q", params.q.trim());
  if (params.limit) query.set("limit", String(params.limit));
  const suffix = query.toString();
  return apiRequest<{ items: MemoryItem[] }>(`${BASE}/memory${suffix ? `?${suffix}` : ""}`);
}

/** 日历:每天一份全局快照(后端 GET /suqinghe/snapshots[/{date}])。 */
export type SnapshotSummary = { date: string; headline: string | null; created_at: string | null };
export type SnapshotDetail = { date: string; headline: string | null; payload: Record<string, unknown> };

export function getSnapshots(limit = 30) {
  return apiRequest<{ items: SnapshotSummary[] }>(`${BASE}/snapshots?limit=${limit}`);
}

export function getSnapshot(date: string) {
  return apiRequest<SnapshotDetail>(`${BASE}/snapshots/${encodeURIComponent(date)}`);
}

/** 运营看板(10-30):后端 /suqinghe/digests。日报只进这里和早间快照,周报另发一张「看板」卡。 */
export type DigestKind = "day" | "week";
export type DigestFindingRead = { code: string; severity: "warn" | "info"; text: string; numbers?: Record<string, unknown> };
export type DigestSummary = { kind: DigestKind; period_key: string; headline: string | null; generated_at: string | null; findings: DigestFindingRead[]; warnings: number };
export type DigestDetail = DigestSummary & { sections: Array<{ heading: string; rows: Array<[string, string, string | null]> }>; payload: Record<string, unknown> };

export function getDigests(kind?: DigestKind, limit = 14) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (kind) query.set("kind", kind);
  return apiRequest<{ items: DigestSummary[] }>(`${BASE}/digests?${query.toString()}`);
}

export function getDigest(kind: DigestKind, periodKey: string) {
  return apiRequest<DigestDetail>(`${BASE}/digests/${kind}/${encodeURIComponent(periodKey)}`);
}

/** 档案柜:一个 1688 链接 → 一份 K 档案草稿(后端 /suqinghe/dossiers)。 */
export type DossierStatus = "queued" | "fetching" | "reading" | "ready" | "blocked" | "failed" | "created" | "rejected" | "needs_human";

export type DossierSummary = {
  id: number;
  offer_id: string;
  status: DossierStatus;
  title: string | null;
  flagged_count: number;
  cost_usd: number | null;
  card_ref: string | null;
  k_product_id: string | null;
  /** 卡批了、worker 还在建进 K(几秒钟);档案状态这时还是 ready。 */
  building?: boolean;
  created_at: string;
  error?: string | null;
  source_url?: string;
  /** 只有 POST 提交时返回:排第几、要不要重新排、她回的一句话。 */
  position?: number;
  created?: boolean;
  reply?: string;
};

/** draft 的结构由后端定(dossier.py,有版本号);界面只经 dossier-view.ts 读它,这里不再猜字段。 */
export type DossierDetail = DossierSummary & {
  capture: Record<string, unknown>;
  draft: unknown;
};

export function submitDossier(url: string) {
  return apiRequest<DossierSummary>(`${BASE}/dossiers`, { body: { url }, method: "POST" });
}

export function getDossiers(limit = 30) {
  return apiRequest<{ items: DossierSummary[] }>(`${BASE}/dossiers?limit=${limit}`);
}

export function getDossier(id: number) {
  return apiRequest<DossierDetail>(`${BASE}/dossiers/${encodeURIComponent(String(id))}`);
}

/** 老板点「重新整理」:旧档案作废(待批的卡按驳回处理),同一个链接按新规则重排。返回新排的那份。 */
export function redoDossier(id: number) {
  return apiRequest<DossierSummary>(`${BASE}/dossiers/${encodeURIComponent(String(id))}/redo`, { method: "POST" });
}

export const DOSSIER_STATUS_LABEL: Record<DossierStatus, string> = {
  queued: "排队",
  fetching: "在抓页面",
  reading: "在读图",
  ready: "待你批",
  blocked: "被1688拦了",
  failed: "失败",
  created: "已建进K",
  rejected: "已驳回",
  needs_human: "等你过验证",
};

/** 她的登录浏览器(10-28):状态、画面、老板的动作。 */
export function getBrowser(viewer = false) {
  return apiRequest<BrowserStatus>(`${BASE}/browser${viewer ? "?viewer=1" : ""}`);
}

/** 画面是 JPEG,带时间戳防缓存;后端也回 no-store。 */
export function browserFrameUrl(now: number = Date.now()) {
  return `/api/backend${BASE}/browser/frame?t=${now}`;
}

export type BrowserInputKind = "click" | "down" | "move" | "up" | "type" | "key" | "wheel" | "navigate" | "dump";

export function sendBrowserInput(kind: BrowserInputKind, payload: Record<string, unknown> = {}) {
  return apiRequest<{ id: number; queued: boolean }>(`${BASE}/browser/input`, { body: { kind, payload }, method: "POST" });
}

export function browserLogin() {
  return apiRequest<{ id: number; queued: boolean }>(`${BASE}/browser/login`, { method: "POST" });
}

export function browserClose() {
  return apiRequest<{ id: number; queued: boolean }>(`${BASE}/browser/close`, { method: "POST" });
}

export const DOSSIER_IN_PROGRESS: DossierStatus[] = ["queued", "fetching", "reading"];

/** 档案柜里显示的状态:批了还在建的那几秒显示「已批，建档中」,别让老板以为没批上。 */
export function dossierStatusOf(item: Pick<DossierSummary, "status" | "building">): { key: string; label: string } {
  if (item.building && item.status === "ready") return { key: "building", label: "已批，建档中" };
  return { key: item.status, label: DOSSIER_STATUS_LABEL[item.status] ?? item.status };
}

export const MEMORY_KIND_LABEL: Record<string, string> = {
  plan: "计划",
  suggestion: "建议",
  decision: "决定",
  note: "笔记",
  dictation: "老板交代",
  observation: "观察",
};

export const STATE_LABEL: Record<OfficeState, string> = {
  working: "干活",
  thinking: "在想",
  raised: "举手",
  night: "夜班",
  offline: "掉线",
};

export const VIA_LABEL: Record<string, string> = { web: "网页", c19: "C19", mcp: "MCP" };

export const CARD_STATUS_LABEL: Record<string, string> = {
  pending: "待批",
  approved: "已批",
  rejected: "已驳",
  stale: "已作废",
  expired: "已过期",
};

export function portraitFor(state: OfficeState): string {
  return `/assets/agents/suqinghe/${state}.webp`;
}

export const AVATAR_SRC = "/assets/agents/suqinghe/avatar.webp";

// ---------------------------------------------------------------- 办公室里的聊天窗
// 就是 C19 里你和她的那条私聊:同一份消息,两边都能看、都能发,不另起一套。

export type ChatMessage = C19MessageRecord;

let suqingheUserIdCache: number | null = null;

/** 在 C19 通讯录里找到苏青禾(机器人、显示名「苏青禾」)。 */
export async function findSuqingheUserId(): Promise<number | null> {
  if (suqingheUserIdCache !== null) return suqingheUserIdCache;
  const page = await listC19Directory({ search: "苏青禾", limit: 10 });
  const hit = page.items.find((profile) => profile.display_name === "苏青禾" && profile.is_bot !== false);
  suqingheUserIdCache = hit ? hit.user_id : null;
  return suqingheUserIdCache;
}

/** 找到(或建好)你和她的私聊。C19 按两个人去重,已有的直接返回。 */
export async function openSuqingheChat(): Promise<string | null> {
  const peer = await findSuqingheUserId();
  if (peer === null) return null;
  const conversation = await createC19DirectConversation({ peer_user_id: peer });
  return conversation.conversation_id;
}

export async function listChat(conversationId: string, limit = 40): Promise<ChatMessage[]> {
  const page = await listC19MessageHistory(conversationId, { limit });
  return [...page.records].sort((a, b) => a.sequence - b.sequence);
}

export function sendChat(conversationId: string, text: string) {
  const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  return sendC19Message(conversationId, { client_message_id: `office-${id}`, content_type: "text", content: text });
}
