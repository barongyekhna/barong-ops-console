"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

export type UploadJob = {
  job_id: string;
  product_id: string;
  product_name: string | null;
  sku: string | null;
  channel: string;
  status: string;
  external_product_id: string | null;
  external_url: string | null;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
};

export type UploadJobsSummary = {
  total: number;
  success: number;
  failed: number;
  in_flight: number;
};

export type UploadJobsResult = {
  jobs: UploadJob[];
  summary: UploadJobsSummary;
};

function buildHeaders() {
  const headers = new Headers({ Accept: "application/json" });
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
    throw new Error(`${label}（${response.status}）`);
  }
  return (await response.json()) as T;
}

export async function getUploadJobs(limit = 50): Promise<UploadJobsResult> {
  const response = await fetch(`${API_PROXY_BASE}/p/uploads?limit=${limit}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<UploadJobsResult>(response, "上架台账加载失败");
}

export type BoardProduct = {
  product_id: string;
  product_name: string | null;
  sku: string | null;
  price: string | null;
  gate_ready: boolean;
  blockers: string[];
  exported: boolean;
  last_job_status: string | null;
  last_external_url: string | null;
};

export type BoardResult = {
  pending: BoardProduct[];
  uploaded: BoardProduct[];
};

export async function getBoard(): Promise<BoardResult> {
  const response = await fetch(`${API_PROXY_BASE}/p/products/board`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<BoardResult>(response, "产品分组加载失败");
}

export async function dispatchProducts(
  productIds: string[],
): Promise<{ queued: string[]; blocked: { product_id: string; blockers: string[] }[] }> {
  const headers = buildHeaders();
  headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_PROXY_BASE}/p/dispatch/batch`, {
    body: JSON.stringify({ product_ids: productIds }),
    cache: "no-store",
    headers,
    method: "POST",
  });
  return readJson(response, "上传派单失败");
}
