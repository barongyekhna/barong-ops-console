/**
 * 跨 GEO/SEO 共享面板的 fetch 样板。
 *
 * 这三段（API_PROXY_BASE / buildHeaders / readJson）原来在 LinkNetPanel、
 * ContentHealthPanel、SiteNavPanel 里**各复制一份**，一模一样。内容台是第四个
 * 用到它们的地方——再抄一遍就是第四份副本，四份必然分叉。
 */

export const API_PROXY_BASE = "/api/backend";
export const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
export const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

export function buildHeaders(json = false) {
  const headers = new Headers({ Accept: "application/json" });
  if (json) headers.set("Content-Type", "application/json");
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

export async function readJson<T>(response: Response, label: string): Promise<T> {
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as {
        detail?: string | { blockers?: string[] };
      };
      if (typeof body?.detail === "string") {
        detail = `：${body.detail}`;
      } else if (Array.isArray(body?.detail?.blockers)) {
        // 发布门禁的 409 是结构化的：把「为什么发不出去」原样说出来。
        detail = `：${body.detail.blockers.join("；")}`;
      }
    } catch {
      detail = "";
    }
    throw new Error(`${label}（${response.status}）${detail}`);
  }
  return (await response.json()) as T;
}
