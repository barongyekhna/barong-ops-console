"use client";

// 通知的接口层。请求一律走 `lib/api.ts` —— 超时、GET 重试、路由切换取消、
// 401 派发、中文错误兜底、并发闸门都在那里，本文件不再自造。
//
// 2026-09-02 收口前这里有一整套复制品：自己的 API_PROXY_BASE、自己的
// readJson、自己的 NotificationApiError，以及一段读 `barong_ops_access_token`
// 拼 `Authorization: Bearer` 的代码 —— 那段是**死代码**：全仓 19 处 getItem、
// 0 处 setItem，代理 route.ts 也根本不读 Authorization（只认 x-session-token
// 和 cookie）。它能工作靠的是同源 Cookie，跟这个头无关。
//
// `/notifications` 在 request-cache 的 cacheTtlForPath 里 TTL=0（不缓存），
// 所以两处轮询不需要 bypassCache。

import { apiRequest } from "@/lib/api";

const NOTIFICATIONS_PATH = "/notifications";

export type NotificationLevel = "info" | "success" | "warning" | "error";
export type NotificationStatus = "unread" | "read" | "archived";

export type NotificationItem = {
  id: number;
  org_id: string | null;
  source: string;
  event_type: string;
  level: string;
  title: string;
  body: string | null;
  product_id: string | null;
  external_refs: Record<string, unknown> | null;
  payload: Record<string, unknown> | null;
  status: string;
  read_at: string | null;
  created_at: string;
};

export type NotificationListResult = {
  items: NotificationItem[];
  count: number;
  unread: number;
  limit: number;
  offset: number;
};

export async function getNotifications(options?: {
  status?: NotificationStatus;
  level?: NotificationLevel;
  limit?: number;
  offset?: number;
}): Promise<NotificationListResult> {
  const params = new URLSearchParams();
  if (options?.status) params.set("status", options.status);
  if (options?.level) params.set("level", options.level);
  if (options?.limit != null) params.set("limit", String(options.limit));
  if (options?.offset != null) params.set("offset", String(options.offset));
  const query = params.toString();
  return apiRequest<NotificationListResult>(
    query ? `${NOTIFICATIONS_PATH}?${query}` : NOTIFICATIONS_PATH,
  );
}

export async function getUnreadCount(): Promise<number> {
  const data = await apiRequest<{ unread: number }>(
    `${NOTIFICATIONS_PATH}/unread-count`,
  );
  return data.unread ?? 0;
}

export async function markNotificationRead(id: number): Promise<number> {
  const data = await apiRequest<{ updated: number }>(
    `${NOTIFICATIONS_PATH}/${id}/read`,
    { method: "POST" },
  );
  return data.updated ?? 0;
}

export async function markAllNotificationsRead(): Promise<number> {
  const data = await apiRequest<{ updated: number }>(
    `${NOTIFICATIONS_PATH}/read-all`,
    { method: "POST" },
  );
  return data.updated ?? 0;
}
