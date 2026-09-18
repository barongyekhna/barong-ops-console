"use client";

import { useCallback, useEffect, useState } from "react";

import styles from "./AmzWorkspace.module.css";
import { getReviewTrend, pasteReviews, type AmzReviewTrend } from "./api";

const LINES: Record<string, string> = { pump: "沐浴泵", heater: "热水棒", flash: "太阳能手电", nail: "磨甲器", bundle: "套装" };

/**
 * 评论簇按月看占比:这个月差评里「预期落差」占多少,改了文案 / 副图之后有没有掉下来。
 * 亚马逊没有评论正文 API,评论靠人贴:每条之间空一行;从亚马逊页面直接复制也行(星级和日期会自动认)。
 */
export function ReviewsTrend() {
  const [line, setLine] = useState("pump");
  const [whose, setWhose] = useState<"ours" | "competitor">("ours");
  const [trend, setTrend] = useState<AmzReviewTrend | null>(null);
  const [text, setText] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setTrend(await getReviewTrend(line, whose));
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, [line, whose]);

  useEffect(() => {
    void load();
  }, [load]);

  async function paste() {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const out = await pasteReviews({ product_line: line, whose, text });
      setStatus(`收进 ${out.added} 条(重复的自动跳过),已归簇`);
      setText("");
      await load();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const families = ["defect", "expectation", "logistics", "other"];
  const labels = trend?.months[0]?.families.reduce<Record<string, string>>((acc, f) => ({ ...acc, [f.family]: f.label }), {}) ?? {};

  return (
    <section className={styles.panel} aria-label="评论簇按月">
      <div className={styles.panelHead}>
        <h2>评论簇 · 按月看占比</h2>
        <span className={styles.muted}>产品缺陷 → 工厂 / 事实表;预期落差 → 殷笑笑 + 殷熊;物流 → FBA 包装</span>
      </div>
      <div className={styles.sheetActions}>
        {Object.entries(LINES).map(([k, v]) => (
          <button className={k === line ? styles.button : styles.linkButton} key={k} onClick={() => setLine(k)} type="button">
            {v}
          </button>
        ))}
        <button className={whose === "ours" ? styles.button : styles.linkButton} onClick={() => setWhose("ours")} type="button">
          自家
        </button>
        <button className={whose === "competitor" ? styles.button : styles.linkButton} onClick={() => setWhose("competitor")} type="button">
          对手
        </button>
      </div>
      {status ? <div className={styles.muted}>{status}</div> : null}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>月份</th>
              <th>条数</th>
              {families.map((f) => (
                <th key={f}>{labels[f] ?? f}</th>
              ))}
              <th>前三个主题</th>
            </tr>
          </thead>
          <tbody>
            {(trend?.months ?? []).map((m) => (
              <tr key={m.month}>
                <td>{m.month}</td>
                <td>
                  {m.total}
                  {m.undated ? <div className={styles.muted}>{m.undated} 条没认出日期,按贴进来那天算</div> : null}
                </td>
                {families.map((f) => {
                  const hit = m.families.find((x) => x.family === f);
                  return <td key={f}>{hit && hit.count ? `${hit.share_pct}%(${hit.count})` : "—"}</td>;
                })}
                <td className={styles.muted}>{m.top_clusters.map((c) => `${c.theme} ${c.share_pct}%`).join(" · ")}</td>
              </tr>
            ))}
            {trend && trend.months.length === 0 ? (
              <tr>
                <td className={styles.muted} colSpan={6}>
                  还没有评论。把评论原文贴在下面(每条之间空一行)
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <label className={styles.muted} style={{ display: "grid", gap: 6 }}>
        贴评论({LINES[line]} · {whose === "ours" ? "自家" : "对手"})
        <textarea onChange={(e) => setText(e.target.value)} placeholder={"1.0 out of 5 stars Doesn't heat the water. Reviewed in the United States on August 3, 2026\n\n2星 用了一周就漏水"} rows={5} value={text} />
      </label>
      <div className={styles.sheetActions}>
        <button className={styles.button} disabled={busy || !text.trim()} onClick={() => void paste()} type="button">
          收进来并归簇
        </button>
      </div>
    </section>
  );
}
