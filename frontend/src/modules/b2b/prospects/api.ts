"use client";

import { b2bRequest } from "../api-base";

/**
 * 扫店和机器初筛都是**同步**的：run_sweep 逐条打 Serper，screen_prospects
 * 逐家读官网再过 AI 漏斗。规模随查询数/店铺数长，默认 15 秒必然不够。
 * 收口前它们一个超时都没有。
 */
const SLOW_SWEEP_TIMEOUT_MS = 300_000;

const LABEL = "B2B 客户挖掘";

export type ProspectStatus =
  | "new"
  | "approved"
  | "rejected"
  | "contacted"
  | "replied"
  | "customer";

export type Prospect = {
  id: string;
  store_name: string;
  website: string | null;
  phone: string | null;
  address: string | null;
  city: string | null;
  region: string | null;
  country: string;
  rating: string | null;
  reviews_count: number | null;
  store_type: string;
  language: string;
  source_query: string | null;
  place_category: string | null;
  place_cid: string | null;
  website_source: string | null;
  screen_verdict: "fit" | "unfit" | "unsure" | null;
  screen_reason: string | null;
  screen_signals: Record<string, boolean> | null;
  maps_url: string | null;
  chain_hint: string | null;
  email: string | null;
  email_verified: boolean;
  contact_name: string | null;
  status: ProspectStatus;
  reject_reason: string | null;
  notes: string | null;
  created_at: string;
};

export type ProspectList = {
  items: Prospect[];
  count: number;
  new_count: number;
  approved_count: number;
  rejected_count: number;
  contacted_count: number;
  replied_count: number;
  customer_count: number;
};

export type ProspectQuery = {
  id: string;
  store_type: string;
  store_type_label: string;
  country: string;
  language: string;
  query_template: string;
  active: boolean;
};

export type SweepResult = {
  queries_executed: number;
  places_seen: number;
  prospects_created: number;
  quota_stopped: boolean;
  quota_used_today: number;
  quota_budget: number;
  errors: string[];
};

export async function getProspects(params: {
  status?: ProspectStatus | "";
  country?: string;
  storeType?: string;
  verdict?: string;
} = {}): Promise<ProspectList> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.country) query.set("country", params.country);
  if (params.storeType) query.set("store_type", params.storeType);
  if (params.verdict) query.set("verdict", params.verdict);
  query.set("limit", "300");
    return b2bRequest<ProspectList>(`/b2b/prospects?${query.toString()}`, LABEL);
}

export async function reviewProspect(
  prospectId: string,
  payload: { approve: boolean; reject_reason?: string; notes?: string },
): Promise<Prospect> {
    return b2bRequest<Prospect>(
      `/b2b/prospects/${encodeURIComponent(prospectId)}/review`,
      LABEL,
      { body: payload, method: "PATCH" },
    );
}

export async function getProspectQueries(): Promise<ProspectQuery[]> {
    return b2bRequest<ProspectQuery[]>("/b2b/prospect-queries", LABEL);
}

export async function getQuota(): Promise<SweepResult> {
    return b2bRequest<SweepResult>("/b2b/prospect-quota", LABEL);
}

export async function runSweep(payload: {
  max_queries: number;
  country?: string;
  store_type?: string;
}): Promise<SweepResult> {
  return b2bRequest<SweepResult>("/b2b/prospect-sweep", LABEL, {
    body: payload,
    method: "POST",
    timeoutMs: SLOW_SWEEP_TIMEOUT_MS,
  });
}

export async function seedProspectConfig(): Promise<{
  queries_added: number;
  cities_added: number;
}> {
    return b2bRequest<{ queries_added: number; cities_added: number }>("/b2b/prospect-config/seed", LABEL, { method: "POST" });
}

export type ScreenResult = {
  screened: number;
  fit: number;
  unfit: number;
  unsure: number;
  quota_stopped: boolean;
  quota_used_today: number;
  message: string;
};

/** 机器读官网，给每家店判个结论 + 一句人话。 */
export async function screenProspects(payload: {
  limit: number;
  store_type?: string;
}): Promise<ScreenResult> {
  return b2bRequest<ScreenResult>("/b2b/prospect-screen", LABEL, {
    body: payload,
    method: "POST",
    timeoutMs: SLOW_SWEEP_TIMEOUT_MS,
  });
}
