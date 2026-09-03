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

export async function listFacts(): Promise<FactsState> {
  return requestWithLabel(
    "/seo/facts",
    "工艺事实库加载失败",
  );
}

export async function createFact(draft: FactDraft): Promise<CraftFact> {
  return requestWithLabel(
    "/seo/facts",
    "新增工艺事实失败",
    { body: draft, method: "POST" },
  );
}

export async function updateFact(
  factId: string,
  draft: FactDraft,
): Promise<CraftFact & { version_bumped: boolean; note: string | null }> {
  return requestWithLabel(
    `/seo/facts/${factId}`,
    "保存工艺事实失败",
    { body: draft, method: "PATCH" },
  );
}

export async function approveFact(factId: string): Promise<CraftFact> {
  return requestWithLabel(
    `/seo/facts/${factId}/approve`,
    "批准失败",
    { method: "POST" },
  );
}

export async function retireFact(factId: string): Promise<CraftFact> {
  return requestWithLabel(
    `/seo/facts/${factId}/retire`,
    "停用失败",
    { method: "POST" },
  );
}

export async function factRevisions(
  factId: string,
): Promise<{ revisions: FactRevision[] }> {
  return requestWithLabel(
    `/seo/facts/${factId}/revisions`,
    "版本历史加载失败",
  );
}

/* ------------------------------------------------------- 选题 · 关键词雷达 */

export type SeoTopic = {
  id: string;
  keyword: string;
  source: string;
  audience: string;
  destination: string;
  category_path: string | null;
  store_type_key: string | null;
  craft_topic: string | null;
  avg_monthly_searches: number | null;
  attackability: number | null;
  terrain: string | null;
  fact_support: {
    supported?: string[];
    missing?: string[];
    has_support?: boolean;
  };
  score: number;
  status: string;
  geo_reason: string | null;
};

export type RadarRun = {
  status: string;
  seed_count: number;
  planner_calls: number;
  candidate_count: number;
  geo_blocked_count: number;
  notes: { notes?: string[]; geo_blocked?: string };
  finished_at?: string | null;
};

export async function listTopics(): Promise<{
  topics: SeoTopic[];
  last_run: RadarRun | null;
}> {
  return requestWithLabel(
    "/seo/topics",
    "选题队列加载失败",
  );
}

export async function runRadar(extra: string[]): Promise<RadarRun> {
  return requestWithLabel(
    "/seo/topics/radar",
    "雷达跑批失败",
    { body: { extra_keywords: extra }, method: "POST", timeoutMs: SLOW_EXTERNAL_TIMEOUT_MS },
  );
}

export async function probeTerrain(
  topicId: string,
): Promise<{ attackability: number | null; terrain: string | null }> {
  return requestWithLabel(
    `/seo/topics/${topicId}/terrain`,
    "可攻度探测失败",
    { method: "POST", timeoutMs: SLOW_EXTERNAL_TIMEOUT_MS },
  );
}

export async function setTopicStatus(
  topicId: string,
  status: string,
  rejectedReason?: string,
): Promise<{ status: string }> {
  return requestWithLabel(
    `/seo/topics/${topicId}`,
    "更新选题失败",
    { body: { status, rejected_reason: rejectedReason ?? null }, method: "PATCH" },
  );
}

export async function generateArticle(topicId: string): Promise<unknown> {
  return requestWithLabel(
    `/seo/topics/${topicId}/generate`,
    "排队生成失败",
    { method: "POST" },
  );
}

/* ------------------------------------------------------------------ 内容 */

export type SeoSection = { heading?: string; body?: string };

export type SeoItem = {
  id: string;
  topic: string | null;
  item_kind: string;
  destination: string;
  title: string;
  sections: SeoSection[];
  seo: { title?: string; meta_description?: string; url_slug?: string };
  links: {
    intents?: { kind?: string; hint?: string }[];
    missing_facts?: string[];
  };
  brand_audit: {
    clean?: boolean;
    brand_violations?: unknown[];
    cjk_surfaces?: string[];
    ungrounded_numbers?: { surface: string; number: string }[];
  };
  analysis: {
    translation?: string;
    geo_role?: string;
    why_written_this_way?: string;
    strengths?: string[];
    risks?: string[];
  };
  revision: { round?: number; unaddressed?: unknown[] };
  review_status: string;
  wp_post_id: number | null;
  wp_status: string | null;
  published_url: string | null;
};

export type SeoJob = {
  job_id: string;
  topic_id: string;
  job_kind: string;
  status: string;
  error: string | null;
  /** 同一个选题后来跑成功了 —— 这条失败是历史，不该再显示成报错 */
  superseded?: boolean;
  finished_at?: string | null;
};

export async function listItems(): Promise<{
  items: SeoItem[];
  jobs: SeoJob[];
}> {
  return requestWithLabel(
    "/seo/items",
    "内容加载失败",
  );
}

export async function reviewItem(
  itemId: string,
  reviewStatus: string,
): Promise<{ review_status: string }> {
  return requestWithLabel(
    `/seo/items/${itemId}/review`,
    "审核失败",
    { body: { review_status: reviewStatus }, method: "POST" },
  );
}

export async function reviseItem(itemId: string): Promise<unknown> {
  return requestWithLabel(
    `/seo/items/${itemId}/revise`,
    "排队重写失败",
    { method: "POST", timeoutMs: SLOW_EXTERNAL_TIMEOUT_MS },
  );
}

/* ------------------------------------------------------------------ 发布 */

export type PublishJob = {
  job_id: string;
  status: string;
  error: string | null;
  item_ids: string[];
  published_items: { item_id: string; wp_post_id?: number; url?: string }[];
  created_at: string | null;
  finished_at: string | null;
};

export async function listPublishes(): Promise<{ jobs: PublishJob[] }> {
  return requestWithLabel(
    "/seo/publishes",
    "发布记录加载失败",
  );
}

export async function publishItems(
  itemIds: string[],
): Promise<{ job_id: string; status: string }> {
  return requestWithLabel(
    "/seo/publishes",
    "派发布单失败",
    { body: { item_ids: itemIds }, method: "POST" },
  );
}

export async function rebuildFactoryIndex(): Promise<{
  url: string | null;
  excluded_category_ids: string | null;
}> {
  return requestWithLabel(
    "/seo/factory-index",
    "重建 /factory/ 枢纽页失败",
    { method: "POST", timeoutMs: SLOW_EXTERNAL_TIMEOUT_MS },
  );
}

/* ------------------------------------------------------------------ 监测 */

export type MonitorRow = {
  keyword: string;
  attackability: number | null;
  terrain: string | null;
  our_position: number | null;
  checked_at: string | null;
};

export async function getMonitor(): Promise<{
  watched: number;
  rows: MonitorRow[];
}> {
  return requestWithLabel(
    "/seo/monitor",
    "监测面板加载失败",
  );
}

export async function seedMonitor(): Promise<{
  added: number;
  topics_rescored: number;
}> {
  return requestWithLabel(
    "/seo/monitor/seed",
    "灌入监测名单失败",
    { method: "POST", timeoutMs: SLOW_EXTERNAL_TIMEOUT_MS },
  );
}
