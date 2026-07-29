"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

export type GeoCluster = {
  id: string;
  title: string;
  topic: string | null;
  google_category_id: string | null;
  category_path: string | null;
  seed_product_id: string | null;
  status: string;
  picked_questions?: { question: string; intent?: string }[];
  product_ids?: string[];
  pending_product_ids?: string[];
  item_count?: number;
  created_at: string | null;
  updated_at: string | null;
};

export type GeoAnswerBlock = { question?: string; answer?: string };
export type GeoSection = { heading?: string; body?: string };

export type GeoBrandAudit = {
  clean?: boolean;
  brand_violations?: unknown[];
  cjk_surfaces?: string[];
  ungrounded_numbers?: { surface: string; number: string }[];
};

export type GeoAnalysis = {
  translation?: string;
  geo_role?: string;
  why_written_this_way?: string;
  strengths?: string[];
  risks?: string[];
  model?: string;
};

export type GeoItem = {
  id: string;
  cluster_id: string;
  item_type: string;
  title: string;
  body: { sections?: GeoSection[]; answer_blocks?: GeoAnswerBlock[] } | null;
  seo: { title?: string; meta_description?: string; url_slug?: string } | null;
  source_products: string[] | null;
  source_product_labels?: string[];
  analysis?: GeoAnalysis | null;
  revision?: GeoRevision | null;
  published_url?: string | null;
  wp_post_id?: number | null;
  schema_type: string | null;
  brand_audit: GeoBrandAudit | null;
  review_status: string;
  generation_status: string;
  skill_version: string | null;
  provider: string | null;
  created_at: string | null;
};

