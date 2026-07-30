"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";
const LABEL = "B2B 产品页小窗";

export type WidgetJob = {
  job_id: string;
  status: "queued" | "dispatched" | "success" | "failed";
  targets: number;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
};

export type WidgetPushResult = {
  job_id: string;
  status: string;
  targets: number;
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

export async function getWidgetJobs(): Promise<WidgetJob[]> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/widget-jobs`, {
    cache: "no-store",
    headers: buildHeaders(),
  });
  return readJson<WidgetJob[]>(response);
}

/** 全量重推。政策文案改了之后用这个——每产品的数据平时保存即自动推。 */
export async function pushWidgets(): Promise<WidgetPushResult> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/widget-push`, {
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<WidgetPushResult>(response);
}

export type WholesaleSiteStatus = {
  main_page_id: string | null;
  last_published_at: string | null;
  store_types: {
    key: string;
    label: string;
    count: number;
    url: string;
    page_id: string | null;
    /** 上次生成时真的挂上去的指南篇数（已向 WP 核过是不是已发布）。 */
    guides: number;
  }[];
  /** 反向回链覆盖了几个 WP 类目。 */
  guide_categories_mapped: number;
};

export type WholesalePublishResult = {
  main_page_id: number;
  main_link: string | null;
  groups: number;
  store_type_pages: { label: string; count: number; link: string | null }[];
};

export async function getWholesaleSiteStatus(): Promise<WholesaleSiteStatus> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/website/status`, {
    cache: "no-store",
    headers: buildHeaders(),
  });
  return readJson<WholesaleSiteStatus>(response);
}

/** 重新生成 /wholesale/ 主页和全部店型子页。幂等。 */
export async function publishWholesaleSite(): Promise<WholesalePublishResult> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/website/publish`, {
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<WholesalePublishResult>(response);
}
