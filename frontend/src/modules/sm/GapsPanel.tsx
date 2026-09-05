"use client";

import { useEffect, useState } from "react";

import styles from "./SmWorkspace.module.css";
import { type Gap, PLATFORM_LABEL, codexPromptForGap, dismissImageRequest, getImageRequests } from "./api";

const LANE_LABEL: Record<Gap["lane"], string> = {
  layout: "版式渲染（代码当场填）",
  mcp: "Codex 精修（K 简报社媒位）",
  photo: "真照片（人拍，AI 不许画）",
};

export function GapsPanel({ onChanged, refreshTick, skuById }: { onChanged: () => void; refreshTick: number; skuById: Map<string, string> }) {
  const [gaps, setGaps] = useState<Gap[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<"open" | "filled" | "dormant" | "all">("open");
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getImageRequests({ status })
      .then((data) => {
        if (!cancelled) {
          setGaps(data.requests);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [status, refreshTick]);

  const handleCodex = async (gap: Gap) => {
    const sku = (gap.seed_product_id && skuById.get(gap.seed_product_id)) || gap.seed_product_id || "";
    const prompt = codexPromptForGap(sku, gap.k_position);
    let ok = false;
    try {
      await navigator.clipboard.writeText(prompt);
      ok = true;
    } catch {
      ok = false;
    }
    window.location.href = `codex://new?prompt=${encodeURIComponent(prompt)}`;
    setCopied(ok ? `已唤起 Codex，指令同时复制到剪贴板（${sku} 第 ${gap.k_position ?? "?"} 位）` : "已尝试唤起 Codex；剪贴板不可用，请手动粘贴");
    window.setTimeout(() => setCopied(null), 8000);
  };

  const handleDismiss = async (gap: Gap) => {
    try {
      await dismissImageRequest(gap.id);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const lanes: Gap["lane"][] = ["photo", "mcp", "layout"];

  return (
    <section className={styles.panel}>
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle}>缺口单</h2>
        <div className={styles.actions}>
          {(["open", "filled", "dormant", "all"] as const).map((s) => (
            <button className={styles.btnGhost} data-active={status === s} key={s} onClick={() => setStatus(s)} type="button" style={status === s ? { textDecoration: "underline" } : undefined}>
              {s === "open" ? "待填" : s === "filled" ? "已填" : s === "dormant" ? "长期缺口" : "全部"}
            </button>
          ))}
        </div>
      </div>
      {error ? <div className={styles.error}>{error}</div> : null}
      {copied ? <div className={styles.notice}>{copied}</div> : null}
      {gaps && gaps.length === 0 ? <p className={styles.muted}>没有缺口。</p> : null}
      {lanes.map((lane) => {
        const rows = (gaps ?? []).filter((g) => g.lane === lane);
        if (!rows.length) return null;
        return (
          <div key={lane}>
            <div className={styles.laneHead}>{LANE_LABEL[lane]} · {rows.length}</div>
            <div className={styles.list}>
              {rows.map((gap) => (
                <div className={styles.mediaCard} key={gap.id} style={{ width: "100%" }}>
                  <div className={styles.slotMeta}>
                    <span className={styles.pillar} data-pillar={gap.pillar}>{gap.pillar_label}</span>
                    <span>{PLATFORM_LABEL[gap.platform]}</span>
                    <span>· {gap.role} × {gap.count} · {gap.ratio}</span>
                    <span>· 截止 {gap.due_day}</span>
                    <span className={styles.status} data-status={gap.status}>{gap.status}</span>
                    {gap.k_position ? <span className={styles.mono}>K 位 {gap.k_position}</span> : null}
                    {gap.seed_product_id ? <span className={styles.mono}>{skuById.get(gap.seed_product_id) ?? ""}</span> : null}
                  </div>
                  <div className={styles.brief}>{gap.brief_text}</div>
                  {gap.prompt_text ? <div className={`${styles.muted} ${styles.mono}`}>{gap.prompt_text}</div> : null}
                  <div className={styles.actions}>
                    {gap.lane === "mcp" && gap.status === "open" ? (
                      <button className={styles.btnPrimary} onClick={() => handleCodex(gap)} type="button">唤起 Codex 作图</button>
                    ) : null}
                    {gap.lane === "photo" && gap.status === "open" ? (
                      <span className={styles.muted}>拍好后从 K 产品页「图片管理」上传，角色选 {gap.role}；扫描器每小时关单。</span>
                    ) : null}
                    {gap.status === "open" ? (
                      <button className={styles.btnGhost} onClick={() => handleDismiss(gap)} type="button">转为长期缺口</button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </section>
  );
}
