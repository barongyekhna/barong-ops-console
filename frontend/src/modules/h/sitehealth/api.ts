"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

export type HealthRunTrigger = "scheduled" | "manual";
export type HealthRunStatus = "running" | "completed" | "failed";
export type HealthFindingType =
  | "broken_link"
  | "slow_page"
  | "sitemap_error"
  | "homepage_error";
export type HealthFindingStatus = "open" | "acknowledged" | "resolved";
export type HealthFindingAction = "acknowledge" | "resolve" | "reopen";

export type HealthRun = {
  id: string;
  trigger: HealthRunTrigger;
  status: HealthRunStatus;
  started_at: string | null;
  finished_at: string | null;
  urls_total: number;
  urls_ok: number;
  urls_broken: number;
  urls_slow: number;
  avg_response_ms: number | null;
  p95_response_ms: number | null;
  sitemap_ok: boolean;
  homepage_ok: boolean;
  summary_json: Record<string, unknown> | null;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type HealthFinding = {
  id: string;
  run_id: string;
  finding_type: HealthFindingType;
  url: string;
  status_code: number | null;
  response_ms: number | null;
  detail: string | null;
  status: HealthFindingStatus;
  created_at: string | null;
  updated_at: string | null;
};

export type HealthRunDetail = HealthRun & {
  findings: HealthFinding[];
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
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail || `${label}（${response.status}）`);
  }
  return (await response.json()) as T;
}

export async function getHealthRuns(
  limit = 30,
): Promise<{ runs: HealthRun[] }> {
  const response = await fetch(`${API_PROXY_BASE}/h/runs?limit=${limit}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<{ runs: HealthRun[] }>(response, "H 站点健康");
}

export async function getHealthRun(runId: string): Promise<HealthRunDetail> {
  const response = await fetch(
    `${API_PROXY_BASE}/h/runs/${encodeURIComponent(runId)}`,
    {
      cache: "no-store",
      headers: buildHeaders(),
      method: "GET",
    },
  );
  return readJson<HealthRunDetail>(response, "H 站点健康");
}

export async function triggerHealthRun(): Promise<HealthRun> {
  const response = await fetch(`${API_PROXY_BASE}/h/runs/trigger`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "POST",
  });
  return readJson<HealthRun>(response, "H 站点健康");
}

export async function getHealthFindings(params: {
  status: HealthFindingStatus;
  findingType?: HealthFindingType;
  limit?: number;
}): Promise<{ items: HealthFinding[]; total: number }> {
  const query = new URLSearchParams({
    limit: String(params.limit ?? 100),
    status: params.status,
  });
  if (params.findingType) {
    query.set("finding_type", params.findingType);
  }
  const response = await fetch(
    `${API_PROXY_BASE}/h/findings?${query.toString()}`,
    {
      cache: "no-store",
      headers: buildHeaders(),
      method: "GET",
    },
  );
  return readJson<{ items: HealthFinding[]; total: number }>(
    response,
    "H 站点健康",
  );
}

export async function updateHealthFinding(
  findingId: string,
  action: HealthFindingAction,
): Promise<HealthFinding> {
  const response = await fetch(
    `${API_PROXY_BASE}/h/findings/${encodeURIComponent(findingId)}`,
    {
      body: JSON.stringify({ action }),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "PATCH",
    },
  );
  return readJson<HealthFinding>(response, "H 站点健康");
}
