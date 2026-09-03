"use client";

import { requestWithLabel } from "@/lib/labelled-api";

/**
 * 同步跑外部服务的接口的超时预算。
 * `POST /f/runs` 后端注释写着「展开子树 → 逐类目 Serper 收割 (+1688 找货)」，
 * 画像生成同理 —— 都是当场等结果，不是派单。默认 15 秒必然不够。
 */
const SLOW_HARVEST_TIMEOUT_MS = 300_000;

// 下面这两个只剩候选图片代理在用 —— 那处**保留裸 fetch**：它要的是 blob，
// 而 apiRequest 的契约是「返回解析后的 JSON」。
const API_PROXY_BASE = "/api/backend";

function buildHeaders() {
  return new Headers({ Accept: "application/json" });
}


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
  profile_product_zh: string | null;
  profile_product_en: string | null;
  score: number | null;
  score_json: Record<string, number | null> | null;
  recommended_rank: number | null;
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
  cps_image_search: QuotaEntry;
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

export async function getTree(parentId?: string): Promise<TreeResponse> {
  const query = parentId ? `?parent_id=${encodeURIComponent(parentId)}` : "";
  return requestWithLabel<TreeResponse>(
    `/f/categories/tree${query}`,
    "类目树加载失败",
  );
}

export async function searchTree(q: string): Promise<TreeResponse> {
  return requestWithLabel<TreeResponse>(
    `/f/categories/search?q=${encodeURIComponent(q)}`,
    "类目搜索失败",
  );
}

export async function getProfile(categoryId: string): Promise<ProfileResponse> {
  return requestWithLabel<ProfileResponse>(
    `/f/categories/${encodeURIComponent(categoryId)}/profile`,
    "类目画像加载失败",
  );
}

export async function generateProfile(
  categoryId: string,
): Promise<ProfileResponse> {
  return requestWithLabel<ProfileResponse>(
    `/f/categories/${encodeURIComponent(categoryId)}/profile`,
    "类目画像生成失败",
    { method: "POST", timeoutMs: SLOW_HARVEST_TIMEOUT_MS },
  );
}

export async function createRun(
  categoryIds: string[],
  mode: RunMode = "full",
): Promise<RunItem> {
  return requestWithLabel<RunItem>(
    "/f/runs",
    "富化运行发起失败",
    {
      body: { category_ids: categoryIds, mode },
      method: "POST",
      timeoutMs: SLOW_HARVEST_TIMEOUT_MS,
    },
  );
}

export async function getRuns(limit = 20): Promise<{ runs: RunItem[] }> {
  return requestWithLabel<{ runs: RunItem[] }>(
    `/f/runs?limit=${limit}`,
    "运行台账加载失败",
  );
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
  return requestWithLabel(
    `/f/keywords?${query.toString()}`,
    "关键词加载失败",
  );
}

export async function reviewKeyword(
  keywordId: string,
  status: "candidate" | "approved" | "rejected",
): Promise<KeywordItem> {
  return requestWithLabel<KeywordItem>(
    `/f/keywords/${keywordId}`,
    "关键词审核失败",
    { body: { status }, method: "PATCH" },
  );
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
  return requestWithLabel(
    `/f/candidates?${query.toString()}`,
    "候选池加载失败",
  );
}

export async function createCandidate(
  payload: CandidateCreatePayload,
): Promise<CandidateItem> {
  return requestWithLabel<CandidateItem>(
    "/f/candidates",
    "候选创建失败",
    { body: payload, method: "POST" },
  );
}

export async function reviewCandidate(
  candidateId: string,
  action: "approve" | "reject" | "reopen",
  notes?: string,
): Promise<CandidateItem> {
  return requestWithLabel<CandidateItem>(
    `/f/candidates/${candidateId}`,
    "候选审核失败",
    { body: { action, notes }, method: "PATCH" },
  );
}

export async function importCandidateToK(
  candidateId: string,
): Promise<{ product_id: string; deduped: boolean }> {
  return requestWithLabel(
    `/f/candidates/${candidateId}/import-to-k`,
    "搬进 K 失败",
    { method: "POST" },
  );
}

// 候选图片走后端代理（服务端回源 alicdn + 磁盘缓存，绕防盗链并提速）。
// objectURL 模块级缓存：列表刷新/分组开合不重复拉图。
const imageUrlCache = new Map<string, string>();
const imageInflight = new Map<string, Promise<string | null>>();

export function fetchCandidateImage(
  candidateId: string,
  variant: "thumb" | "full",
): Promise<string | null> {
  const cacheKey = `${candidateId}:${variant}`;
  const cached = imageUrlCache.get(cacheKey);
  if (cached) return Promise.resolve(cached);
  const inflight = imageInflight.get(cacheKey);
  if (inflight) return inflight;
  const promise = fetch(
    `${API_PROXY_BASE}/f/candidates/${candidateId}/image?variant=${variant}`,
    { headers: buildHeaders(), method: "GET" },
  )
    .then(async (response) => {
      if (!response.ok) return null;
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      imageUrlCache.set(cacheKey, url);
      return url;
    })
    .catch(() => null)
    .finally(() => {
      imageInflight.delete(cacheKey);
    });
  imageInflight.set(cacheKey, promise);
  return promise;
}

export type MarketRef = {
  title: string | null;
  page_url: string;
  source_domain: string | null;
  site_type: "independent" | "platform" | "content" | null;
};

export async function getMarketRefs(
  categoryId: string,
): Promise<{ category_id: string; groups: Record<string, MarketRef[]> }> {
  return requestWithLabel(
    `/f/categories/${encodeURIComponent(categoryId)}/market-refs`,
    "市场参考加载失败",
  );
}

export async function getQuota(): Promise<QuotaResponse> {
  return requestWithLabel<QuotaResponse>(
    "/f/quota",
    "额度加载失败",
  );
}
