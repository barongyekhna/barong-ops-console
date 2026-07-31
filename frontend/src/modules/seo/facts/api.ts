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
  const response = await fetch(`${API_PROXY_BASE}/seo/topics`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson(response, "选题队列加载失败");
}

export async function runRadar(extra: string[]): Promise<RadarRun> {
  const response = await fetch(`${API_PROXY_BASE}/seo/topics/radar`, {
    body: JSON.stringify({ extra_keywords: extra }),
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "雷达跑批失败");
}

export async function probeTerrain(
  topicId: string,
): Promise<{ attackability: number | null; terrain: string | null }> {
  const response = await fetch(
    `${API_PROXY_BASE}/seo/topics/${topicId}/terrain`,
    { headers: buildHeaders(true), method: "POST" },
  );
  return readJson(response, "可攻度探测失败");
}

export async function setTopicStatus(
  topicId: string,
  status: string,
  rejectedReason?: string,
): Promise<{ status: string }> {
  const response = await fetch(`${API_PROXY_BASE}/seo/topics/${topicId}`, {
    body: JSON.stringify({ status, rejected_reason: rejectedReason ?? null }),
    headers: buildHeaders(true),
    method: "PATCH",
  });
  return readJson(response, "更新选题失败");
}

export async function generateArticle(topicId: string): Promise<unknown> {
  const response = await fetch(
    `${API_PROXY_BASE}/seo/topics/${topicId}/generate`,
    { headers: buildHeaders(true), method: "POST" },
  );
  return readJson(response, "排队生成失败");
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
  const response = await fetch(`${API_PROXY_BASE}/seo/items`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson(response, "内容加载失败");
}

export async function reviewItem(
  itemId: string,
  reviewStatus: string,
): Promise<{ review_status: string }> {
  const response = await fetch(`${API_PROXY_BASE}/seo/items/${itemId}/review`, {
    body: JSON.stringify({ review_status: reviewStatus }),
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "审核失败");
}

export async function reviseItem(itemId: string): Promise<unknown> {
  const response = await fetch(`${API_PROXY_BASE}/seo/items/${itemId}/revise`, {
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "排队重写失败");
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
  const response = await fetch(`${API_PROXY_BASE}/seo/publishes`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson(response, "发布记录加载失败");
}

export async function publishItems(
  itemIds: string[],
): Promise<{ job_id: string; status: string }> {
  const response = await fetch(`${API_PROXY_BASE}/seo/publishes`, {
    body: JSON.stringify({ item_ids: itemIds }),
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "派发布单失败");
}

export async function rebuildFactoryIndex(): Promise<{
  url: string | null;
  excluded_category_ids: string | null;
}> {
  const response = await fetch(`${API_PROXY_BASE}/seo/factory-index`, {
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "重建 /factory/ 枢纽页失败");
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
  const response = await fetch(`${API_PROXY_BASE}/seo/monitor`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson(response, "监测面板加载失败");
}

export async function seedMonitor(): Promise<{
  added: number;
  topics_rescored: number;
}> {
  const response = await fetch(`${API_PROXY_BASE}/seo/monitor/seed`, {
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson(response, "灌入监测名单失败");
}
