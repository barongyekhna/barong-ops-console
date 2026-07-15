"use client";

import {
  Boxes,
  Brain,
  Check,
  Copy,
  ExternalLink,
  Loader2,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  createRaExpansion,
  getRaExpansion,
  getRaReportDetail,
  requestRaOpusReview,
} from "@/modules/r/analysis/api";
import type {
  RaExpansion,
  RaOpusReview,
  RaReportDetail,
} from "@/modules/r/analysis/types";

import styles from "./DetailModal.module.css";

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

const LAYER_LABELS: Record<string, string> = {
  deepseek: "DeepSeek 初筛",
  vision: "AI 看图",
  gpt: "GPT 终审",
  opus: "Opus 复核",
};

const TREND_LABELS: Record<string, string> = {
  improving: "上升（排名变好）",
  declining: "下滑",
  stable: "平稳",
  unknown: "数据不足",
};

function fmtSearches(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "—";
  }
  return value >= 10000
    ? `${(value / 10000).toFixed(1).replace(/\.0$/, "")}万`
    : value.toLocaleString();
}

function usdFromMicros(micros: number | null | undefined): string {
  if (typeof micros !== "number" || !Number.isFinite(micros) || micros <= 0) {
    return "—";
  }
  return `$${(micros / 1e6).toFixed(2)}`;
}

// 日常价估算:实际点击均价通常贴低位区间走,取 low + (high-low)*0.25。
function typicalCpcMicros(
  gads: { cpc_low_micros?: number | null; cpc_high_micros?: number | null } | null | undefined,
): number | null {
  const low = gads?.cpc_low_micros;
  const high = gads?.cpc_high_micros;
  if (typeof low === "number" && low > 0 && typeof high === "number" && high > 0) {
    return low + (high - low) * 0.25;
  }
  return typeof low === "number" && low > 0 ? low : null;
}

