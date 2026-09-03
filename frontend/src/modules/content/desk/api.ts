import { contentRequest, SLOW_AI_TIMEOUT_MS } from "../api-base";
import type {
  Article,
  ClusterQuestions,
  Overview,
  PublishState,
  TopicState,
} from "./types";

const BASE = "/content-desk";

export async function fetchQueue(): Promise<Article[]> {
  const data = await contentRequest<{ articles: Article[] }>(
    `${BASE}/articles?queue=review`,
    "待审队列加载失败",
  );
  return data.articles ?? [];
}

export async function fetchArticles(): Promise<Article[]> {
  const data = await contentRequest<{ articles: Article[] }>(
    `${BASE}/articles`,
    "文章列表加载失败",
  );
  return data.articles ?? [];
}

export async function fetchArticle(
  source: string,
  id: string,
): Promise<Article> {
  return contentRequest<Article>(
    `${BASE}/articles/${source}/${id}`,
    "文章加载失败",
  );
}

function post<T>(
  path: string,
  body: unknown,
  label: string,
  timeoutMs?: number,
): Promise<T> {
  return contentRequest<T>(`${BASE}${path}`, label, {
    body,
    method: "POST",
    timeoutMs,
  });
}

export function reviewArticle(
  source: string,
  id: string,
  reviewStatus: "approved" | "rejected" | "pending",
): Promise<Article> {
  return post(
    `/articles/${source}/${id}/review`,
    { review_status: reviewStatus },
    reviewStatus === "approved" ? "批准失败" : "驳回失败",
  );
}

/**
 * 同步：两边都要等 AI 写完（约 30 秒）。
 *
 * 所以必须显式给超时预算 —— 默认 15 秒会在 DeepSeek 还没回来时就把请求掐掉，
 * 而后端那边其实已经在写、写完还会 commit。用户看到「失败」，文章却变了。
 */
export function reviseArticle(source: string, id: string): Promise<Article> {
  return post(
    `/articles/${source}/${id}/revise`,
    {},
    "重写失败",
    SLOW_AI_TIMEOUT_MS,
  );
}

/** 同 revise：同步等 DeepSeek 解读返回。 */
export function analyzeArticle(source: string, id: string): Promise<Article> {
  return post(
    `/articles/${source}/${id}/analyze`,
    {},
    "解读失败",
    SLOW_AI_TIMEOUT_MS,
  );
}

/** 放行/撤销一条审查发现。**指纹由后端算**——前端只传原始字段。 */
export function ignoreFinding(
  source: string,
  id: string,
  payload: Record<string, unknown>,
  ignored: boolean,
): Promise<Article> {
  return post(
    `/articles/${source}/${id}/audit/ignore`,
    { ...payload, ignored },
    ignored ? "放行失败" : "撤销放行失败",
  );
}

export async function fetchOverview(): Promise<Overview> {
  return contentRequest<Overview>(`${BASE}/overview`, "内容台加载失败");
}

export async function fetchPublishState(): Promise<PublishState> {
  const data = await contentRequest<PublishState>(
    `${BASE}/publish-preview`,
    "发布状态加载失败",
  );
  return {
    drafts: data.drafts ?? [],
    in_flight: data.in_flight ?? [],
    live: data.live ?? [],
    units: data.units ?? [],
  };
}

export function publishUnit(
  source: string,
  unitId: string,
): Promise<{ job_id: string; status: string; titles: string[] }> {
  return post(`/publish`, { source, unit_id: unitId }, "发布失败");
}

export async function fetchTopics(): Promise<TopicState> {
  const data = await contentRequest<TopicState>(
    `${BASE}/topics`,
    "选题清单加载失败",
  );
  return {
    awaiting_generation: data.awaiting_generation ?? [],
    clusters: data.clusters ?? [],
    seo_candidates: data.seo_candidates ?? [],
  };
}

export function pickTopic(
  topicId: string,
  status: "picked" | "rejected",
): Promise<{ id: string; status: string }> {
  return post(`/topics/${topicId}/pick`, { status }, "操作失败");
}

export function generateTopics(topicIds: string[]): Promise<{ queued: number }> {
  return post(`/topics/generate`, { topic_ids: topicIds }, "派单失败");
}

export async function fetchClusterQuestions(
  clusterId: string,
): Promise<ClusterQuestions> {
  return contentRequest<ClusterQuestions>(
    `${BASE}/clusters/${clusterId}/questions`,
    "候选问句加载失败",
  );
}

export function saveClusterQuestions(
  clusterId: string,
  questions: { question: string; intent?: string }[],
): Promise<{ picked: number }> {
  return post(`/clusters/${clusterId}/questions`, { questions }, "保存失败");
}

export function generateCluster(clusterId: string): Promise<{ queued: number }> {
  return post(`/clusters/${clusterId}/generate`, {}, "派单失败");
}
