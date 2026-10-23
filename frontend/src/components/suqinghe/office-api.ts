"use client";

import { ApiError, apiRequest } from "@/lib/api";

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
  can_command: boolean;
  server_time: string;
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

/** 档案柜:一个 1688 链接 → 一份 K 档案草稿(后端 /suqinghe/dossiers)。 */
export type DossierStatus = "queued" | "fetching" | "reading" | "ready" | "blocked" | "failed" | "created" | "rejected";

export type DossierSummary = {
  id: number;
  offer_id: string;
  status: DossierStatus;
  title: string | null;
  flagged_count: number;
  cost_usd: number | null;
  card_ref: string | null;
  k_product_id: string | null;
  created_at: string;
  error?: string | null;
  source_url?: string;
  /** 只有 POST 提交时返回:排第几、要不要重新排、她回的一句话。 */
  position?: number;
  created?: boolean;
  reply?: string;
};

// kind 以后端为准:writer = 英文名是按事实改写的,classifier = 类目是判定出来的;认不出的照原样显示。
export type DraftSource = { kind: "page_json" | "page_text" | "image" | "writer" | "classifier" | "precedent" | (string & {}); ref?: string; raw?: string };

export type DraftField = {
  value: unknown;
  unit?: string | null;
  sources?: DraftSource[];
  status: "ok" | "conflict" | "missing" | "needs_owner";
  note?: string;
};

export type DossierDetail = DossierSummary & {
  capture: Record<string, unknown>;
  draft: Record<string, DraftField | unknown>;
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

export const DOSSIER_STATUS_LABEL: Record<DossierStatus, string> = {
  queued: "排队",
  fetching: "在抓页面",
  reading: "在读图",
  ready: "待你批",
  blocked: "被1688拦了",
  failed: "失败",
  created: "已建进K",
  rejected: "已驳回",
};

export const DOSSIER_IN_PROGRESS: DossierStatus[] = ["queued", "fetching", "reading"];

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
