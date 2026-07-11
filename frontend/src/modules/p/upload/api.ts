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

export async function getUploadJobs(limit = 50): Promise<UploadJobsResult> {
  const response = await fetch(`${API_PROXY_BASE}/p/uploads?limit=${limit}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    throw new Error(`上架台账加载失败（${response.status}）`);
  }
  return (await response.json()) as UploadJobsResult;
}
