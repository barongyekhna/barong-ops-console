"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

export type TreeNode = {
  id: string;
  name: string;
  name_zh: string | null;
  full_path: string;
  level: number;
  is_leaf: boolean;
  children_count: number;
  keywords_count: number;
  candidates_count: number;
};

export type ProfileProduct = {
  en: string;
  zh: string;
  note_zh: string;
};

export type ProfileResponse = {
  category_id: string;
  exists: boolean;
  products: ProfileProduct[];
};

export type TreeResponse = {
  parent_id: string | null;
  items: TreeNode[];
};

export type RunMode = "full" | "keywords_only" | "sourcing_only";

export type RunItem = {
  run_id: string;
  status: string;
  mode: RunMode;
  categories_total: number;
  categories_done: number;
  keywords_found: number;
  serper_calls: number;
  candidates_found: number;
  alibaba_calls: number;
  selection: { id: string; name: string; full_path: string }[];
  error: string | null;
  requested_by: string | null;
  created_at: string | null;
  finished_at: string | null;
};

export type KeywordItem = {
  id: string;
  category_id: string;
  category_path: string;
  keyword_text: string;
  keyword_type: string;
  rank: number | null;
  status: string;
};

export type CandidateItem = {
  id: string;
  category_id: string;
  category_path: string;
  title: string;
  source: string;
  source_url: string | null;
  image_url: string | null;
  price_cny: string | null;
  moq: number | null;
  supplier_name: string | null;
  weight_note: string | null;
  red_flags: { type: string; reason: string }[];
  automation_blocked: boolean;
  status: string;
  notes: string | null;
  k_product_id: string | null;
  created_at: string | null;
};

export type QuotaEntry = {
  label: string;
  used: number;
  budget: number;
  remaining: number | null;
  unlimited: boolean;
} | null;

export type QuotaResponse = {
  serper: QuotaEntry;
  alibaba1688_app_calls: QuotaEntry;
};

export type CandidateCreatePayload = {
  category_id: string;
  title: string;
  source_url?: string;
  image_url?: string;
  price_cny?: string;
  moq?: number;
  supplier_name?: string;
  weight_note?: string;
  notes?: string;
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
      detail = body?.detail ? `：${body.detail}` : "";
    } catch {
      // 忽略非 JSON 错误体
    }
    throw new Error(`${label}（${response.status}）${detail}`);
  }
  return (await response.json()) as T;
}

export async function getTree(parentId?: string): Promise<TreeResponse> {
  const query = parentId ? `?parent_id=${encodeURIComponent(parentId)}` : "";
  const response = await fetch(`${API_PROXY_BASE}/f/categories/tree${query}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<TreeResponse>(response, "类目树加载失败");
}

export async function searchTree(q: string): Promise<TreeResponse> {
  const response = await fetch(
    `${API_PROXY_BASE}/f/categories/search?q=${encodeURIComponent(q)}`,
    { cache: "no-store", headers: buildHeaders(), method: "GET" },
  );
  return readJson<TreeResponse>(response, "类目搜索失败");
}

export async function getProfile(categoryId: string): Promise<ProfileResponse> {
  const response = await fetch(
    `${API_PROXY_BASE}/f/categories/${encodeURIComponent(categoryId)}/profile`,
    { cache: "no-store", headers: buildHeaders(), method: "GET" },
  );
  return readJson<ProfileResponse>(response, "类目画像加载失败");
}

export async function generateProfile(
  categoryId: string,
): Promise<ProfileResponse> {
  const response = await fetch(
    `${API_PROXY_BASE}/f/categories/${encodeURIComponent(categoryId)}/profile`,
    { cache: "no-store", headers: buildHeaders(true), method: "POST" },
  );
  return readJson<ProfileResponse>(response, "类目画像生成失败");
}

export async function createRun(
  categoryIds: string[],
  mode: RunMode = "full",
): Promise<RunItem> {
  const response = await fetch(`${API_PROXY_BASE}/f/runs`, {
    body: JSON.stringify({ category_ids: categoryIds, mode }),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<RunItem>(response, "富化运行发起失败");
}

export async function getRuns(limit = 20): Promise<{ runs: RunItem[] }> {
  const response = await fetch(`${API_PROXY_BASE}/f/runs?limit=${limit}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<{ runs: RunItem[] }>(response, "运行台账加载失败");
}

export async function getKeywords(params: {
  categoryId?: string;
  status?: string;
  limit?: number;
}): Promise<{ items: KeywordItem[]; total: number }> {
  const query = new URLSearchParams();
  if (params.categoryId) query.set("category_id", params.categoryId);
  if (params.status) query.set("status", params.status);
  query.set("limit", String(params.limit ?? 200));
  const response = await fetch(
    `${API_PROXY_BASE}/f/keywords?${query.toString()}`,
    { cache: "no-store", headers: buildHeaders(), method: "GET" },
  );
  return readJson(response, "关键词加载失败");
}

export async function reviewKeyword(
  keywordId: string,
  status: "candidate" | "approved" | "rejected",
): Promise<KeywordItem> {
  const response = await fetch(`${API_PROXY_BASE}/f/keywords/${keywordId}`, {
    body: JSON.stringify({ status }),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "PATCH",
  });
  return readJson<KeywordItem>(response, "关键词审核失败");
}

export async function getCandidates(params: {
  categoryId?: string;
  status?: string;
  limit?: number;
}): Promise<{ items: CandidateItem[]; total: number }> {
  const query = new URLSearchParams();
  if (params.categoryId) query.set("category_id", params.categoryId);
  if (params.status) query.set("status", params.status);
  query.set("limit", String(params.limit ?? 100));
  const response = await fetch(
    `${API_PROXY_BASE}/f/candidates?${query.toString()}`,
    { cache: "no-store", headers: buildHeaders(), method: "GET" },
  );
  return readJson(response, "候选池加载失败");
}

export async function createCandidate(
  payload: CandidateCreatePayload,
): Promise<CandidateItem> {
  const response = await fetch(`${API_PROXY_BASE}/f/candidates`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<CandidateItem>(response, "候选创建失败");
}

export async function reviewCandidate(
  candidateId: string,
  action: "approve" | "reject" | "reopen",
  notes?: string,
): Promise<CandidateItem> {
  const response = await fetch(`${API_PROXY_BASE}/f/candidates/${candidateId}`, {
    body: JSON.stringify({ action, notes }),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "PATCH",
  });
  return readJson<CandidateItem>(response, "候选审核失败");
}

export async function importCandidateToK(
  candidateId: string,
): Promise<{ product_id: string; deduped: boolean }> {
  const response = await fetch(
    `${API_PROXY_BASE}/f/candidates/${candidateId}/import-to-k`,
    { cache: "no-store", headers: buildHeaders(), method: "POST" },
  );
  return readJson(response, "搬进 K 失败");
}

export async function getQuota(): Promise<QuotaResponse> {
  const response = await fetch(`${API_PROXY_BASE}/f/quota`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<QuotaResponse>(response, "额度加载失败");
}
