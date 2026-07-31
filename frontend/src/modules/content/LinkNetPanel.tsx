"use client";

import { useCallback, useEffect, useState } from "react";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

const GOLD = "#d9a441";
const GREEN = "#55bd88";
const RED = "#dd6d63";
const MUTED = "#8b98a8";

type LinkNetState = {
  fingerprint: string;
  pushed_at: string;
  dirty: boolean;
  summary: {
    posts?: number;
    products?: number;
    guides?: number;
    factory?: number;
    token_matched?: string[];
  };
  product_pages: {
    stale_count: number;
    reasons: string[];
    skipped: string[];
  };
};

function buildHeaders(json = false) {
  const headers = new Headers({ Accept: "application/json" });
  if (json) headers.set("Content-Type", "application/json");
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
    if (token) headers.set("Authorization", `Bearer ${token}`);
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

/**
 * 内链网面板。GeoContentDeck 和 SeoDeck 挂的是同一个组件——
 * 内链网本来就是跨 GEO/SEO 的一件事，做两份必然分叉。
 */
export function LinkNetPanel() {
  const [state, setState] = useState<LinkNetState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const response = await fetch(`${API_PROXY_BASE}/seo/link-net`, {
        cache: "no-store",
        headers: buildHeaders(),
        method: "GET",
      });
      setState(await readJson<LinkNetState>(response, "内链网状态加载失败"));
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const run = useCallback(
    async (action: () => Promise<string | null>) => {
      setBusy(true);
      setError(null);
      try {
        setNotice(await action());
        await reload();
      } catch (actionError) {
        setError((actionError as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [reload],
  );

  const summary = state?.summary ?? {};
  const pages = state?.product_pages ?? { stale_count: 0, reasons: [], skipped: [] };
  const tokenMatched = summary.token_matched ?? [];

  return (
    <div style={{ display: "grid", gap: 12 }}>
      {error ? (
        <div style={{ ...card, borderColor: `${RED}66`, color: RED }}>{error}</div>
      ) : null}
      {notice ? (
        <div style={{ ...card, borderColor: `${GREEN}66`, color: GREEN }}>
          {notice}
        </div>
      ) : null}

      {/* ---- 文章内链：全自动 ---- */}
      <div style={card}>
        <div style={{ alignItems: "center", display: "flex", flexWrap: "wrap", gap: 8 }}>
          <strong style={{ color: "#dfe6ef", fontSize: 14 }}>文章内链</strong>
          <span style={{ color: MUTED, fontSize: 12 }}>
            覆盖 {summary.posts ?? 0} 篇 · {summary.products ?? 0} 张产品卡 ·{" "}
            {summary.guides ?? 0} 篇指南 · {summary.factory ?? 0} 篇工艺文
          </span>
          <span style={{ flex: 1 }} />
          <button
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const response = await fetch(
                  `${API_PROXY_BASE}/seo/link-net/refresh`,
                  { headers: buildHeaders(true), method: "POST" },
                );
                const result = await readJson<{
                  ok: boolean;
                  changed: boolean;
                  reason?: string;
                  posts?: number;
                }>(response, "刷新失败");
                if (!result.ok) return result.reason ?? "推送失败";
                // 让人看得见「什么都没做」也是正确结果
                return result.changed
                  ? `已推送：覆盖 ${result.posts ?? 0} 篇文章。`
                  : "内容没有变化，未推送。";
              })
            }
            style={primary}
            type="button"
          >
            刷新文章内链
          </button>
        </div>
        <div style={{ color: MUTED, fontSize: 11, marginTop: 8 }}>
          新文章发布、新产品上架时**自动刷新**；这个按钮只为立刻看效果。
          {state?.pushed_at ? ` 上次推送：${state.pushed_at.slice(0, 19).replace("T", " ")}` : ""}
          {state?.dirty ? " · 有改动待推送" : ""}
        </div>
        {tokenMatched.length > 0 ? (
          <div style={{ color: GOLD, fontSize: 11, marginTop: 8 }}>
            ⚠ {tokenMatched.length} 张卡片是靠词面匹配挑的，建议核一眼：
            {tokenMatched.slice(0, 3).join("、")}
          </div>
        ) : null}
      </div>

      {/* ---- 产品页链接：人工，因为它是投放落地页 ---- */}
      <div style={card}>
        <div style={{ alignItems: "center", display: "flex", flexWrap: "wrap", gap: 8 }}>
          <strong style={{ color: "#dfe6ef", fontSize: 14 }}>产品页链接</strong>
          {pages.stale_count > 0 ? (
            <span style={{ color: GOLD, fontSize: 12 }}>
              ⚠ 有 {pages.stale_count} 个产品页的链接已过期
            </span>
          ) : (
            <span style={{ color: MUTED, fontSize: 12 }}>全部是最新的</span>
          )}
          <span style={{ flex: 1 }} />
          <button
            disabled={busy || pages.stale_count === 0}
            onClick={() =>
              void run(async () => {
                const response = await fetch(`${API_PROXY_BASE}/geo/backlinks`, {
                  headers: buildHeaders(true),
                  method: "POST",
                });
                const result = await readJson<{ job_id?: string }>(
                  response,
                  "派单失败",
                );
                return `已派单 ${result.job_id ?? ""}，n8n 正在更新产品页。`;
              })
            }
            style={pages.stale_count > 0 ? primary : ghost}
            type="button"
          >
            同步产品页链接
          </button>
        </div>
        <div style={{ color: MUTED, fontSize: 11, marginTop: 8 }}>
          产品页是投放落地页，所以**由你决定什么时候变**——这一侧不自动刷新。
        </div>
        {pages.reasons.length > 0 ? (
          <ul style={{ color: "#c7d0da", fontSize: 12, margin: "8px 0 0 18px" }}>
            {pages.reasons.slice(0, 8).map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

const card: React.CSSProperties = {
  background: "#0d131bcc",
  border: "1px solid #ffffff1a",
  borderRadius: 10,
  padding: 14,
};

const primary: React.CSSProperties = {
  background: `${GOLD}22`,
  border: `1px solid ${GOLD}88`,
  borderRadius: 6,
  color: GOLD,
  cursor: "pointer",
  fontSize: 12,
  padding: "6px 14px",
};

const ghost: React.CSSProperties = {
  background: "transparent",
  border: "1px solid #ffffff22",
  borderRadius: 6,
  color: "#b9c4d1",
  cursor: "pointer",
  fontSize: 12,
  padding: "5px 12px",
};
