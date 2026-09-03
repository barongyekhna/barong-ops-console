"use client";

import { requestWithLabel } from "@/lib/labelled-api";

/**
 * 当场打外部服务的接口的超时预算。
 *
 * `lib/api.ts` 给非 GET 的默认值是 15 秒。这个模块里有几条**不是派单、
 * 是同步等结果**（后端 docstring 里写着的）：选题雷达和可攻度打 Serper，
 * 重写/解读同步等 AI 返回（SEO 那条注释直说「**同步**——排队那条路是坏的」），
 * 枢纽页重建和簇发布连着打 WP.com，阵地巡检逐条问句打 Serper。
 * 收口前它们一个超时都没有；照默认值收口这些按钮会集体失效。
 *
 * 派单类（返回 job_id 就走）保持默认：`/topics/{id}/generate`、`/publishes`、
 * `/clusters/{id}/generate`、`/backlinks`。
 */
const SLOW_EXTERNAL_TIMEOUT_MS = 300_000;


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

export async function listClusters(): Promise<{ clusters: GeoCluster[] }> {
  return requestWithLabel(
    "/geo/clusters",
    "话题簇加载失败",
  );
}

export async function createClusterFromProduct(
  productId: string,
): Promise<GeoCluster> {
  return requestWithLabel(
    "/geo/clusters/from-product",
    "从产品创建话题簇失败",
    { body: { product_id: productId }, method: "POST" },
  );
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
  return requestWithLabel(
    `/geo/clusters/${clusterId}/products/${productId}/spotlight`,
    "生成专属文章失败",
    { method: "POST" },
  );
}

export async function getCluster(
  clusterId: string,
): Promise<{
  cluster: GeoCluster;
  items: GeoItem[];
  products: GeoClusterProduct[];
}> {
  return requestWithLabel(
    `/geo/clusters/${clusterId}`,
    "话题簇详情加载失败",
  );
}

export async function generateCluster(
  clusterId: string,
): Promise<{ batch_id: string; jobs: { job_id: string; cluster_id: string }[] }> {
  return requestWithLabel(
    `/geo/clusters/${clusterId}/generate`,
    "触发内容生成失败",
    { method: "POST" },
  );
}

export async function getClusterJobs(
  clusterId: string,
): Promise<{ jobs: GeoJob[] }> {
  return requestWithLabel(
    `/geo/clusters/${clusterId}/jobs`,
    "任务状态加载失败",
  );
}

export type GeoTerrainReading = {
  attackability: number;
  terrain: string;
  our_position: number | null;
  top_domains: string[];
  checked_at: string | null;
};

export type GeoTopicCandidate = {
  question: string;
  terrain?: GeoTerrainReading | null;
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
  return requestWithLabel(
    `/geo/clusters/${clusterId}/topic-candidates`,
    "话题候选加载失败",
  );
}

export type MiningReport = {
  seeds: string[];
  queries_spent: number;
  new_questions: number;
  expanded: number;
  notes: string[];
};

export async function mineClusterQuestions(
  clusterId: string,
): Promise<MiningReport> {
  return requestWithLabel(
    `/geo/clusters/${clusterId}/mine-questions`,
    "选题深挖失败",
    { method: "POST", timeoutMs: SLOW_EXTERNAL_TIMEOUT_MS },
  );
}

export async function savePickedQuestions(
  clusterId: string,
  questions: GeoPickedQuestion[],
): Promise<GeoCluster> {
  return requestWithLabel(
    `/geo/clusters/${clusterId}/picked-questions`,
    "保存选题失败",
    { body: { questions }, method: "POST" },
  );
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
  return requestWithLabel(
    `/geo/clusters/${clusterId}/critique-summary`,
    "批评汇总加载失败",
  );
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
  return requestWithLabel(
    `/geo/clusters/${clusterId}/publishes`,
    "发布台账加载失败",
  );
}

export async function publishCluster(
  clusterId: string,
): Promise<{ job_id: string; status: string; article_count: number }> {
  return requestWithLabel(
    `/geo/clusters/${clusterId}/publish`,
    "发布失败",
    { method: "POST", timeoutMs: SLOW_EXTERNAL_TIMEOUT_MS },
  );
}

export async function reviseItem(itemId: string): Promise<GeoItem> {
  return requestWithLabel(
    `/geo/items/${itemId}/revise`,
    "按批评重写失败",
    { method: "POST", timeoutMs: SLOW_EXTERNAL_TIMEOUT_MS },
  );
}

export async function analyzeItem(itemId: string): Promise<GeoItem> {
  return requestWithLabel(
    `/geo/items/${itemId}/analyze`,
    "内容解读失败",
    { method: "POST", timeoutMs: SLOW_EXTERNAL_TIMEOUT_MS },
  );
}

export async function reviewItem(
  itemId: string,
  reviewStatus: "pending" | "approved" | "rejected",
): Promise<GeoItem> {
  return requestWithLabel(
    `/geo/items/${itemId}/review`,
    "审阅更新失败",
    { body: { review_status: reviewStatus }, method: "POST" },
  );
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
  return requestWithLabel(
    "/geo/backlinks",
    "产品页反链状态加载失败",
  );
}

export async function dispatchBacklinks(): Promise<{
  job_id: string;
  status: string;
  target_count: number;
}> {
  return requestWithLabel(
    "/geo/backlinks",
    "同步产品页反链失败",
    { method: "POST" },
  );
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
  return requestWithLabel(
    "/geo/monitor",
    "阵地监测加载失败",
  );
}

export async function seedMonitorFromCluster(
  clusterId: string,
): Promise<{ added: number; skipped: number }> {
  return requestWithLabel(
    `/geo/monitor/seed-from-cluster/${clusterId}`,
    "导入监测问句失败",
    { method: "POST" },
  );
}

export async function runMonitorSweep(): Promise<{
  run_id: string;
  status: string;
  checked_count: number;
  question_count: number;
}> {
  return requestWithLabel(
    "/geo/monitor/run",
    "监测执行失败",
    { method: "POST", timeoutMs: SLOW_EXTERNAL_TIMEOUT_MS },
  );
}

export async function probeTopicTerrain(clusterId: string): Promise<{
  checked: number;
  cached: number;
  created: number;
  skipped_over_cap: number;
}> {
  return requestWithLabel(
    `/geo/clusters/${clusterId}/topic-terrain`,
    "探测选题阵地失败",
    { method: "POST", timeoutMs: SLOW_EXTERNAL_TIMEOUT_MS },
  );
}
