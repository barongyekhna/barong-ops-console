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
  getRaFrameworkStatus,
  getRaProfitSnapshots,
  runRaAutoProfit,
} from "@/modules/r/analysis/api";
import type {
  RaAutoProfitItem,
  RaAutoProfitResult,
  RaFrameworkStatus,
  RaProfitSnapshot,
} from "@/modules/r/analysis/types";

import styles from "./AnalysisWorkspace.module.css";

const DEFAULT_ASIN_LIMIT = 1;
const DEFAULT_SUPPLIER_LIMIT = 3;

export function AnalysisWorkspace({ view }: { view: "dashboard" | "analysis" }) {
  const [status, setStatus] = useState<RaFrameworkStatus | null>(null);
  const [snapshots, setSnapshots] = useState<RaProfitSnapshot[]>([]);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<RaAutoProfitResult | null>(null);
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
      const payload = await runRaAutoProfit({
        asin_limit: DEFAULT_ASIN_LIMIT,
        query: cleaned,
        supplier_limit: DEFAULT_SUPPLIER_LIMIT,
      });
      setResult(payload);
      const snapshotPayload = await getRaProfitSnapshots();
      setSnapshots(snapshotPayload.items);
    } catch (requestError) {
      setRunError(
        requestError instanceof Error
          ? requestError.message
          : "自动利润分析失败。",
      );
    } finally {
      setRunning(false);
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
              <span>{running ? "自动分析中" : "开始自动分析"}</span>
            </button>
          </div>
          <p>
            默认每次匹配 {DEFAULT_ASIN_LIMIT} 个 R-W 候选 ASIN，每个 ASIN 优先抓取{" "}
            {DEFAULT_SUPPLIER_LIMIT} 个一件代发/一件起批 1688 供应商。
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
        <section className={styles.resultMetaBand}>
          <div>
            <span className={styles.kicker}>本次任务</span>
            <strong>{result.query}</strong>
          </div>
          <div>
            <span>实时汇率</span>
            <strong>
              1 USD = {result.exchange_rate.usd_cny.toFixed(4)} CNY
            </strong>
          </div>
          <div>
            <span>汇率来源</span>
            <strong>{result.exchange_rate.live ? "实时接口" : "备用汇率"}</strong>
          </div>
          {result.exchange_rate.warning ? (
            <div className={styles.metaWarning}>{result.exchange_rate.warning}</div>
          ) : null}
        </section>
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
            <th>1688 成本</th>
            <th>毛利润</th>
            <th>利润率</th>
            <th>1688 链接</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={`${item.asin ?? "unknown"}-${item.supplier_url ?? index}`}>
              <td>
                <ProductImage src={item.image_url} title={item.title_zh || item.title} />
              </td>
              <td>
                <AsinTag asin={item.asin} />
                <small>{statusLabel(item.status)}</small>
              </td>
              <td>
                <strong>{item.keyword}</strong>
                <span>{item.matched_source_query || item.category || "R-W 匹配"}</span>
              </td>
              <td>
                <strong>{item.title_zh || "等待中文名"}</strong>
                <span>{item.category || "未标注类目"}</span>
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
                {item.supplier_url ? (
                  <a href={item.supplier_url} rel="noreferrer" target="_blank">
                    <ExternalLink size={15} />
                    打开供应商
                  </a>
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
                <ProductImage src={snapshot.image_url} title={snapshot.title_zh || snapshot.title} />
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

function ProductImage({ src, title }: { src: string | null; title: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return <div className={styles.imagePlaceholder}>无图</div>;
  }
  return (
    <img
      alt={title || "产品图片"}
      className={styles.productImage}
      loading="lazy"
      src={src}
      onError={() => setFailed(true)}
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
