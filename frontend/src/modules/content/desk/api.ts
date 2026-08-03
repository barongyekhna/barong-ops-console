import { API_PROXY_BASE, buildHeaders, readJson } from "../api-base";
import type {
  Article,
  ClusterQuestions,
  Overview,
  PublishState,
  TopicState,
} from "./types";

const BASE = `${API_PROXY_BASE}/content-desk`;

export async function fetchQueue(): Promise<Article[]> {
  const response = await fetch(`${BASE}/articles?queue=review`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  const data = await readJson<{ articles: Article[] }>(response, "待审队列加载失败");
  return data.articles ?? [];
}

export async function fetchArticles(): Promise<Article[]> {
  const response = await fetch(`${BASE}/articles`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  const data = await readJson<{ articles: Article[] }>(response, "文章列表加载失败");
  return data.articles ?? [];
}

export async function fetchArticle(
  source: string,
  id: string,
): Promise<Article> {
  const response = await fetch(`${BASE}/articles/${source}/${id}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<Article>(response, "文章加载失败");
}

async function post<T>(path: string, body: unknown, label: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    body: body === undefined ? undefined : JSON.stringify(body),
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<T>(response, label);
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

/** 同步：两边都要等 AI 写完（约 30 秒）。 */
export function reviseArticle(source: string, id: string): Promise<Article> {
  return post(`/articles/${source}/${id}/revise`, {}, "重写失败");
}

export function analyzeArticle(source: string, id: string): Promise<Article> {
  return post(`/articles/${source}/${id}/analyze`, {}, "解读失败");
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
  const response = await fetch(`${BASE}/overview`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<Overview>(response, "内容台加载失败");
}

export async function fetchPublishState(): Promise<PublishState> {
  const response = await fetch(`${BASE}/publish-preview`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  const data = await readJson<PublishState>(response, "发布状态加载失败");
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
  const response = await fetch(`${BASE}/topics`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  const data = await readJson<TopicState>(response, "选题清单加载失败");
  return {
    awaiting_generation: data.awaiting_generation ?? [],
    clusters_needing_questions: data.clusters_needing_questions ?? [],
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
  const response = await fetch(`${BASE}/clusters/${clusterId}/questions`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<ClusterQuestions>(response, "候选问句加载失败");
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
