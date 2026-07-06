"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Database,
  ExternalLink,
  Loader2,
  Search,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import {
  createRaAutoProfitJob,
  getRaAutoProfitJob,
  getRaFrameworkStatus,
  getRaProfitSnapshots,
} from "@/modules/r/analysis/api";
import type {
  RaAutoProfitItem,
  RaAutoProfitJobResult,
  RaFrameworkStatus,
  RaProfitSnapshot,
} from "@/modules/r/analysis/types";

import styles from "./AnalysisWorkspace.module.css";

const DEFAULT_ASIN_LIMIT = 20;
const DEFAULT_SUPPLIER_LIMIT = 5;
const POLL_INTERVAL_MS = 3_000;

export function AnalysisWorkspace({ view }: { view: "dashboard" | "analysis" }) {
  const [status, setStatus] = useState<RaFrameworkStatus | null>(null);
  const [snapshots, setSnapshots] = useState<RaProfitSnapshot[]>([]);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<RaAutoProfitJobResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([getRaFrameworkStatus(), getRaProfitSnapshots()])
      .then(([frameworkStatus, snapshotPayload]) => {
        if (cancelled) {
          return;
        }
        setStatus(frameworkStatus);
        setSnapshots(snapshotPayload.items);
        setError(null);
      })
      .catch((requestError: unknown) => {
        if (cancelled) {
          return;
        }
        setError(
          requestError instanceof Error
            ? requestError.message
            : "R-A 后端状态接口暂时不可读。",
        );
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!result?.run_id || isTerminalStatus(result.status)) {
      return undefined;
    }

    let cancelled = false;
    const poll = async () => {
      try {
        const payload = await getRaAutoProfitJob(result.run_id);
        if (cancelled) {
          return;
        }
        setResult(payload);
        if (isTerminalStatus(payload.status)) {
          setRunning(false);
          const snapshotPayload = await getRaProfitSnapshots();
          if (!cancelled) {
            setSnapshots(snapshotPayload.items);
          }
        }
      } catch (requestError) {
        if (!cancelled) {
          setRunError(
            requestError instanceof Error
              ? requestError.message
              : "读取后台任务进度失败。",
          );
        }
      }
    };

    const timer = window.setInterval(() => {
      void poll();
    }, POLL_INTERVAL_MS);
    void poll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [result?.run_id, result?.status]);

  const summary = useMemo(() => {
    if (!result) {
      return {
        matched: status?.candidate_source.ra_eligible ?? null,
        offers: snapshots.length,
        priced: snapshots.filter((snapshot) => snapshot.gross_margin !== null).length,
        passed: snapshots.filter((snapshot) => snapshot.verdict === "pass").length,
      };
    }
    return {
      matched: result.counts.matched_products,
      offers: result.counts.candidate_offers,
      priced: result.counts.priced_offers,
      passed: result.counts.profit_pass,
    };
  }, [result, snapshots, status]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleaned = query.trim();
    if (!cleaned) {
      setRunError("请输入关键词或类目。");
      return;
    }
    setRunning(true);
    setRunError(null);
    try {
      const payload = await createRaAutoProfitJob({
        asin_limit: DEFAULT_ASIN_LIMIT,
        query: cleaned,
        supplier_limit: DEFAULT_SUPPLIER_LIMIT,
      });
      setResult(payload);
      setRunning(!isTerminalStatus(payload.status));
    } catch (requestError) {
      setRunning(false);
      setRunError(
        requestError instanceof Error
          ? requestError.message
          : "自动利润分析失败。",
      );
    }
  }

  return (
    <div className={styles.workspace}>
      <section className={styles.heroBand}>
        <div className={styles.heroText}>
          <span className={styles.kicker}>R-A 自动利润分析</span>
          <h2>{view === "dashboard" ? "利润候选总览" : "关键词/类目利润测算"}</h2>
          <p>
            输入模糊关键词或类目后，系统只从 R-W 产品库中匹配同关键词/同类目的
            ASIN，再自动搜索多平台供应商并按美国站公式计算毛利润。
          </p>
        </div>
        <div className={styles.statusPill} data-state={error ? "error" : "ready"}>
          {error ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
          <span>{error ? "状态接口异常" : loading ? "读取中" : "后端已连接"}</span>
        </div>
      </section>

      {error ? (
        <section className={styles.noticeBand}>
          <AlertTriangle size={18} />
          <div>
            <strong>后端状态接口暂时不可读，但页面不会清空</strong>
            <span>{error}</span>
          </div>
        </section>
      ) : null}

      <section className={styles.searchBand}>
        <form className={styles.searchForm} onSubmit={handleSubmit}>
          <label htmlFor="ra-auto-query">关键词 / 类目</label>
          <div className={styles.searchRow}>
            <Search size={18} />
            <input
              id="ra-auto-query"
              maxLength={120}
              placeholder="例如：露营桌、办公收纳、庭院灯"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <button disabled={running || !query.trim()} type="submit">
              {running ? <Loader2 className={styles.spinIcon} size={17} /> : <Search size={17} />}
              <span>{running ? "后台分析中" : "开始自动分析"}</span>
            </button>
          </div>
          <p>
            默认每次提交 {DEFAULT_ASIN_LIMIT} 个 R-W 候选 ASIN 到后台队列，每个
            ASIN 优先抓取 {DEFAULT_SUPPLIER_LIMIT} 个一件代发/一件起批供应商，
            页面每 3 秒自动刷新结果。
          </p>
        </form>
        {runError ? (
          <div className={styles.inlineError}>
            <AlertTriangle size={16} />
            <span>{runError}</span>
          </div>
        ) : null}
      </section>

      <section className={styles.metricGrid} aria-label="R-A 自动利润指标">
        <Metric label="R-W 匹配产品" value={formatCount(summary.matched)} />
        <Metric label="供应商候选报价" value={formatCount(summary.offers)} />
        <Metric label="已抓到成本" value={formatCount(summary.priced)} />
        <Metric label="利润通过" value={formatCount(summary.passed)} />
      </section>

      {result ? (
        <JobProgressPanel result={result} />
      ) : null}

      {result?.warnings.length ? (
        <section className={styles.noticeBand}>
          <AlertTriangle size={18} />
          <div>
            <strong>本次任务提示</strong>
            <span>{result.warnings[0]}</span>
          </div>
        </section>
      ) : null}

      <section className={styles.sectionBand}>
        <div className={styles.sectionHeader}>
          <div>
            <span className={styles.kicker}>结果</span>
            <h3>利润测算结果</h3>
          </div>
          <span className={styles.mutedBadge}>
            {result ? "本次自动任务" : "等待输入关键词/类目"}
          </span>
        </div>
        {result ? (
          <AutoResultTable result={result} />
        ) : (
          <SnapshotPreview snapshots={snapshots} />
        )}
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.metricCard}>
      <Database size={18} />
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function JobProgressPanel({ result }: { result: RaAutoProfitJobResult }) {
  const matched = result.counts.matched_products ?? 0;
  const processed = result.counts.processed_products ?? 0;
  const progress = matched > 0 ? Math.min(100, Math.round((processed / matched) * 100)) : 0;
  return (
    <section className={styles.progressBand}>
      <div className={styles.progressHeader}>
        <div>
          <span className={styles.kicker}>本次任务</span>
          <strong>{result.query}</strong>
        </div>
        <span className={styles.jobState} data-status={result.status}>
          {jobStatusLabel(result.status)}
        </span>
      </div>
      <div
        aria-label="R-A 自动分析进度"
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={progress}
        className={styles.progressTrack}
        role="progressbar"
      >
        <span style={{ width: `${progress}%` }} />
      </div>
      <div className={styles.progressStats}>
        <span>已处理 {formatCount(processed)} / {formatCount(matched)} 个产品</span>
        <span>供应商候选 {formatCount(result.counts.candidate_offers)}</span>
        <span>已抓到成本 {formatCount(result.counts.priced_offers)}</span>
        <span>利润快照 {formatCount(result.counts.profit_snapshots)}</span>
        <span>实时汇率 1 USD = {formatRate(result.exchange_rate.usd_cny)} CNY</span>
      </div>
      {result.exchange_rate.warning ? (
        <div className={styles.metaWarning}>{result.exchange_rate.warning}</div>
      ) : null}
    </section>
  );
}

function AutoResultTable({ result }: { result: RaAutoProfitJobResult }) {
  const items = result.items ?? [];
  if (items.length === 0) {
    if (
      result.counts.rw_empty_result ||
      (isTerminalStatus(result.status) && result.counts.matched_products === 0)
    ) {
      return <RwEmptyResultNotice result={result} />;
    }
    return <div className={styles.emptyLine}>正在等待 R-W 匹配产品进入利润测算。</div>;
  }

  return (
    <div className={styles.tableWrap}>
      <table className={styles.resultTable}>
        <thead>
          <tr>
            <th>图片</th>
            <th>ASIN</th>
            <th>关键词</th>
            <th>中文产品名</th>
            <th>产品信息</th>
            <th>供应商成本</th>
            <th>毛利润</th>
            <th>利润率</th>
            <th>供应商链接</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={`${item.asin ?? "unknown"}-${item.supplier_url ?? index}`}>
              <td>
                <ProductImage
                  asin={item.asin}
                  candidates={item.image_candidates}
                  src={item.image_url}
                  title={item.title_zh || item.title}
                />
              </td>
              <td>
                <AsinTag asin={item.asin} />
                <small>{statusLabel(item.status)}</small>
              </td>
              <td>
                <strong>{item.product_keyword || item.keyword}</strong>
                <span>{item.matched_source_query || item.category || "R-W 匹配"}</span>
                <span className={styles.relevanceTag} data-status={item.relevance_status}>
                  {relevanceLabel(item.relevance_status)}
                  {typeof item.relevance_score === "number" ? ` · ${item.relevance_score}` : ""}
                </span>
                {item.relevance_reason ? <small>{item.relevance_reason}</small> : null}
              </td>
              <td>
                <strong>{item.title_zh || "等待中文名"}</strong>
                <span>{item.category || "未标注类目"}</span>
              </td>
              <td>
                <strong>售价 {formatUsd(item.sell_price_usd)}</strong>
                <span>配送 {item.fulfillment_method || "未标注"}</span>
                <span>FBA {formatUsd(item.fba_fee_usd)}</span>
                <span>重量 {item.weight_label || formatWeight(item.package_weight_g)}</span>
                <span>尺寸 {item.dimensions_label || formatDimensions(item)}</span>
                {item.lithium_battery_warning ? (
                  <em className={styles.lithiumTag}>锂电提示</em>
                ) : null}
              </td>
              <td>
                <strong>{formatCny(item.unit_price_cny)}</strong>
                <span>运费 {formatCny(item.domestic_shipping_cny)}</span>
                <span>合计 {formatCny(item.supplier_total_cny)}</span>
                {item.one_piece_hint || item.moq === 1 ? (
                  <em className={styles.onePieceTag}>一件优先</em>
                ) : item.moq ? (
                  <em className={styles.moqTag}>MOQ {item.moq}</em>
                ) : null}
              </td>
              <td>
                <strong>{formatUsd(item.gross_profit_usd)}</strong>
                <span>{formatCny(item.gross_profit_cny)}</span>
              </td>
              <td>
                <span className={styles.marginTag} data-verdict={item.verdict}>
                  {formatPercent(item.gross_margin)}
                </span>
                {item.warnings[0] ? <small>{item.warnings[0]}</small> : null}
                {item.blocked_reasons[0] ? (
                  <small>{item.blocked_reasons[0]}</small>
                ) : null}
              </td>
              <td>
                {supplierOptions(item).length ? (
                  <div className={styles.supplierList}>
                    {supplierOptions(item).map((supplier, supplierIndex) => (
                      <div
                        className={styles.supplierOption}
                        key={`${supplier.supplier_detail_url ?? supplier.supplier_url ?? "supplier"}-${supplierIndex}`}
                      >
                        <a
                          href={supplier.supplier_detail_url ?? supplier.supplier_url ?? "#"}
                          rel="noreferrer"
                          target="_blank"
                        >
                          <ExternalLink size={15} />
                          <span>
                            {supplierPlatformLabel(supplier)} 详情页 {supplierIndex + 1}
                            {supplier.supplier_total_cny
                              ? ` · ${formatCny(supplier.supplier_total_cny)}`
                              : ""}
                            {supplier.one_piece_hint || supplier.moq === 1 ? " · 一件" : ""}
                          </span>
                        </a>
                        {supplier.supplier_search_url ? (
                          <a
                            href={supplier.supplier_search_url}
                            rel="noreferrer"
                            target="_blank"
                          >
                            <Search size={15} />
                            <span>{supplierPlatformLabel(supplier)} 平台搜索页</span>
                          </a>
                        ) : null}
                        <SupplierRiskTags supplier={supplier} />
                      </div>
                    ))}
                  </div>
                ) : (
                  <span>未找到详情页</span>
                )}
                <SupplierSearchPages pages={item.supplier_search_pages} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RwEmptyResultNotice({ result }: { result: RaAutoProfitJobResult }) {
  const reason =
    result.counts.empty_reason ||
    `R-W 仓库中暂无“${result.query || "该关键词/类目"}”相关产品。`;
  const recommendation =
    result.counts.empty_recommendation ||
    "请先到 R-W 仓库的类目设置中选择相关类目，等待 Keepa 自动抓取后再回到 R-A 重新分析。";

  return (
    <div className={styles.emptyActionPanel}>
      <AlertTriangle size={20} />
      <div>
        <strong>{reason}</strong>
        <span>{recommendation}</span>
        <div className={styles.emptyActions}>
          <a href="/r-w/products">查看 R-W 产品库</a>
          <a href="/r-w/dashboard">进入 R-W 类目设置</a>
        </div>
      </div>
    </div>
  );
}

function SnapshotPreview({ snapshots }: { snapshots: RaProfitSnapshot[] }) {
  if (snapshots.length === 0) {
    return <div className={styles.emptyLine}>暂无利润结果。输入关键词或类目后开始。</div>;
  }
  return (
    <div className={styles.tableWrap}>
      <table className={styles.resultTable}>
        <thead>
          <tr>
            <th>图片</th>
            <th>ASIN</th>
            <th>关键词</th>
            <th>中文产品名</th>
            <th>供应商成本</th>
            <th>毛利润</th>
            <th>利润率</th>
            <th>供应商链接</th>
          </tr>
        </thead>
        <tbody>
          {snapshots.slice(0, 20).map((snapshot) => (
            <tr key={snapshot.snapshot_id}>
              <td>
                <ProductImage
                  asin={snapshot.asin}
                  candidates={snapshot.image_candidates}
                  src={snapshot.image_url}
                  title={snapshot.title_zh || snapshot.title}
                />
              </td>
              <td>
                <AsinTag asin={snapshot.asin} />
                <small>{verdictLabel(snapshot.verdict)}</small>
              </td>
              <td>
                <strong>历史快照</strong>
                <span>{snapshot.category || "R-W 产品库"}</span>
              </td>
              <td>
                <strong>{snapshot.title_zh || snapshot.title || "未命名产品"}</strong>
                <span>{snapshot.category || "未标注类目"}</span>
              </td>
              <td>
                <strong>{formatCny(snapshot.supplier.unit_price_cny)}</strong>
                <span>运费 {formatCny(snapshot.supplier.domestic_shipping_cny)}</span>
              </td>
              <td>
                <strong>{formatUsd(snapshot.gross_profit_usd)}</strong>
                <span>{formatCny(snapshot.gross_profit_cny)}</span>
              </td>
              <td>
                <span className={styles.marginTag} data-verdict={snapshot.verdict}>
                  {formatPercent(snapshot.gross_margin)}
                </span>
              </td>
              <td>
                {snapshot.supplier.supplier_url ? (
                  <div className={styles.supplierList}>
                    <a
                      href={
                        snapshot.supplier.supplier_detail_url ??
                        snapshot.supplier.supplier_url
                      }
                      rel="noreferrer"
                      target="_blank"
                    >
                      <ExternalLink size={15} />
                      {supplierPlatformLabel(snapshot.supplier)} 详情页
                    </a>
                    {snapshot.supplier.supplier_search_url ? (
                      <a
                        href={snapshot.supplier.supplier_search_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        <Search size={15} />
                        {supplierPlatformLabel(snapshot.supplier)} 平台搜索页
                      </a>
                    ) : null}
                  </div>
                ) : (
                  <span>未记录</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProductImage({
  asin,
  candidates,
  src,
  title,
}: {
  asin?: string | null;
  candidates?: string[];
  src: string | null;
  title: string | null;
}) {
  const imageCandidates = useMemo(
    () => productImageCandidates({ asin, candidates, src }),
    [asin, candidates, src],
  );
  const [candidateIndex, setCandidateIndex] = useState(0);
  const currentSrc = imageCandidates[candidateIndex] ?? null;

  useEffect(() => {
    setCandidateIndex(0);
  }, [imageCandidates]);

  if (!currentSrc) {
    return <div className={styles.imagePlaceholder}>无图</div>;
  }
  return (
    <img
      alt={title || "产品图片"}
      className={styles.productImage}
      loading="lazy"
      src={currentSrc}
      onError={() => setCandidateIndex((current) => current + 1)}
    />
  );
}

function AsinTag({ asin }: { asin: string | null }) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "manual">("idle");

  if (!asin) {
    return <span className={styles.asinTag}>未记录</span>;
  }
  const asinValue = asin;

  async function handleCopy() {
    let copiedSuccessfully = false;
    try {
      if (window.isSecureContext && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(asinValue);
        copiedSuccessfully = true;
      }
    } catch {
      copiedSuccessfully = fallbackCopyText(asinValue);
    }
    if (!copiedSuccessfully) {
      copiedSuccessfully = fallbackCopyText(asinValue);
    }
    if (!copiedSuccessfully) {
      window.prompt("复制 ASIN", asinValue);
      setCopyState("manual");
      window.setTimeout(() => setCopyState("idle"), 2200);
      return;
    }
    setCopyState("copied");
    if (copiedSuccessfully) {
      window.setTimeout(() => setCopyState("idle"), 1400);
    }
  }

  return (
    <button
      className={styles.asinTag}
      data-copied={copyState === "copied" ? "true" : "false"}
      title={copyState === "copied" ? "ASIN 已复制" : "复制 ASIN"}
      type="button"
      onClick={() => void handleCopy()}
    >
      <span>{asinValue}</span>
      <Copy size={13} />
      {copyState === "manual" ? <em>手动复制</em> : null}
    </button>
  );
}

function fallbackCopyText(value: string) {
  if (typeof document === "undefined") {
    return false;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(textarea);
  }
}

function supplierOptions(item: RaAutoProfitItem) {
  const fromList = (item.suppliers ?? []).filter(
    (supplier) => typeof supplier.supplier_url === "string" && supplier.supplier_url.length > 0,
  );
  if (fromList.length) {
    return fromList.slice(0, 5);
  }
  if (!item.supplier_url) {
    return [];
  }
  return [
    {
      supplier_name: item.supplier_name,
      supplier_url: item.supplier_url,
      supplier_platform: item.supplier_platform,
      supplier_platform_label: item.supplier_platform_label,
      supplier_url_type: item.supplier_url_type,
      supplier_detail_url: item.supplier_detail_url || item.supplier_url,
      supplier_search_url: item.supplier_search_url,
      unit_price_cny: item.unit_price_cny,
      domestic_shipping_cny: item.domestic_shipping_cny,
      supplier_total_cny: item.supplier_total_cny,
      moq: item.moq,
      one_piece_hint: item.one_piece_hint,
      supplier_alignment: item.supplier_alignment,
    },
  ];
}

function SupplierSearchPages({ pages }: { pages?: RaAutoProfitItem["supplier_search_pages"] }) {
  const visiblePages = (pages ?? []).filter((page) => page.search_url).slice(0, 8);
  if (!visiblePages.length) {
    return null;
  }
  return (
    <div className={styles.searchPageList}>
      <strong>平台搜索页</strong>
      {visiblePages.map((page, index) => (
        <a
          href={page.search_url ?? "#"}
          key={`${page.platform ?? "platform"}-${page.search_url ?? index}`}
          rel="noreferrer"
          target="_blank"
        >
          <Search size={14} />
          <span>
            {page.platform_label || supplierPlatformLabel({ supplier_platform: page.platform })}
            {typeof page.result_count === "number" ? ` · ${page.result_count} 条` : ""}
          </span>
        </a>
      ))}
    </div>
  );
}

function SupplierRiskTags({
  supplier,
}: {
  supplier: NonNullable<RaAutoProfitItem["suppliers"]>[number];
}) {
  const alignment = supplier.supplier_alignment;
  if (!alignment) {
    return null;
  }
  const quantityStatus = alignment.quantity?.status;
  const dimensionStatus = alignment.dimensions?.status;
  return (
    <div className={styles.supplierTags}>
      <span data-status={alignment.match_status || "review"}>
        {alignmentStatusLabel(alignment.match_status)}
        {typeof alignment.match_score === "number" ? ` · ${alignment.match_score}` : ""}
      </span>
      {quantityStatus && quantityStatus !== "not_required" ? (
        <span data-status={quantityStatus === "aligned" ? "match" : "review"}>
          数量{quantityStatus === "aligned" ? "已对齐" : "待确认"}
        </span>
      ) : null}
      {dimensionStatus && dimensionStatus !== "not_required" ? (
        <span data-status={dimensionStatus === "aligned" ? "match" : "review"}>
          尺寸{dimensionStatus === "aligned" ? "已对齐" : "待确认"}
        </span>
      ) : null}
      {alignment.match_reason ? <small>{alignment.match_reason}</small> : null}
    </div>
  );
}

function supplierPlatformLabel(supplier: {
  supplier_platform?: string | null;
  supplier_platform_label?: string | null;
}) {
  if (supplier.supplier_platform_label) {
    return supplier.supplier_platform_label;
  }
  if (supplier.supplier_platform === "pdd") {
    return "拼多多";
  }
  if (supplier.supplier_platform === "taobao") {
    return "淘宝/天猫";
  }
  if (supplier.supplier_platform === "jd") {
    return "京东";
  }
  return "1688";
}

function alignmentStatusLabel(value: string | null | undefined) {
  if (value === "match") {
    return "匹配通过";
  }
  if (value === "mismatch") {
    return "匹配拒绝";
  }
  if (value === "review") {
    return "需确认";
  }
  return "匹配待判定";
}

function productImageCandidates({
  asin,
  candidates,
  src,
}: {
  asin?: string | null;
  candidates?: string[];
  src: string | null;
}) {
  const cleanedAsin = asin?.trim().toUpperCase() ?? "";
  const output = [
    ...(candidates ?? []),
    src,
    src?.replace(
      "https://images-na.ssl-images-amazon.com/images/I/",
      "https://m.media-amazon.com/images/I/",
    ),
    src?.replace(
      "https://images-na.ssl-images-amazon.com/images/P/",
      "https://m.media-amazon.com/images/P/",
    )?.replace("._SCLZZZZZZZ_", "._SL160_"),
  ];
  return output.filter(
    (candidate, index): candidate is string =>
      typeof candidate === "string" &&
      !isAsinFallbackImage(candidate, cleanedAsin) &&
      output.indexOf(candidate) === index,
  );
}

function isAsinFallbackImage(candidate: string, asin: string) {
  if (!asin) {
    return false;
  }
  const upper = candidate.toUpperCase();
  return upper.includes(`/IMAGES/P/${asin}.01.`);
}

function formatCount(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "读取中";
  }
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatUsd(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "待计算";
  }
  return `$${value.toFixed(2)}`;
}

function formatCny(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "待获取";
  }
  return `￥${value.toFixed(2)}`;
}

function formatWeight(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "未标注";
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)} kg`;
  }
  return `${value.toFixed(0)} g`;
}

function formatDimensions(item: RaAutoProfitItem) {
  const values = [
    item.package_length_mm,
    item.package_width_mm,
    item.package_height_mm,
  ];
  if (values.some((value) => typeof value !== "number" || !Number.isFinite(value))) {
    return "未标注";
  }
  return values.map((value) => `${((value ?? 0) / 10).toFixed(1)}`).join(" x ") + " cm";
}

function formatPercent(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "待计算";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function statusLabel(value: string | null | undefined) {
  if (value === "profit_calculated") {
    return "已计算";
  }
  if (value === "cost_pending") {
    return "待成本";
  }
  if (value === "supplier_not_found") {
    return "未找到供应商";
  }
  if (value === "failed") {
    return "任务失败";
  }
  return "处理中";
}

function relevanceLabel(value: string | null | undefined) {
  if (value === "exact_match") {
    return "主体匹配";
  }
  if (value === "variant_match") {
    return "变体匹配";
  }
  if (value === "accessory_only") {
    return "仅配件";
  }
  if (value === "consumable_only") {
    return "仅耗材";
  }
  if (value === "replacement_part_only") {
    return "替换件";
  }
  if (value === "unrelated") {
    return "不相关";
  }
  return "相关性待判定";
}

function jobStatusLabel(value: string | null | undefined) {
  if (value === "queued") {
    return "已排队";
  }
  if (value === "running") {
    return "运行中";
  }
  if (value === "completed") {
    return "已完成";
  }
  if (value === "partial") {
    return "部分完成";
  }
  if (value === "failed") {
    return "任务失败";
  }
  return value || "等待中";
}

function isTerminalStatus(value: string | null | undefined) {
  return value === "completed" || value === "partial" || value === "failed";
}

function formatRate(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "读取中";
  }
  return value.toFixed(4);
}

function verdictLabel(value: string | null | undefined) {
  if (value === "pass") {
    return "利润通过";
  }
  if (value === "reject") {
    return "利润不足";
  }
  if (value === "blocked") {
    return "缺字段";
  }
  return "待计算";
}
