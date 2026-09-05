"use client";

import { apiRequest } from "@/lib/api";

/** 与后端 `modules/home/schemas.py` 一一对应。 */
export type HomeCardSeverity = "ok" | "warn" | "error";

export type HomeCardItem = {
  id: string;
  title: string;
  subtitle: string;
  at: string | null;
  href: string;
};

export type HomeCardRead = {
  card_id: string;
  module_key: string | null;
  count: number | null;
  items: HomeCardItem[];
  freshness: string;
  actions: string[];
  extra: Record<string, unknown>;
  severity: HomeCardSeverity;
};

export type HomeBootstrapRead = {
  org_type: string;
  org_id: string;
  cards: HomeCardRead[];
  poll_seconds: number;
};

export type HomeTrafficDay = { day: string; views: number; visitors: number };

export type HomeTrafficSummary = {
  site_utc_offset: string;
  day_from: string;
  day_to: string;
  days: HomeTrafficDay[];
  views: number;
  visitors: number;
  prev_views: number;
  prev_visitors: number;
  today: HomeTrafficDay | null;
  yesterday: HomeTrafficDay | null;
  top_post: Record<string, unknown> | null;
  top_referrer: Record<string, unknown> | null;
  top_country: Record<string, unknown> | null;
  collected_at: string | null;
  collector_stale: boolean;
};

export type HomeTrafficRange = HomeTrafficSummary & {
  top_posts: Array<Record<string, unknown>>;
  referrers: Array<Record<string, unknown>>;
  countries: Array<Record<string, unknown>>;
  search_terms: Array<Record<string, unknown>>;
  encrypted_search_terms: number;
  clicks: Array<Record<string, unknown>>;
};

export const HOME_BOOTSTRAP_PATH = "/dashboard/home";
export const HOME_STREAM_PROXY_PATH = "/api/backend/dashboard/home/stream";

export function getHomeBootstrap(signal?: AbortSignal) {
  return apiRequest<HomeBootstrapRead>(HOME_BOOTSTRAP_PATH, {
    method: "GET",
    bypassCache: true,
    signal,
  });
}

export function getHomeCard(cardId: string, signal?: AbortSignal) {
  return apiRequest<HomeCardRead>(
    `/dashboard/home/cards/${encodeURIComponent(cardId)}`,
    { method: "GET", bypassCache: true, signal },
  );
}

export function getHomeTraffic(days: number, signal?: AbortSignal) {
  return apiRequest<HomeTrafficSummary>(
    `/dashboard/home/traffic?days=${encodeURIComponent(String(days))}`,
    { method: "GET", bypassCache: true, signal },
  );
}

export function getHomeTrafficRange(from: string, to: string, signal?: AbortSignal) {
  const query = new URLSearchParams({ from, to }).toString();
  return apiRequest<HomeTrafficRange>(`/dashboard/home/traffic/range?${query}`, {
    method: "GET",
    bypassCache: true,
    signal,
  });
}

export function formatClock(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