export function DetailModal({
  reportId,
  onClose,
}: {
  reportId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<RaReportDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opusBusy, setOpusBusy] = useState(false);
  const [opusResult, setOpusResult] = useState<RaOpusReview | null>(null);
  const [expansion, setExpansion] = useState<RaExpansion | null>(null);
  const [expansionBusy, setExpansionBusy] = useState(false);
  const [copied, setCopied] = useState<"" | "amazon" | "google">("");
  const pollRef = useRef<number | null>(null);

  const copyKeywords = useCallback(
    (channel: "amazon" | "google", lines: string[]) => {
      const textValue = lines.filter(Boolean).join("\n");
      if (!textValue) {
        return;
      }
      void navigator.clipboard.writeText(textValue).then(() => {
        setCopied(channel);
        window.setTimeout(() => setCopied(""), 1800);
      });
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    getRaReportDetail(reportId)
      .then((payload) => {
        if (!cancelled) {
          setDetail(payload);
          setOpusResult(payload.opus_review);
        }
      })
      .catch((requestError: unknown) => {
        if (!cancelled) {
          setError(
            requestError instanceof Error ? requestError.message : "详情读取失败。",
          );
        }
      });
    getRaExpansion(reportId)
      .then((payload) => {
        if (!cancelled && payload.status !== "none") {
          setExpansion(payload);
        }
      })
      .catch(() => null);
    return () => {
      cancelled = true;
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
      }
    };
  }, [reportId]);

  // 扩品进行中每 6 秒轮询。
  useEffect(() => {
    if (!expansion || !["pending", "running"].includes(expansion.status)) {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    if (pollRef.current !== null) {
      return;
    }
    pollRef.current = window.setInterval(() => {
      getRaExpansion(reportId)
        .then((payload) => setExpansion(payload))
        .catch(() => null);
    }, 6_000);
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [expansion, reportId]);

  const handleOpus = useCallback(async () => {
    setOpusBusy(true);
    setError(null);
    try {
      const result = await requestRaOpusReview(reportId);
      setOpusResult(result);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Opus 建议生成失败。",
      );
    } finally {
      setOpusBusy(false);
    }
  }, [reportId]);

  const handleExpand = useCallback(async () => {
    setExpansionBusy(true);
    setError(null);
    try {
      const payload = await createRaExpansion(reportId);
      setExpansion(payload);
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "扩品任务创建失败。",
      );
    } finally {
      setExpansionBusy(false);
    }
  }, [reportId]);

  const product = (detail?.product ?? {}) as Record<string, unknown>;
  const competition = (detail?.competition ?? {}) as Record<string, unknown>;
  const kw = detail?.keyword_channels;
  const deep = detail?.deep_enrichment;
  const gads = kw?.google_seo?.google_ads ?? null;

  return (
    <div className={styles.overlay} onClick={onClose} role="presentation">
      <div
        className={styles.modal}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <button type="button" className={styles.closeButton} onClick={onClose}>
          <X size={18} />
        </button>

        {!detail && !error ? (
          <p className={styles.loading}>
            <Loader2 className={styles.spin} size={16} /> 读取完整数据…
          </p>
        ) : null}
        {error ? <p className={styles.error}>{error}</p> : null}

        {detail ? (
          <div className={styles.body}>
            <header className={styles.head}>
              {detail.product_image_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={detail.product_image_url} alt="" className={styles.headImage} />
              ) : (
                <div className={styles.headImageFallback}>
                  <Boxes size={26} />
                </div>
              )}
              <div>
                <h3>{detail.title ?? detail.asin}</h3>
                <p className={styles.headMeta}>
                  {detail.asin} · 终审{" "}
                  {String((detail.final as Record<string, unknown>)?.verdict ?? "—")} ·{" "}
                  {String((detail.final as Record<string, unknown>)?.final_score ?? "—")} 分
                </p>
              </div>
            </header>

            {/* Keepa 基础数据 */}
            <section className={styles.section}>
              <h4>Keepa 数据（R-W 抓取）</h4>
              <div className={styles.statRow}>
                <span>售价 ${num(product.price)?.toFixed(2) ?? "—"}</span>
                <span>月销 ~{num(product.monthly_sales) ?? "—"}</span>
                <span>BSR {num(product.bsr) ?? "—"}</span>
                <span>评论 {num(product.reviews) ?? "—"}</span>
                <span>评分 {num(product.rating) ?? "—"}</span>
                <span>
                  毛利{" "}
                  {num(product.gross_margin) !== null
                    ? `${((num(product.gross_margin) as number) * 100).toFixed(1)}%`
                    : "—"}
                </span>
              </div>
            </section>

            {/* AI 审核链 */}
            <section className={styles.section}>
              <h4>AI 审核链（通过/拒绝理由）</h4>
              {detail.layers.map((layer, index) => (
                <div key={index} className={styles.layerRow} data-verdict={layer.verdict ?? ""}>
                  <span className={styles.layerName}>
                    {LAYER_LABELS[layer.layer ?? ""] ?? layer.layer} {layer.score ?? "—"} 分 ·{" "}
                    {layer.verdict}
                  </span>
                  <p>{layer.reason}</p>
                  {layer.advantages.length > 0 ? (
                    <p className={styles.pros}>✓ {layer.advantages.join("；")}</p>
                  ) : null}
                  {layer.risks.length > 0 ? (
                    <p className={styles.cons}>⚠ {layer.risks.join("；")}</p>
                  ) : null}
                </div>
              ))}
            </section>

            {/* Rainforest 竞争 */}
            <section className={styles.section}>
              <h4>Rainforest 竞争数据（亚马逊页一）</h4>
              <div className={styles.statRow}>
                <span>评论墙 {num(competition.review_wall_max) ?? "—"}</span>
                <span>
                  品牌集中度{" "}
                  {num(competition.single_brand_share) !== null
                    ? `${((num(competition.single_brand_share) as number) * 100).toFixed(0)}%`
                    : "—"}
                </span>
                <span>主导品牌 {String(competition.dominant_brand ?? "—")}</span>
                <span>页一卖家 ~{num(competition.market_seller_count_est) ?? "—"}</span>
              </div>
            </section>

            {/* 深度富化：Keepa 12 个月趋势 + 价格地板 */}
            <section className={styles.section}>
              <h4>Keepa 12 个月趋势（利润通过后深挖）</h4>
              {deep?.keepa && Object.keys(deep.keepa).length > 0 ? (
                <>
                  <div className={styles.statRow}>
                    <span>
                      历史 {deep.keepa.history_days ?? "—"} 天
                      {deep.keepa.has_12m_history ? " ✓满12月" : " ⚠不足12月"}
                    </span>
                    <span
                      className={styles.trendBadge}
                      data-trend={deep.keepa.bsr_trend_12m ?? "unknown"}
                    >
                      BSR {TREND_LABELS[deep.keepa.bsr_trend_12m ?? "unknown"] ?? "数据不足"}
                      {typeof deep.keepa.bsr_change_pct_12m === "number"
                        ? ` ${deep.keepa.bsr_change_pct_12m > 0 ? "+" : ""}${deep.keepa.bsr_change_pct_12m}%`
                        : ""}
                    </span>
                    <span>
                      价格地板{" "}
                      {deep.keepa.price_floor_declining === true
                        ? `⚠ 走低 ${deep.keepa.price_floor_change_pct_12m ?? ""}%`
                        : deep.keepa.price_floor_declining === false
                          ? "✓ 稳定"
                          : "—"}
                    </span>
                    <span>12月最低价 ${deep.keepa.min_price_12m ?? "—"}</span>
                    <span>当前价 ${deep.keepa.current_new_price ?? "—"}</span>
                    {deep.keepa.viral_suspect ? (
                      <span className={styles.viralFlag}>⚠ 疑似网红昙花款</span>
                    ) : null}
                  </div>
                  {(deep.keepa.monthly_price_floors?.length ?? 0) >= 4 ? (
                    <div className={styles.floorBars} title="近12个月每月最低价轨迹">
                      {(deep.keepa.monthly_price_floors ?? []).map((floor, index) => {
                        const floors = deep.keepa?.monthly_price_floors ?? [];
                        const max = Math.max(...floors, 0.01);
                        return (
                          <div key={index} className={styles.floorBarWrap}>
                            <div
                              className={styles.floorBar}
                              style={{ height: `${Math.max(8, (floor / max) * 100)}%` }}
                            />
                            <span>${floor}</span>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                </>
              ) : (
                <p className={styles.deepGap}>
                  {deep?.errors?.keepa
                    ? `Keepa 拉取失败：${deep.errors.keepa}`
                    : "暂无 Keepa 深度数据（旧报告点一次「Opus 建议」即可回填）。"}
                </p>
              )}
            </section>

            {/* 深度富化：Rainforest 全量 listing 事实 + 真实差评 */}
            <section className={styles.section}>
              <h4>真实差评与 listing 深数据（Rainforest 全量）</h4>
              {deep?.rainforest_product &&
              Object.keys(deep.rainforest_product).length > 0 ? (
                <>
                  <div className={styles.statRow}>
                    <span>品牌 {deep.rainforest_product.brand ?? "—"}</span>
                    <span>
                      评分 {deep.rainforest_product.rating ?? "—"}（
                      {deep.rainforest_product.ratings_total ?? "—"} 条）
                    </span>
                    <span>
                      1-2星占比{" "}
                      {(() => {
                        const rb = deep.rainforest_product?.rating_breakdown ?? {};
                        const low = (rb.one_star ?? 0) + (rb.two_star ?? 0);
                        return low > 0 ? `${low}%` : "—";
                      })()}
                    </span>
                    {deep.rainforest_product.recent_sales ? (
                      <span className={styles.viralFlag}>
                        🔥 {deep.rainforest_product.recent_sales}
                      </span>
                    ) : null}
                    <span>变体 {deep.rainforest_product.variant_count ?? "—"}</span>
                    <span>图片 {deep.rainforest_product.images_count ?? "—"}</span>
                    <span>视频 {deep.rainforest_product.videos_count ?? "—"}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span>
                      Buybox ${deep.rainforest_product.buybox_price ?? "—"}
                      {deep.rainforest_product.buybox_fulfillment
                        ? ` · ${deep.rainforest_product.buybox_fulfillment}`
                        : ""}
                    </span>
                    <span>
                      A+ 页面 {deep.rainforest_product.has_a_plus_content ? "有" : "无"}
                    </span>
                    <span>
                      优惠券{" "}
                      {deep.rainforest_product.has_coupon
                        ? deep.rainforest_product.coupon_text ?? "有"
                        : "无"}
                    </span>
                    {deep.rainforest_product.proposition_65_warning ? (
                      <span className={styles.viralFlag}>⚠ 加州65合规警告</span>
                    ) : null}
                    {(deep.rainforest_product.bestsellers_rank?.length ?? 0) > 0 ? (
                      <span>
                        BSR{" "}
                        {(deep.rainforest_product.bestsellers_rank ?? [])
                          .map((entry) => `#${entry.rank} ${entry.category ?? ""}`)
                          .join(" / ")}
                      </span>
                    ) : null}
                  </div>
                  {deep.rainforest_product.listing_keywords ? (
                    <p className={styles.deepGap}>
                      listing 关键词：{deep.rainforest_product.listing_keywords}
                    </p>
                  ) : null}
                </>
              ) : null}
              {deep?.review_themes?.differentiation_summary ? (
                <p className={styles.diffSummary}>
                  🎯 差异化一句话：{deep.review_themes.differentiation_summary}
                </p>
              ) : null}
              {(deep?.review_themes?.top_complaints?.length ?? 0) > 0 ? (
                <div>
                  <p className={styles.kwGroupLabel}>
                    差评主题（{deep?.review_themes?.review_count_analyzed ?? "—"} 条差评提炼 ·
                    严重度 {deep?.review_themes?.severity ?? "—"}）
                  </p>
                  {(deep?.review_themes?.top_complaints ?? []).map((complaint, index) => (
                    <div key={index} className={styles.themeRow}>
                      <span className={styles.themeName}>{complaint.theme}</span>
                      {complaint.evidence ? <p>「{complaint.evidence}」</p> : null}
                      {complaint.improvement_angle ? (
                        <p className={styles.pros}>改法：{complaint.improvement_angle}</p>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
              {(deep?.reviews?.length ?? 0) > 0 ? (
                <details className={styles.reviewFold}>
                  <summary>差评原文（{deep?.reviews?.length} 条）</summary>
                  {(deep?.reviews ?? []).map((review, index) => (
                    <blockquote key={index} className={styles.reviewQuote}>
                      <span>
                        ★{review.rating ?? "—"} {review.title}
                        {review.verified ? " · 已验证购买" : ""}
                        {review.date ? ` · ${review.date}` : ""}
                      </span>
                      <p>{review.body}</p>
                    </blockquote>
                  ))}
                </details>
              ) : (
                <p className={styles.deepGap}>
                  {deep?.errors?.rainforest
                    ? `Rainforest 深数据失败：${deep.errors.rainforest}`
                    : deep?.rainforest_product &&
                        Object.keys(deep.rainforest_product).length > 0
                      ? "该产品页一暂无可抓取的差评（差评少本身也是信号）。"
                      : "暂无差评深数据（旧报告点一次「Opus 建议」即可回填）。"}
                </p>
              )}
            </section>

            {/* 关键词：分渠道，列表形式 + 一键复制 */}
            {kw ? (
              <section className={styles.section}>
                <h4>关键词（分渠道标注）</h4>
                <div className={styles.keywordColumns}>
                  <div className={styles.kwCol}>
                    <div className={styles.kwColHead}>
                      <h5>🛒 亚马逊关键词</h5>
                      <button
                        type="button"
                        className={styles.copyButton}
                        onClick={() =>
                          copyKeywords("amazon", [
                            kw.amazon.primary ?? "",
                            ...kw.amazon.core_keywords,
                            ...kw.amazon.long_tail_keywords,
                          ])
                        }
                      >
                        {copied === "amazon" ? (
                          <>
                            <Check size={12} /> 已复制
                          </>
                        ) : (
                          <>
                            <Copy size={12} /> 一键复制
                          </>
                        )}
                      </button>
                    </div>
                    <p className={styles.kwSource}>{kw.amazon.source}</p>
                    {kw.amazon.primary ? (
                      <>
                        <p className={styles.kwGroupLabel}>主关键词</p>
                        <ol className={styles.kwList}>
                          <li data-primary="true">{kw.amazon.primary}</li>
                        </ol>
                      </>
                    ) : null}
                    {kw.amazon.core_keywords.length > 0 ? (
                      <>
                        <p className={styles.kwGroupLabel}>核心投放词</p>
                        <ol className={styles.kwList}>
                          {kw.amazon.core_keywords.map((word) => (
                            <li key={word}>{word}</li>
                          ))}
                        </ol>
                      </>
                    ) : null}
                    {kw.amazon.long_tail_keywords.length > 0 ? (
                      <>
                        <p className={styles.kwGroupLabel}>长尾词</p>
                        <ol className={styles.kwList}>
                          {kw.amazon.long_tail_keywords.map((word) => (
                            <li key={word}>{word}</li>
                          ))}
                        </ol>
                      </>
                    ) : null}
                    {kw.amazon.core_keywords.length === 0 &&
                    kw.amazon.long_tail_keywords.length === 0 ? (
                      <p className={styles.kwSource}>
                        （关键词提炼中，重新打开详情即可看到）
                      </p>
                    ) : null}
                  </div>
                  <div className={styles.kwCol}>
                    <div className={styles.kwColHead}>
                      <h5>🔍 Google SEO 关键词</h5>
                      <button
                        type="button"
                        className={styles.copyButton}
                        onClick={() =>
                          copyKeywords("google", [
                            ...kw.google_seo.related_searches,
                            ...kw.google_seo.people_also_ask,
                          ])
                        }
                      >
                        {copied === "google" ? (
                          <>
                            <Check size={12} /> 已复制
                          </>
                        ) : (
                          <>
                            <Copy size={12} /> 一键复制
                          </>
                        )}
                      </button>
                    </div>
                    <p className={styles.kwSource}>{kw.google_seo.source}</p>
                    {kw.google_seo.related_searches.length > 0 ? (
                      <>
                        <p className={styles.kwGroupLabel}>相关搜索</p>
                        <ol className={styles.kwList}>
                          {kw.google_seo.related_searches.map((word) => (
                            <li key={word}>{word}</li>
                          ))}
                        </ol>
                      </>
                    ) : null}
                    {kw.google_seo.people_also_ask.length > 0 ? (
                      <>
                        <p className={styles.kwGroupLabel}>大家也在问</p>
                        <ol className={styles.kwList}>
                          {kw.google_seo.people_also_ask.map((question) => (
                            <li key={question}>{question}</li>
                          ))}
                        </ol>
                      </>
                    ) : null}
                    {kw.google_seo.related_searches.length === 0 &&
                    kw.google_seo.people_also_ask.length === 0 ? (
                      <p className={styles.kwSource}>
                        （本产品 SERP 未返回相关词）
                      </p>
                    ) : null}
                  </div>
                </div>
              </section>
            ) : null}

            {/* Google Ads 实测数据（Keyword Planner） */}
            <section className={styles.section}>
              <h4>Google Ads 实测数据（Keyword Planner）</h4>
              {gads && (gads.avg_monthly_searches !== null &&
                gads.avg_monthly_searches !== undefined) ||
              (gads?.ideas?.length ?? 0) > 0 ? (
                <>
                  <div className={styles.statRow}>
                    <span>
                      主词 Google 月搜索量{" "}
                      <strong className={styles.gadsBig}>
                        {fmtSearches(gads?.avg_monthly_searches)}
                      </strong>
                    </span>
                    <span>
                      广告竞争度{" "}
                      <strong
                        className={styles.gadsBig}
                        data-hot={(gads?.competition_index ?? 0) >= 80}
                      >
                        {gads?.competition_index ?? "—"}/100
                      </strong>
                    </span>
                  </div>
                  {gads?.cpc_low_micros || gads?.cpc_high_micros ? (
                    <>
                      <div className={styles.gadsCards}>
                        <div className={styles.gadsCard}>
                          <span className={styles.gadsCardLabel}>CPC 最低价</span>
                          <span className={styles.gadsCardValue}>
                            {usdFromMicros(gads?.cpc_low_micros)}
                          </span>
                          <span className={styles.gadsCardNote}>页首出价低位</span>
                        </div>
                        <div className={styles.gadsCard} data-kind="typical">
                          <span className={styles.gadsCardLabel}>日常价（估算）</span>
                          <span className={styles.gadsCardValue}>
                            {usdFromMicros(typicalCpcMicros(gads))}
                          </span>
                          <span className={styles.gadsCardNote}>
                            实际点击价通常贴此价走 · 算广告账用这个
                          </span>
                        </div>
                        <div className={styles.gadsCard}>
                          <span className={styles.gadsCardLabel}>CPC 最高价</span>
                          <span className={styles.gadsCardValue}>
                            {usdFromMicros(gads?.cpc_high_micros)}
                          </span>
                          <span className={styles.gadsCardNote}>
                            页首出价高位 · 旺季天花板
                          </span>
                        </div>
                      </div>
                      <p className={styles.gadsHint}>
                        💡 CPC 越高 = 这个流量被市场标价越贵 = SEO 自然位含金量越高
                      </p>
                    </>
                  ) : null}
                  {(gads?.ideas?.length ?? 0) > 0 ? (
                    <div className={styles.gadsTableWrap}>
                      <table className={styles.gadsTable}>
                        <thead>
                          <tr>
                            <th>相关关键词（Google 官方推荐）</th>
                            <th>月搜索量</th>
                            <th>竞争度</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(gads?.ideas ?? []).slice(0, 10).map((idea, index) => (
                            <tr key={index}>
                              <td>{idea.keyword}</td>
                              <td>{fmtSearches(idea.avg_monthly_searches)}</td>
                              <td>
                                {idea.competition_index !== null &&
                                idea.competition_index !== undefined
                                  ? `${idea.competition_index}/100`
                                  : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                </>
              ) : (
                <p className={styles.deepGap}>
                  {gads?.status === "enabled" || gads?.backfilled_at
                    ? "该主词过于长尾,Google 无搜索量数据（相关近似词见上方关键词列表）。"
                    : "Google Ads 数据将在下次审核时自动拉取。"}
                </p>
              )}
            </section>

            {/* 1688 供应商 */}
            <section className={styles.section}>
              <h4>1688 供应商（{detail.suppliers.length}）</h4>
              {detail.suppliers.slice(0, 8).map((supplier) => (
                <div key={supplier.offer_id} className={styles.supplierRow}>
                  <span>{supplier.supplier_name ?? "1688 供应商"}</span>
                  <span>¥{supplier.unit_price_cny ?? "—"}</span>
                  <span>起批 {supplier.moq ?? "—"}</span>
                  {supplier.supplier_url ? (
                    <a href={supplier.supplier_url} target="_blank" rel="noreferrer">
                      <ExternalLink size={13} /> 打开
                    </a>
                  ) : null}
                </div>
              ))}
            </section>

            {/* Opus 建议 */}
            <section className={styles.section}>
              <div className={styles.actionHead}>
                <h4>
                  <Brain size={15} /> Opus 系统建议
                </h4>
                <button
                  type="button"
                  className={styles.actionButton}
                  disabled={opusBusy}
                  onClick={() => void handleOpus()}
                >
                  {opusBusy ? (
                    <>
                      <Loader2 className={styles.spin} size={14} /> Opus 思考中（约 1 分钟）…
                    </>
                  ) : opusResult ? (
                    "重新生成建议"
                  ) : (
                    "获取 Opus 建议"
                  )}
                </button>
              </div>
              {opusResult ? (
                <div className={styles.opusBox}>
                  <p className={styles.opusVerdict}>
                    {opusResult.verdict} · {opusResult.score ?? "—"} 分
                  </p>
                  <p>{opusResult.reason}</p>
                  {(opusResult.advantages ?? []).length > 0 ? (
                    <p className={styles.pros}>✓ {(opusResult.advantages ?? []).join("；")}</p>
                  ) : null}
                  {(opusResult.risks ?? []).length > 0 ? (
                    <p className={styles.cons}>⚠ {(opusResult.risks ?? []).join("；")}</p>
                  ) : null}
                </div>
              ) : null}
            </section>

            {/* 1688 扩品 */}
            <section className={styles.section}>
              <div className={styles.actionHead}>
                <h4>
                  <Sparkles size={15} /> 1688 类目扩品（垂直类目海量上架）
                </h4>
                <button
                  type="button"
                  className={styles.actionButton}
                  disabled={
                    expansionBusy ||
                    ["pending", "running"].includes(expansion?.status ?? "")
                  }
                  onClick={() => void handleExpand()}
                >
                  {["pending", "running"].includes(expansion?.status ?? "") ? (
                    <>
                      <Loader2 className={styles.spin} size={14} /> 扩品中（图搜+词搜+AI 对比）…
                    </>
                  ) : expansion?.status === "completed" ? (
                    "重新扩品"
                  ) : (
                    <>
                      <Search size={14} /> 开始扩品
                    </>
                  )}
                </button>
              </div>
              {expansion?.status === "failed" ? (
                <p className={styles.error}>扩品失败：{expansion.error}</p>
              ) : null}
              {expansion?.status === "completed" ? (
                <div>
                  <p className={styles.kwSource}>
                    候选池 {String(expansion.counts?.raw_candidates ?? "—")} 个 → AI 精选{" "}
                    {(expansion.selected ?? []).length} 个优质款：
                  </p>
                  <div className={styles.expansionGrid}>
                    {(expansion.selected ?? []).map((item) => (
                      <a
                        key={item.offer_id}
                        className={styles.expansionCard}
                        href={item.detail_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {item.image_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={item.image_url} alt="" />
                        ) : (
                          <div className={styles.expansionImageFallback} />
                        )}
                        <div className={styles.expansionBody}>
                          <span className={styles.expansionRole} data-role={item.role}>
                            {item.role ?? "跑量"}
                          </span>
                          <p className={styles.expansionTitle}>{item.title}</p>
                          <p className={styles.expansionMeta}>
                            ¥{item.price_cny ?? "—"} · 已售 {item.sale_amount ?? "—"} · 评分{" "}
                            {item.composite_score ?? "—"}
                            {item.delivery_free ? " · 包邮" : ""}
                            {item.shili_supplier ? " · 实力商家" : ""}
                          </p>
                          {item.reason ? (
                            <p className={styles.expansionReason}>{item.reason}</p>
                          ) : null}
                        </div>
                      </a>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>
          </div>
        ) : null}
      </div>
    </div>
  );
}
