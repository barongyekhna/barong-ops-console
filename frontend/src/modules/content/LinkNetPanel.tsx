"use client";

import { useCallback, useEffect, useState } from "react";

import { contentRequest, SLOW_WP_TIMEOUT_MS } from "./api-base";

const GOLD = "var(--color-warning)";
const GREEN = "var(--color-success)";
const RED = "var(--color-error)";
const MUTED = "var(--color-muted)";

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
      setState(
        await contentRequest<LinkNetState>("/seo/link-net", "内链网状态加载失败"),
      );
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
          <strong style={{ color: "var(--color-text-strong)", fontSize: 14 }}>文章内链</strong>
          <span style={{ color: MUTED, fontSize: 12 }}>
            覆盖 {summary.posts ?? 0} 篇 · {summary.products ?? 0} 张产品卡 ·{" "}
            {summary.guides ?? 0} 篇指南 · {summary.factory ?? 0} 篇工艺文
          </span>
          <span style={{ flex: 1 }} />
          <button
            disabled={busy}
            onClick={() =>
              void run(async () => {
                // 同步打 WP.com 覆盖文章内链，不是派单 —— 默认 15 秒不够。
                const result = await contentRequest<{
                  ok: boolean;
                  changed: boolean;
                  reason?: string;
                  posts?: number;
                }>("/seo/link-net/refresh", "刷新失败", {
                  method: "POST",
                  timeoutMs: SLOW_WP_TIMEOUT_MS,
                });
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
          <strong style={{ color: "var(--color-text-strong)", fontSize: 14 }}>产品页链接</strong>
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
                // 这一条是**派单**（返回 job_id 就走），默认超时够用。
                const result = await contentRequest<{ job_id?: string }>(
                  "/geo/backlinks",
                  "派单失败",
                  { method: "POST" },
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
          <ul style={{ color: "var(--color-text)", fontSize: 12, margin: "8px 0 0 18px" }}>
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
  background: "color-mix(in srgb, var(--color-panel-base) 80%, transparent)",
  border: "1px solid color-mix(in srgb, var(--color-line-strong) 10%, transparent)",
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
  border: "1px solid color-mix(in srgb, var(--color-line-strong) 13%, transparent)",
  borderRadius: 6,
  color: "var(--color-text)",
  cursor: "pointer",
  fontSize: 12,
  padding: "5px 12px",
};
