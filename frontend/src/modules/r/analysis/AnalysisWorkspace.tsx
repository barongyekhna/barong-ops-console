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
const DEFAULT_SUPPLIER_LIMIT = 3;
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

  const resultItems = result?.items ?? [];
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
            ASIN，再自动搜索 1688 供应商并按美国站公式计算毛利润。
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
            ASIN 优先抓取 {DEFAULT_SUPPLIER_LIMIT} 个一件代发/一件起批 1688
            供应商，页面每 3 秒自动刷新结果。
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
        <Metric label="1688 候选报价" value={formatCount(summary.offers)} />
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
          <AutoResultTable items={resultItems} />
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
        <span>1688 候选 {formatCount(result.counts.candidate_offers)}</span>
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

function AutoResultTable({ items }: { items: RaAutoProfitItem[] }) {
  if (items.length === 0) {
    return <div className={styles.emptyLine}>没有找到与关键词/类目匹配的 R-W 产品。</div>;
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
            <th>1688 成本</th>
            <th>毛利润</th>
            <th>利润率</th>
            <th>1688 供应商</th>
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
              </td>
              <td>
                <strong>{item.title_zh || "等待中文名"}</strong>
                <span>{item.category || "未标注类目"}</span>
              </td>
              <td>
                <strong>{formatUsd(item.sell_price_usd)}</strong>
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
                      <a
                        key={`${supplier.supplier_url ?? "supplier"}-${supplierIndex}`}
                        href={supplier.supplier_url ?? "#"}
                        rel="noreferrer"
                        target="_blank"
                      >
                        <ExternalLink size={15} />
                        <span>
                          供应商 {supplierIndex + 1}
                          {supplier.supplier_total_cny
                            ? ` · ${formatCny(supplier.supplier_total_cny)}`
                            : ""}
                          {supplier.one_piece_hint || supplier.moq === 1 ? " · 一件" : ""}
                        </span>
                      </a>
                    ))}
                  </div>
                ) : (
                  <span>未找到</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
            <th>1688 成本</th>
            <th>毛利润</th>
            <th>利润率</th>
            <th>1688 链接</th>
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
                  <a href={snapshot.supplier.supplier_url} rel="noreferrer" target="_blank">
                    <ExternalLink size={15} />
                    打开供应商
                  </a>
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
  if (!asin) {
    return <span className={styles.asinTag}>未记录</span>;
  }
  return (
    <button
      className={styles.asinTag}
      title="复制 ASIN"
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(asin);
      }}
    >
      <span>{asin}</span>
      <Copy size={13} />
    </button>
  );
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
      unit_price_cny: item.unit_price_cny,
      domestic_shipping_cny: item.domestic_shipping_cny,
      supplier_total_cny: item.supplier_total_cny,
      moq: item.moq,
      one_piece_hint: item.one_piece_hint,
    },
  ];
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
    cleanedAsin.length === 10
      ? `https://m.media-amazon.com/images/P/${cleanedAsin}.01._SL160_.jpg`
      : null,
    cleanedAsin.length === 10
      ? `https://images-na.ssl-images-amazon.com/images/P/${cleanedAsin}.01._SCLZZZZZZZ_.jpg`
      : null,
  ];
  return output.filter(
    (candidate, index): candidate is string =>
      Boolean(candidate) && output.indexOf(candidate) === index,
  );
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
