"use client";

const API_PROXY_BASE = "/api/backend";
const NOTIFICATIONS_PATH = "/notifications";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";

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

export class NotificationApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "NotificationApiError";
  }
}

function readAccessToken() {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
}

function buildHeaders(hasBody = false) {
  const headers = new Headers({ Accept: "application/json" });
  const token = readAccessToken();
  if (hasBody) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const detail = (await response.json())?.detail;
      if (typeof detail === "string" && detail) {
        message = detail;
      }
    } catch {
      // keep default message
    }
    throw new NotificationApiError(message, response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

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
  const path = query ? `${NOTIFICATIONS_PATH}?${query}` : NOTIFICATIONS_PATH;
  const response = await fetch(`${API_PROXY_BASE}${path}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<NotificationListResult>(response);
}

export async function getUnreadCount(): Promise<number> {
  const path = `${NOTIFICATIONS_PATH}/unread-count`;
  const response = await fetch(`${API_PROXY_BASE}${path}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  const data = await readJson<{ unread: number }>(response);
  return data.unread ?? 0;
}

export async function markNotificationRead(id: number): Promise<number> {
  const path = `${NOTIFICATIONS_PATH}/${id}/read`;
  const response = await fetch(`${API_PROXY_BASE}${path}`, {
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  const data = await readJson<{ updated: number }>(response);
  return data.updated ?? 0;
}

export async function markAllNotificationsRead(): Promise<number> {
  const path = `${NOTIFICATIONS_PATH}/read-all`;
  const response = await fetch(`${API_PROXY_BASE}${path}`, {
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  const data = await readJson<{ updated: number }>(response);
  return data.updated ?? 0;
}
