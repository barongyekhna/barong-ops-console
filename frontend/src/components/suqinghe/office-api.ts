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
