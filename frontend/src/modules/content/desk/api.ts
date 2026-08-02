import { API_PROXY_BASE, buildHeaders, readJson } from "../api-base";
import type { Article } from "./types";

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