export type GeoJob = {
  job_id: string;
  cluster_id: string;
  job_type: string;
  status: string;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
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

export async function listClusters(): Promise<{ clusters: GeoCluster[] }> {
  const response = await fetch(`${API_PROXY_BASE}/geo/clusters`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson(response, "话题簇加载失败");
}

export async function createClusterFromProduct(
  productId: string,
): Promise<GeoCluster> {
  const response = await fetch(`${API_PROXY_BASE}/geo/clusters/from-product`, {
    body: JSON.stringify({ product_id: productId }),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "从产品创建话题簇失败");
}

export type GeoClusterProduct = {
  product_id: string;
  sku: string | null;
  name: string | null;
  is_seed: boolean;
  is_pending: boolean;
  differentiated: boolean;
  unique_points: string[];
};

export async function generateProductSpotlight(
  clusterId: string,
  productId: string,
): Promise<GeoItem> {
  const response = await fetch(
    `${API_PROXY_BASE}/geo/clusters/${clusterId}/products/${productId}/spotlight`,
    {
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );
  return readJson(response, "生成专属文章失败");
}

export async function getCluster(
  clusterId: string,
): Promise<{
  cluster: GeoCluster;
  items: GeoItem[];
  products: GeoClusterProduct[];
}> {
  const response = await fetch(`${API_PROXY_BASE}/geo/clusters/${clusterId}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson(response, "话题簇详情加载失败");
}

export async function generateCluster(
  clusterId: string,
): Promise<{ batch_id: string; jobs: { job_id: string; cluster_id: string }[] }> {
  const response = await fetch(
    `${API_PROXY_BASE}/geo/clusters/${clusterId}/generate`,
    {
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );
  return readJson(response, "触发内容生成失败");
}

export async function getClusterJobs(
  clusterId: string,
): Promise<{ jobs: GeoJob[] }> {
  const response = await fetch(
    `${API_PROXY_BASE}/geo/clusters/${clusterId}/jobs`,
    {
      cache: "no-store",
      headers: buildHeaders(),
      method: "GET",
    },
  );
  return readJson(response, "任务状态加载失败");
}

export type GeoTopicCandidate = {
  question: string;
  source: string; // k_faq | f_keyword
  source_type: string;
  intent: string;
  rank: number | null;
  snippet: string | null;
  score: number;
};

export type GeoPickedQuestion = { question: string; intent?: string };

export async function getTopicCandidates(
  clusterId: string,
): Promise<{ candidates: GeoTopicCandidate[]; picked: GeoPickedQuestion[] }> {
  const response = await fetch(
    `${API_PROXY_BASE}/geo/clusters/${clusterId}/topic-candidates`,
    {
      cache: "no-store",
      headers: buildHeaders(),
      method: "GET",
    },
  );
  return readJson(response, "话题候选加载失败");
}

export async function savePickedQuestions(
  clusterId: string,
  questions: GeoPickedQuestion[],
): Promise<GeoCluster> {
  const response = await fetch(
    `${API_PROXY_BASE}/geo/clusters/${clusterId}/picked-questions`,
    {
      body: JSON.stringify({ questions }),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );
  return readJson(response, "保存选题失败");
}

export type GeoUnaddressed = {
  critique: string;
  reason: string;
  needs_data: boolean;
  missing_fact: string;
};

export type GeoRevision = {
  round?: number;
  addressed?: string[];
  unaddressed?: GeoUnaddressed[];
};

export type GeoCritiquePattern = {
  pattern: string;
  affected_count: number;
  suggested_fix: string;
};

export type GeoDataGap = {
  missing_fact: string;
  reason: string;
  items: { item_id: string; title: string }[];
  critiques: string[];
};

export type GeoCritiqueSummary = {
  critique_count: number;
  patterns: GeoCritiquePattern[];
  data_gaps: GeoDataGap[];
  critiques: { item_id: string; item_type: string; title: string; critique: string }[];
};

export async function getCritiqueSummary(
  clusterId: string,
): Promise<GeoCritiqueSummary> {
  const response = await fetch(
    `${API_PROXY_BASE}/geo/clusters/${clusterId}/critique-summary`,
    {
      cache: "no-store",
      headers: buildHeaders(),
      method: "GET",
    },
  );
  return readJson(response, "批评汇总加载失败");
}

export type GeoPublishJobRow = {
  job_id: string;
  status: string;
  error: string | null;
  published_items: { item_id: string; wp_post_id?: number; url?: string }[];
  created_at: string | null;
  finished_at: string | null;
};

export type GeoPublishState = {
  jobs: GeoPublishJobRow[];
  publishable_count: number;
  total_count: number;
  ready: boolean;
  blockers: string[];
};

export async function getPublishState(
  clusterId: string,
): Promise<GeoPublishState> {
  const response = await fetch(
    `${API_PROXY_BASE}/geo/clusters/${clusterId}/publishes`,
    { cache: "no-store", headers: buildHeaders(), method: "GET" },
  );
  return readJson(response, "发布台账加载失败");
}

export async function publishCluster(
  clusterId: string,
): Promise<{ job_id: string; status: string; article_count: number }> {
  const response = await fetch(
    `${API_PROXY_BASE}/geo/clusters/${clusterId}/publish`,
    { cache: "no-store", headers: buildHeaders(true), method: "POST" },
  );
  return readJson(response, "发布失败");
}

export async function reviseItem(itemId: string): Promise<GeoItem> {
  const response = await fetch(`${API_PROXY_BASE}/geo/items/${itemId}/revise`, {
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "按批评重写失败");
}

export async function analyzeItem(itemId: string): Promise<GeoItem> {
  const response = await fetch(`${API_PROXY_BASE}/geo/items/${itemId}/analyze`, {
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "内容解读失败");
}

export async function reviewItem(
  itemId: string,
  reviewStatus: "pending" | "approved" | "rejected",
): Promise<GeoItem> {
  const response = await fetch(`${API_PROXY_BASE}/geo/items/${itemId}/review`, {
    body: JSON.stringify({ review_status: reviewStatus }),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "审阅更新失败");
}

export type GeoBacklinkState = {
  ready: boolean;
  target_count: number;
  targets: { sku: string | null; woo_product_id: number; guide_count: number }[];
  skipped: string[];
  jobs: {
    job_id: string;
    status: string;
    error: string | null;
    updated_count: number;
    created_at: string | null;
    finished_at: string | null;
  }[];
};

export async function getBacklinkState(): Promise<GeoBacklinkState> {
  const response = await fetch(`${API_PROXY_BASE}/geo/backlinks`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson(response, "产品页反链状态加载失败");
}

export async function dispatchBacklinks(): Promise<{
  job_id: string;
  status: string;
  target_count: number;
}> {
  const response = await fetch(`${API_PROXY_BASE}/geo/backlinks`, {
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "同步产品页反链失败");
}

export type GeoMonitorQuestion = {
  id: string;
  question: string;
  intent: string | null;
  cluster_title: string | null;
  our_position: number | null;
  previous_position: number | null;
  attackability: number | null;
  terrain: string | null;
  holder_counts: Record<string, number>;
  top_results: { position: number; url: string; title: string; domain: string; holder: string }[];
  last_checked_at: string | null;
};

export type GeoMonitorState = {
  questions: GeoMonitorQuestion[];
  summary: {
    watched: number;
    checked: number;
    ranked: number;
    soft_unclaimed: number;
    best_position: number | null;
  };
  budget: { provider?: string; daily_budget?: number };
  runs: {
    id: string;
    status: string;
    question_count: number;
    checked_count: number;
    error: string | null;
    created_at: string | null;
  }[];
};

export async function getMonitorState(): Promise<GeoMonitorState> {
  const response = await fetch(`${API_PROXY_BASE}/geo/monitor`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson(response, "阵地监测加载失败");
}

export async function seedMonitorFromCluster(
  clusterId: string,
): Promise<{ added: number; skipped: number }> {
  const response = await fetch(
    `${API_PROXY_BASE}/geo/monitor/seed-from-cluster/${clusterId}`,
    { cache: "no-store", headers: buildHeaders(true), method: "POST" },
  );
  return readJson(response, "导入监测问句失败");
}

export async function runMonitorSweep(): Promise<{
  run_id: string;
  status: string;
  checked_count: number;
  question_count: number;
}> {
  const response = await fetch(`${API_PROXY_BASE}/geo/monitor/run`, {
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "监测执行失败");
}
