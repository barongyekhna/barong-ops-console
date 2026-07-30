"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

export type CraftFact = {
  id: string;
  topic: string;
  claim: string;
  detail: string | null;
  value: string | null;
  unit: string | null;
  basis: string | null;
  status: string;
  version: number;
  product_ids: string[];
  approved_at: string | null;
  updated_at: string | null;
};

export type StaleFact = {
  fact_id: string;
  topic: string;
  claim: string;
  used_version: number;
  current_version: number;
};

export type StaleContent = {
  content_kind: string;
  content_id: string;
  stale_facts: StaleFact[];
};

export type FactsState = {
  facts: CraftFact[];
  topics: string[];
  approved_count: number;
  stale: StaleContent[];
};

export type FactRevision = {
  version: number;
  snapshot: Record<string, unknown>;
  change_reason: string | null;
  changed_at: string | null;
};

export type FactDraft = {
  topic: string;
  claim: string;
  detail?: string | null;
  value?: string | null;
  unit?: string | null;
  basis?: string | null;
  change_reason?: string | null;
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

async function readJson<T>(response: Response, label: string): Promise<T> {
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: string };
      detail = typeof body?.detail === "string" ? `：${body.detail}` : "";
    } catch {
      detail = "";
    }
    throw new Error(`${label}（${response.status}）${detail}`);
  }
  return (await response.json()) as T;
}

export async function listFacts(): Promise<FactsState> {
  const response = await fetch(`${API_PROXY_BASE}/seo/facts`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson(response, "工艺事实库加载失败");
}

export async function createFact(draft: FactDraft): Promise<CraftFact> {
  const response = await fetch(`${API_PROXY_BASE}/seo/facts`, {
    body: JSON.stringify(draft),
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "新增工艺事实失败");
}

export async function updateFact(
  factId: string,
  draft: FactDraft,
): Promise<CraftFact & { version_bumped: boolean; note: string | null }> {
  const response = await fetch(`${API_PROXY_BASE}/seo/facts/${factId}`, {
    body: JSON.stringify(draft),
    headers: buildHeaders(true),
    method: "PATCH",
  });
  return readJson(response, "保存工艺事实失败");
}

export async function approveFact(factId: string): Promise<CraftFact> {
  const response = await fetch(`${API_PROXY_BASE}/seo/facts/${factId}/approve`, {
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "批准失败");
}

export async function retireFact(factId: string): Promise<CraftFact> {
  const response = await fetch(`${API_PROXY_BASE}/seo/facts/${factId}/retire`, {
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "停用失败");
}

export async function factRevisions(
  factId: string,
): Promise<{ revisions: FactRevision[] }> {
  const response = await fetch(
    `${API_PROXY_BASE}/seo/facts/${factId}/revisions`,
    { cache: "no-store", headers: buildHeaders(), method: "GET" },
  );
  return readJson(response, "版本历史加载失败");
}
