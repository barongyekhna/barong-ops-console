"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";
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

function buildHeaders(json = false) {
  const headers = new Headers({ Accept: "application/json" });
  if (json) {
    headers.set("Content-Type", "application/json");
  }
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  return headers;
}

async function readJson<T>(response: Response): Promise<T> {
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: string };
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail || `${LABEL}（${response.status}）`);
  }
  return (await response.json()) as T;
}

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
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/prospects?${query.toString()}`,
    { cache: "no-store", headers: buildHeaders() },
  );
  return readJson<ProspectList>(response);
}

export async function reviewProspect(
  prospectId: string,
  payload: { approve: boolean; reject_reason?: string; notes?: string },
): Promise<Prospect> {
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/prospects/${encodeURIComponent(prospectId)}/review`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "PATCH",
    },
  );
  return readJson<Prospect>(response);
}

export async function getProspectQueries(): Promise<ProspectQuery[]> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/prospect-queries`, {
    cache: "no-store",
    headers: buildHeaders(),
  });
  return readJson<ProspectQuery[]>(response);
}

export async function getQuota(): Promise<SweepResult> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/prospect-quota`, {
    cache: "no-store",
    headers: buildHeaders(),
  });
  return readJson<SweepResult>(response);
}

export async function runSweep(payload: {
  max_queries: number;
  country?: string;
  store_type?: string;
}): Promise<SweepResult> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/prospect-sweep`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<SweepResult>(response);
}

export async function seedProspectConfig(): Promise<{
  queries_added: number;
  cities_added: number;
}> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/prospect-config/seed`, {
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<{ queries_added: number; cities_added: number }>(response);
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
  const response = await fetch(`${API_PROXY_BASE}/b2b/prospect-screen`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<ScreenResult>(response);
}
