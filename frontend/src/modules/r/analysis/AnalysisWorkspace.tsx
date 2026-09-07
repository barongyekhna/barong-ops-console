"use client";

import {
  AlertTriangle,
  Copy,
  Database,
  ExternalLink,
  Search,
} from "lucide-react";
import {
  Fragment,
  type FormEvent,
  useEffect,
  useMemo,
  useState,
  type MouseEvent,
} from "react";

import {
  createRaAutoProfitJob,
  getRaAutoProfitJob,
  getRaFrameworkStatus,
  getRaJobStatus,
  getLatestRaAutoProfitJob,
  getRaProfitSnapshots,
} from "@/modules/r/analysis/api";
import type {
  RaAutoProfitJobItemsQuery,
  RaAutoProfitItem,
  RaAutoProfitJobResult,
  RaFrameworkStatus,
  RaProfitSnapshot,
} from "@/modules/r/analysis/types";

import { RadarScan } from "@/modules/r/analysis/RadarScan";
import { CruiseSwitch } from "./CruiseSwitch";

import styles from "./AnalysisWorkspace.module.css";

const DEFAULT_ASIN_LIMIT = 20;
const DEFAULT_SUPPLIER_LIMIT = 5;
const RESULT_PAGE_SIZE = 50;
const POLL_INTERVAL_MS = 5_000;
const POLL_BACKOFF_MAX_MS = 30_000;
const ITEMS_REFRESH_MS = 30_000;
const DEFAULT_ITEMS_QUERY: RaAutoProfitJobItemsQuery = {
  item_page: 1,
  item_page_size: RESULT_PAGE_SIZE,
  item_sort: "created_at",
  item_sort_direction: "desc",
  item_verdict: "all",
};

export function AnalysisWorkspace() {
  const [status, setStatus] = useState<RaFrameworkStatus | null>(null);
  const [snapshots, setSnapshots] = useState<RaProfitSnapshot[]>([]);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<RaAutoProfitJobResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [itemsQuery, setItemsQuery] = useState<RaAutoProfitJobItemsQuery>(
    DEFAULT_ITEMS_QUERY,
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      getRaFrameworkStatus(),
      getRaProfitSnapshots(),
      getLatestRaAutoProfitJob(DEFAULT_ITEMS_QUERY).catch(() => null),
    ])
      .then(([frameworkStatus, snapshotPayload, latestJob]) => {
        if (cancelled) {
          return;
        }
        setStatus(frameworkStatus);
        setSnapshots(snapshotPayload.items);
        if (latestJob) {
          setResult(latestJob);
          setRunning(!isTerminalStatus(latestJob.status));
        }
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

  // 轻量状态轮询：只拉 status + counts（毫秒级查询），带错误退避。
  useEffect(() => {
    if (!result?.run_id || isTerminalStatus(result.status)) {
      return undefined;
    }

    let cancelled = false;
    let timer: number | undefined;
    let errorStreak = 0;
    const runId = result.run_id;

    const tick = async () => {
      try {
        const statusPayload = await getRaJobStatus(runId);
        if (cancelled) {
          return;
        }
        errorStreak = 0;
        setRunError(null);
        setResult((prev) =>
          prev && prev.run_id === statusPayload.run_id
            ? {
                ...prev,
                status: statusPayload.status,
                counts: { ...prev.counts, ...statusPayload.counts },
                warnings: statusPayload.warnings ?? prev.warnings,
                finished_at: statusPayload.finished_at ?? prev.finished_at,
              }
            : prev,
        );
        setRunning(!isTerminalStatus(statusPayload.status));
      } catch (requestError) {
        if (cancelled) {
          return;
        }
        errorStreak += 1;
        setRunError(
          requestError instanceof Error
            ? requestError.message
            : "读取后台任务进度失败。",
        );
      }
      if (!cancelled) {
        const delay = Math.min(
          POLL_INTERVAL_MS * 2 ** Math.min(errorStreak, 3),
          POLL_BACKOFF_MAX_MS,
        );
        timer = window.setTimeout(() => {
          void tick();
        }, delay);
      }
    };

    timer = window.setTimeout(() => {
      void tick();
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [result?.run_id, result?.status]);

  // 明细列表刷新：翻页/筛选变化、状态到达终态时立即拉；运行中每 15 秒节流刷新一次。
  useEffect(() => {
    if (!result?.run_id) {
      return undefined;
    }

    let cancelled = false;
    const runId = result.run_id;
    const fetchItems = async () => {
      try {
        const payload = await getRaAutoProfitJob(runId, itemsQuery);
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

    void fetchItems();
    if (isTerminalStatus(result.status)) {
      return () => {
        cancelled = true;
      };
    }

    const timer = window.setInterval(() => {
      void fetchItems();
    }, ITEMS_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [itemsQuery, result?.run_id, result?.status]);

  const summary = useMemo(() => {
    if (!result) {
      return {
        matched: status?.candidate_source.ra_eligible ?? null,
        offers: snapshots.length,
        priced: snapshots.filter((snapshot) => snapshot.gross_margin !== null).length,
        passed: snapshots.filter((snapshot) => snapshot.verdict === "pass").length,
        aiPassed: null,
      };
    }
    return {
      matched: result.counts.matched_products,
      offers: result.counts.candidate_offers,
      priced: result.counts.priced_offers,
      passed: result.counts.profit_pass,
      aiPassed: result.counts.ai_pass ?? result.ai_selection?.counts.ai_pass ?? 0,
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
      setItemsQuery(DEFAULT_ITEMS_QUERY);
      const payload = await createRaAutoProfitJob({
        asin_limit: DEFAULT_ASIN_LIMIT,
        query: cleaned,
        run_ai_chain: true,
        selection_channel: "both",
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
      <CruiseSwitch />
      <RadarScan
        running={running}
        query={query}
        onQueryChange={setQuery}
        onSubmit={handleSubmit}
        counts={{
          matched: summary.matched,
          processed: result?.counts.processed_products ?? null,
          pass: summary.passed,
          aiPass: summary.aiPassed,
        }}
        statusText={result ? jobStatusLabel(result.status) : null}
        error={error}
        runError={runError}
      />

      <section className={styles.metricGrid} aria-label="R-A 自动利润指标">
        <Metric label="R-W 匹配产品" value={formatCount(summary.matched)} />
        <Metric label="供应商候选报价" value={formatCount(summary.offers)} />
        <Metric label="已抓到成本" value={formatCount(summary.priced)} />
        <Metric label="利润通过" value={formatCount(summary.passed)} />
        <Metric label="AI 通过" value={formatCount(summary.aiPassed)} />
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
          <AutoResultTable
            itemsQuery={itemsQuery}
            result={result}
            onItemsQueryChange={setItemsQuery}
          />
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
  const selected = result.counts.selected_products ?? 0;
  const processed = result.counts.processed_products ?? 0;
  const targetPass = result.counts.target_profit_pass ?? 10;
  const profitPass = result.counts.profit_pass ?? 0;
  const progress = targetPass > 0 ? Math.min(100, Math.round((profitPass / targetPass) * 100)) : 0;
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
        <span>利润通过 {formatCount(profitPass)} / {formatCount(targetPass)}</span>
        <span>R-W 已匹配 {formatCount(matched)}</span>
        <span>已选取 {formatCount(selected)}</span>
        <span>已处理 {formatCount(processed)}</span>
        <span>供应商候选 {formatCount(result.counts.candidate_offers)}</span>
        <span>已抓到成本 {formatCount(result.counts.priced_offers)}</span>
        <span>利润快照 {formatCount(result.counts.profit_snapshots)}</span>
        {result.counts.profit_quantity_pending ? (
          <span>数量待确认 {formatCount(result.counts.profit_quantity_pending)}</span>
        ) : null}
        <span>AI 决策 {formatCount(result.counts.final_decisions ?? result.ai_selection?.counts.final_decisions ?? 0)}</span>
        <span>AI 通过 {formatCount(result.counts.ai_pass ?? result.ai_selection?.counts.ai_pass ?? 0)}</span>
        <span>实时汇率 1 USD = {formatRate(result.exchange_rate.usd_cny)} CNY</span>
      </div>
      {result.exchange_rate.warning ? (
        <div className={styles.metaWarning}>{result.exchange_rate.warning}</div>
      ) : null}
    </section>
  );
}

function AutoResultTable({
  itemsQuery,
  onItemsQueryChange,
  result,
}: {
  itemsQuery: RaAutoProfitJobItemsQuery;
  onItemsQueryChange: (query: RaAutoProfitJobItemsQuery) => void;
  result: RaAutoProfitJobResult;
}) {
  const items = result.items ?? [];
  const pageInfo = result.items_page ?? {
    page: itemsQuery.item_page ?? 1,
    page_size: RESULT_PAGE_SIZE,
    total_items: items.length,
    total_pages: 1,
    has_previous: false,
    has_next: false,
    search: itemsQuery.item_search ?? "",
    category: itemsQuery.item_category ?? "",
    verdict: itemsQuery.item_verdict ?? "all",
    sort: itemsQuery.item_sort ?? "created_at",
    sort_direction: itemsQuery.item_sort_direction ?? "desc",
  };
  const minMargin = result.formula.default_min_gross_margin;
  const sortValue =
    pageInfo.sort === "gross_margin"
      ? pageInfo.sort_direction === "asc"
        ? "margin_asc"
        : "margin_desc"
      : "created_desc";
  const itemSections = useMemo(() => groupAutoProfitItems(items), [items]);

  function updateQuery(partial: RaAutoProfitJobItemsQuery) {
    onItemsQueryChange({
      ...itemsQuery,
      item_page_size: RESULT_PAGE_SIZE,
      ...partial,
    });
  }

  if (items.length === 0) {
    if (
      pageInfo.total_items === 0 &&
      (pageInfo.search || pageInfo.category || pageInfo.verdict !== "all") &&
      (result.counts.candidate_products ?? 0) > 0
    ) {
      return (
        <>
          <ResultTableControls
            itemCount={items.length}
            pageInfo={pageInfo}
            searchValue={itemsQuery.item_search ?? ""}
            categoryValue={itemsQuery.item_category ?? ""}
            verdictValue={itemsQuery.item_verdict ?? "all"}
            sortValue={sortValue}
            onUpdate={updateQuery}
          />
          <div className={styles.emptyLine}>没有找到符合当前筛选条件的利润测算结果。</div>
        </>
      );
    }
    if (
      result.counts.rw_empty_result ||
      (isTerminalStatus(result.status) && result.counts.matched_products === 0)
    ) {
      return <RwEmptyResultNotice result={result} />;
    }
    return <div className={styles.emptyLine}>正在等待 R-W 匹配产品进入利润测算。</div>;
  }

  return (
    <>
      <ResultTableControls
        categoryValue={itemsQuery.item_category ?? ""}
        itemCount={items.length}
        pageInfo={pageInfo}
        searchValue={itemsQuery.item_search ?? ""}
        sortValue={sortValue}
        verdictValue={itemsQuery.item_verdict ?? "all"}
        onUpdate={updateQuery}
      />
      <div className={styles.tableWrap}>
        <table className={styles.resultTable}>
          <colgroup>
            <col className={styles.colImage} />
            <col className={styles.colAsin} />
            <col className={styles.colKeyword} />
            <col className={styles.colProduct} />
            <col className={styles.colAmazon} />
            <col className={styles.colProfit} />
            <col className={styles.colMargin} />
            <col className={styles.colSupplier} />
          </colgroup>
          <thead>
            <tr>
              <th>图</th>
              <th>ASIN</th>
              <th>关键词</th>
              <th>产品 / 销量</th>
              <th>亚马逊</th>
              <th>成本 / 毛利</th>
              <th>利润率 ≥ {formatPercent(minMargin)}</th>
              <th>1688 供应商</th>
            </tr>
          </thead>
          <tbody>
            {itemSections.map((section) => (
              <Fragment key={section.key}>
                <tr className={styles.resultSectionRow} data-section={section.key}>
                  <td colSpan={8}>
                    <div className={styles.resultSectionTitle}>
                      <strong>{section.title}</strong>
                      <span>{section.description}</span>
                      <em>{formatCount(section.items.length)} 条</em>
                    </div>
                  </td>
                </tr>
                {section.items.map(({ item, index }) => (
                  <AutoResultRow
                    item={item}
                    key={`${item.asin ?? "unknown"}-${item.snapshot_id ?? item.supplier_url ?? index}`}
                  />
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <ResultPagination pageInfo={pageInfo} onUpdate={updateQuery} />
    </>
  );
}

function AutoResultRow({ item }: { item: RaAutoProfitItem }) {
  return (
    <tr>
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
        <small>{verdictLabel(item.verdict)}</small>
      </td>
      <td>
        <KeywordTag keyword={item.product_keyword || item.keyword} />
        <span>{item.matched_source_query || item.category || "R-W 匹配"}</span>
        <span className={styles.relevanceTag} data-status={item.relevance_status}>
          {relevanceLabel(item.relevance_status)}
          {typeof item.relevance_score === "number" ? ` · ${item.relevance_score}` : ""}
        </span>
      </td>
      <td>
        <strong>{item.title_zh || item.title || "未记录标题"}</strong>
        <ProductPackBadge item={item} />
        <span className={styles.compactText}>
          {item.title_zh ? item.title || "未记录英文标题" : "中文名待 R-A 选中后翻译"}
        </span>
        <span>{item.category || "未标注类目"}</span>
        <MonthlySalesBadge item={item} />
        <span>
          BSR {formatKnownCount(item.bsr)} · 评 {formatKnownCount(item.reviews)} · 市场卖家{" "}
          {formatKnownCount(item.market_seller_count_est ?? item.seller_count)}
        </span>
      </td>
      <td>
        <strong>{formatUsd(amazonPriceUsd(item))}</strong>
        <span>FBA {formatUsd(item.fba_fee_usd)}</span>
        <span>{item.fulfillment_method || "配送未标注"}</span>
        <span>{item.weight_label || formatWeight(item.package_weight_g)}</span>
        <span>{item.dimensions_label || formatDimensions(item)}</span>
        {item.lithium_battery_warning ? <em className={styles.lithiumTag}>锂电提示</em> : null}
      </td>
      <td>
        <strong>
          {formatCnyRange(
            item.supplier_total_cny_min,
            item.supplier_total_cny_max,
            item.supplier_total_cny,
          )}
        </strong>
        <span>
          产品 {formatCny(item.unit_price_cny)} · 运费 {formatCny(item.domestic_shipping_cny)}
        </span>
        <span>
          毛利{" "}
          {formatUsdRange(item.gross_profit_usd_min, item.gross_profit_usd_max, item.gross_profit_usd)}
        </span>
        <span>
          {formatCnyRange(item.gross_profit_cny_min, item.gross_profit_cny_max, item.gross_profit_cny)}
        </span>
      </td>
      <td>
        <span className={styles.marginTag} data-verdict={item.verdict}>
          {formatPercentRange(item.gross_margin_min, item.gross_margin_max, item.gross_margin)}
        </span>
        {item.warnings[0] ? <small>{item.warnings[0]}</small> : null}
        {item.blocked_reasons[0] ? <small>{item.blocked_reasons[0]}</small> : null}
        <AiSelectionCell selection={item.ai_selection} />
      </td>
      <td>
        <SupplierLinks item={item} />
        <SupplierSearchPages pages={item.supplier_search_pages} />
      </td>
    </tr>
  );
}

function groupAutoProfitItems(items: RaAutoProfitItem[]) {
  const sections = [
    {
      key: "profit-pass",
      title: "利润通过，等待 AI",
      description: "利润计算已达标，正在或即将进入 AI 选品链。",
      items: [] as Array<{ item: RaAutoProfitItem; index: number }>,
    },
    {
      key: "profit-reject",
      title: "利润不通过",
      description: "利润、供应商、数量或成本字段未达到 R-A 当前要求。",
      items: [] as Array<{ item: RaAutoProfitItem; index: number }>,
    },
    {
      key: "ai-pass",
      title: "AI 通过",
      description: "已通过 DeepSeek/GPT/Opus 选品链，可进入下一阶段。",
      items: [] as Array<{ item: RaAutoProfitItem; index: number }>,
    },
    {
      key: "ai-reject",
      title: "AI 不通过 / 复核",
      description: "AI 链判断不适合继续推进，或需要人工复核。",
      items: [] as Array<{ item: RaAutoProfitItem; index: number }>,
    },
  ];
  const byKey = new Map(sections.map((section) => [section.key, section]));
  items.forEach((item, index) => {
    const aiVerdict = String(item.ai_selection?.verdict ?? "").toLowerCase();
    if (aiVerdict === "pass") {
      byKey.get("ai-pass")?.items.push({ item, index });
      return;
    }
    if (aiVerdict === "reject" || aiVerdict === "review") {
      byKey.get("ai-reject")?.items.push({ item, index });
      return;
    }
    if (item.verdict === "pass") {
      byKey.get("profit-pass")?.items.push({ item, index });
      return;
    }
    byKey.get("profit-reject")?.items.push({ item, index });
  });
  return sections.filter((section) => section.items.length > 0);
}

function ResultTableControls({
  categoryValue,
  itemCount,
  onUpdate,
  pageInfo,
  searchValue,
  sortValue,
  verdictValue,
}: {
  categoryValue: string;
  itemCount: number;
  onUpdate: (partial: RaAutoProfitJobItemsQuery) => void;
  pageInfo: NonNullable<RaAutoProfitJobResult["items_page"]>;
  searchValue: string;
  sortValue: string;
  verdictValue: string;
}) {
  function handleSortChange(value: string) {
    if (value === "margin_asc") {
      onUpdate({ item_page: 1, item_sort: "gross_margin", item_sort_direction: "asc" });
      return;
    }
    if (value === "margin_desc") {
      onUpdate({ item_page: 1, item_sort: "gross_margin", item_sort_direction: "desc" });
      return;
    }
    onUpdate({ item_page: 1, item_sort: "created_at", item_sort_direction: "desc" });
  }

  return (
    <div className={styles.tableControls}>
      <label>
        <span>关键词 / ASIN</span>
        <input
          placeholder="模糊搜索 ASIN / 关键词 / 标题"
          value={searchValue}
          onChange={(event) => onUpdate({ item_page: 1, item_search: event.target.value })}
        />
      </label>
      <label>
        <span>类目搜索</span>
        <input
          placeholder="模糊搜索类目"
          value={categoryValue}
          onChange={(event) => onUpdate({ item_category: event.target.value, item_page: 1 })}
        />
      </label>
      <label>
        <span>利润状态</span>
        <select
          value={verdictValue}
          onChange={(event) => onUpdate({ item_page: 1, item_verdict: event.target.value })}
        >
          <option value="all">全部</option>
          <option value="profit_pass">利润通过</option>
          <option value="profit_reject">利润不通过</option>
          <option value="ai_pass">AI 通过</option>
          <option value="ai_reject">AI 不通过/复核</option>
          <option value="pending">待计算</option>
        </select>
      </label>
      <label>
        <span>利润率排序</span>
        <select value={sortValue} onChange={(event) => handleSortChange(event.target.value)}>
          <option value="created_desc">最新优先</option>
          <option value="margin_desc">利润率从高到低</option>
          <option value="margin_asc">利润率从低到高</option>
        </select>
      </label>
      <span className={styles.tableCount}>
        第 {formatCount(pageInfo.page)} / {formatCount(pageInfo.total_pages)} 页 · 本页{" "}
        {formatCount(itemCount)} 条 · 共{" "}
        {formatCount(pageInfo.total_items)} 条
      </span>
    </div>
  );
}

function ResultPagination({
  onUpdate,
  pageInfo,
}: {
  onUpdate: (partial: RaAutoProfitJobItemsQuery) => void;
  pageInfo: NonNullable<RaAutoProfitJobResult["items_page"]>;
}) {
  return (
    <div className={styles.paginationBar}>
      <button
        disabled={!pageInfo.has_previous}
        type="button"
        onClick={() => onUpdate({ item_page: Math.max(1, pageInfo.page - 1) })}
      >
        上一页
      </button>
      <span>
        每页 {formatCount(pageInfo.page_size)} 条，当前第 {formatCount(pageInfo.page)} 页
      </span>
      <button
        disabled={!pageInfo.has_next}
        type="button"
        onClick={() => onUpdate({ item_page: pageInfo.page + 1 })}
      >
        下一页
      </button>
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

function AiSelectionCell({ selection }: { selection?: RaAutoProfitItem["ai_selection"] }) {
  if (!selection) {
    return <span className={styles.aiPending}>等待 AI</span>;
  }
  const layers = aiLayerTimeline(selection);
  return (
    <div className={styles.aiCell}>
      <span className={styles.aiVerdict} data-verdict={selection.verdict}>
        {aiVerdictLabel(selection.verdict)} · {selection.final_score ?? "-"}分
      </span>
      <ChannelRouteBadges selection={selection} />
      {selection.decision_reason ? <small>{selection.decision_reason}</small> : null}
      <div className={styles.aiLayerList}>
        {layers.map((layer) => (
          <section
            className={styles.aiLayerCard}
            data-verdict={layer.verdict}
            key={`${selection.candidate_id}-${layer.layer}`}
          >
            <div className={styles.aiLayerCardHead}>
              <strong>{aiLayerLabel(layer.layer)}</strong>
              <span>{aiVerdictLabel(layer.verdict)} · {layer.score ?? "-"}分</span>
            </div>
            {layer.model_name ? <small>模型：{layer.model_name}</small> : null}
            <p>{layer.reason || "该层未返回明确理由。"}</p>
            {layer.advantages.length ? (
              <ul>
                {layer.advantages.slice(0, 2).map((item) => (
                  <li key={`adv-${layer.layer}-${item}`}>优势：{item}</li>
                ))}
              </ul>
            ) : null}
            {layer.risks.length ? (
              <ul>
                {layer.risks.slice(0, 2).map((item) => (
                  <li key={`risk-${layer.layer}-${item}`}>风险：{item}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ))}
      </div>
    </div>
  );
}

function ChannelRouteBadges({ selection }: { selection: NonNullable<RaAutoProfitItem["ai_selection"]> }) {
  const routes = selection.channel_routes?.routes ?? {};
  const routeItems = ["amazon", "dtc_ad", "dtc_seo"]
    .map((key) => ({ key, route: routes[key] }))
    .filter((item) => item.route);
  if (routeItems.length === 0) {
    return null;
  }
  return (
    <div className={styles.channelRoutes}>
      {routeItems.map(({ key, route }) => (
        <span
          data-primary={selection.primary_channel?.channel === key ? "true" : "false"}
          data-verdict={route?.verdict ?? "review"}
          key={key}
          title={channelRouteTitle(route)}
        >
          {route?.label || channelLabel(key)} · {route?.score ?? "-"}分
        </span>
      ))}
    </div>
  );
}

function channelRouteTitle(
  route:
    | {
        provider_mode?: string | null;
        reasons?: string[];
        risks?: string[];
      }
    | undefined,
) {
  if (!route) {
    return "";
  }
  const reasons = (route.reasons ?? []).slice(0, 2).join("；");
  const risks = (route.risks ?? []).slice(0, 2).join("；");
  return [route.provider_mode ? `来源：${route.provider_mode}` : "", reasons, risks]
    .filter(Boolean)
    .join("；");
}

function channelLabel(value: string) {
  if (value === "dtc_ad") {
    return "独立站广告";
  }
  if (value === "dtc_seo") {
    return "独立站 SEO";
  }
  if (value === "amazon") {
    return "亚马逊";
  }
  return value;
}

function aiLayerTimeline(selection: NonNullable<RaAutoProfitItem["ai_selection"]>) {
  const existing = new Map((selection.layers ?? []).map((layer) => [layer.layer, layer]));
  const deepseek = existing.get("deepseek");
  const gpt = existing.get("gpt");
  const output = [];
  for (const layerName of ["deepseek", "gpt", "opus"]) {
    const layer = existing.get(layerName);
    if (layer) {
      output.push(layer);
      continue;
    }
    let reason = "上一层未放行，本层按 R-A 漏斗规则未执行。";
    if (layerName === "gpt" && deepseek?.verdict === "reject") {
      reason = "DeepSeek 第一层已淘汰，GPT 第二层未执行。";
    }
    if (layerName === "opus") {
      if (deepseek?.verdict === "reject") {
        reason = "DeepSeek 第一层已淘汰，Opus 最终层未执行。";
      } else if (gpt?.verdict === "reject") {
        reason = "GPT 第二层已淘汰，Opus 最终层未执行。";
      }
    }
    output.push({
      layer: layerName,
      model_role: layerName,
      model_name: "",
      score: null,
      verdict: "skipped",
      reason,
      advantages: [],
      risks: [],
      created_at: null,
    });
  }
  return output;
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
            <th>亚马逊售价</th>
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
                <strong>{formatUsd(amazonPriceUsd(snapshot))}</strong>
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
  const [previewPosition, setPreviewPosition] = useState<{ left: number; top: number } | null>(
    null,
  );
  const currentSrc = imageCandidates[candidateIndex] ?? null;

  useEffect(() => {
    setCandidateIndex(0);
  }, [imageCandidates]);

  if (!currentSrc) {
    return <div className={styles.imagePlaceholder}>无图</div>;
  }
  function updatePreviewPosition(event: MouseEvent<HTMLElement>) {
    setPreviewPosition(imagePreviewPosition(event));
  }
  return (
    <span
      className={styles.imageZoomWrap}
      onMouseEnter={updatePreviewPosition}
      onMouseLeave={() => setPreviewPosition(null)}
      onMouseMove={updatePreviewPosition}
    >
      <img
        alt={title || "产品图片"}
        className={styles.productImage}
        loading="lazy"
        src={currentSrc}
        onError={() => {
          setCandidateIndex((current) => current + 1);
          setPreviewPosition(null);
        }}
      />
      {previewPosition ? (
        <span
          className={styles.imageZoomPreview}
          style={{ left: previewPosition.left, top: previewPosition.top }}
        >
          <img alt="" src={currentSrc} />
        </span>
      ) : null}
    </span>
  );
}

function imagePreviewPosition(event: MouseEvent<HTMLElement>) {
  const previewSize = 240;
  const gap = 18;
  const padding = 14;
  const viewportWidth = typeof window === "undefined" ? 1440 : window.innerWidth;
  const viewportHeight = typeof window === "undefined" ? 900 : window.innerHeight;
  let left = event.clientX + gap;
  let top = event.clientY + gap;
  if (left + previewSize + padding > viewportWidth) {
    left = event.clientX - previewSize - gap;
  }
  if (top + previewSize + padding > viewportHeight) {
    top = event.clientY - previewSize - gap;
  }
  return {
    left: Math.max(padding, left),
    top: Math.max(padding, top),
  };
}

function AsinTag({ asin }: { asin: string | null }) {
  if (!asin) {
    return <span className={styles.asinTag}>未记录</span>;
  }
  return <CopyToken className={styles.asinTag} label={asin} title="复制 ASIN" value={asin} />;
}

function KeywordTag({ keyword }: { keyword: string | null | undefined }) {
  const value = keyword?.trim();
  if (!value) {
    return <span>未记录关键词</span>;
  }
  return (
    <CopyToken
      className={`${styles.asinTag} ${styles.keywordCopyTag}`}
      label={value}
      title="复制关键词"
      value={value}
    />
  );
}

function CopyToken({
  className,
  label,
  title,
  value,
}: {
  className: string;
  label: string;
  title: string;
  value: string;
}) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "manual">("idle");

  async function handleCopy(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    const copiedSuccessfully = await copyText(value);
    if (!copiedSuccessfully) {
      window.prompt(title, value);
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
      className={className}
      data-copied={copyState === "copied" ? "true" : "false"}
      title={copyState === "copied" ? "已复制" : title}
      type="button"
      onClick={(event) => void handleCopy(event)}
    >
      <span>{label}</span>
      <Copy size={13} />
      {copyState === "copied" ? <em>已复制</em> : null}
      {copyState === "manual" ? <em>手动复制</em> : null}
    </button>
  );
}

function MonthlySalesBadge({ item }: { item: RaAutoProfitItem }) {
  return (
    <span className={styles.salesBadge} title={monthlySalesTitle(item)}>
      月销 {formatMonthlySales(item)}
    </span>
  );
}

async function copyText(value: string) {
  try {
    await navigator.clipboard?.writeText(value);
    return true;
  } catch {
    return fallbackCopyText(value);
  }
}

function fallbackCopyText(value: string) {
  if (typeof document === "undefined") {
    return false;
  }
  const input = document.createElement("input");
  input.value = value;
  input.setAttribute("readonly", "true");
  input.style.position = "fixed";
  input.style.left = "0";
  input.style.top = "0";
  input.style.width = "1px";
  input.style.height = "1px";
  input.style.opacity = "0";
  input.style.pointerEvents = "none";
  document.body.appendChild(input);
  input.focus({ preventScroll: true });
  input.select();
  input.setSelectionRange(0, input.value.length);
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(input);
  }
}

function SupplierLinks({ item }: { item: RaAutoProfitItem }) {
  const options = supplierOptions(item);
  if (!options.length) {
    return <span>未找到详情页</span>;
  }
  return (
    <div className={styles.supplierList}>
      {options.map((supplier, supplierIndex) => (
        <div
          className={styles.supplierOption}
          key={`${supplier.supplier_detail_url ?? supplier.supplier_url ?? "supplier"}-${supplierIndex}`}
        >
          <a
            href={supplier.supplier_detail_url ?? supplier.supplier_url ?? "#"}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalLink size={14} />
            <span>
              {supplierPlatformLabel(supplier)} {supplierIndex + 1}
              {supplier.is_lowest_price ? " · 最低价" : ""}
              {supplier.supplier_total_cny ? ` · ${formatCny(supplier.supplier_total_cny)}` : ""}
              {supplier.gross_margin !== null && supplier.gross_margin !== undefined
                ? ` · ${formatPercent(supplier.gross_margin)}`
                : ""}
            </span>
          </a>
          <span className={styles.supplierTitle}>
            {supplier.supplier_title || supplier.supplier_name || "1688 供应商"}
          </span>
          {supplier.one_piece_hint || supplier.moq === 1 ? (
            <em className={styles.onePieceTag}>一件</em>
          ) : supplier.moq ? (
            <em className={styles.moqTag}>MOQ {supplier.moq}</em>
          ) : null}
          <SupplierRiskTags supplier={supplier} />
        </div>
      ))}
    </div>
  );
}

function ProductPackBadge({ item }: { item: RaAutoProfitItem }) {
  const pack = productPackInfo(item);
  if (!pack) {
    return null;
  }
  return (
    <span
      className={styles.packTag}
      title={pack.reason || undefined}
      data-status={pack.status || "aligned"}
    >
      {pack.label}
      {pack.multiplier && pack.multiplier !== 1 ? ` · 成本x${formatMultiplier(pack.multiplier)}` : ""}
    </span>
  );
}

function productPackInfo(item: RaAutoProfitItem) {
  const fromItem = normalizePackInfo({
    label: item.pack_label,
    count: item.pack_quantity,
    supplierLabel: item.supplier_pack_label,
    multiplier: item.quantity_cost_multiplier,
    status: item.quantity_alignment_status,
    reason: item.quantity_alignment_reason,
  });
  if (fromItem) {
    return fromItem;
  }
  const alignments = [
    item.supplier_alignment,
    ...(item.suppliers ?? []).map((supplier) => supplier.supplier_alignment),
  ];
  for (const alignment of alignments) {
    const quantity = alignment?.quantity;
    const normalized = normalizePackInfo({
      label: quantity?.amazon_pack_label,
      count: quantity?.amazon_pack_count,
      supplierLabel: quantity?.supplier_pack_label,
      multiplier: quantity?.cost_multiplier ?? alignment?.cost_multiplier,
      status: quantity?.status,
      reason: quantity?.reason ?? alignment?.match_reason,
    });
    if (normalized) {
      return normalized;
    }
  }
  return null;
}

function normalizePackInfo({
  label,
  count,
  supplierLabel,
  multiplier,
  status,
  reason,
}: {
  label?: string | null;
  count?: number | null;
  supplierLabel?: string | null;
  multiplier?: number | null;
  status?: string | null;
  reason?: string | null;
}) {
  const cleanedLabel = String(label || "").trim();
  const numericCount = typeof count === "number" && Number.isFinite(count) ? count : null;
  const isPendingMulti = cleanedLabel.includes("待确认") || status === "needs_review";
  if ((!numericCount || numericCount <= 1) && !isPendingMulti) {
    return null;
  }
  const displayLabel =
    cleanedLabel || (numericCount && numericCount > 1 ? `${Math.round(numericCount)}件装` : "多件装待确认");
  const supplierText = supplierLabel ? `供应商 ${supplierLabel}` : "";
  const reasonText = [reason, supplierText].filter(Boolean).join("；");
  return {
    label: displayLabel,
    multiplier: typeof multiplier === "number" && Number.isFinite(multiplier) ? multiplier : null,
    status,
    reason: reasonText,
  };
}

function formatMultiplier(value: number) {
  if (!Number.isFinite(value)) {
    return "-";
  }
  return value.toFixed(2).replace(/\.?0+$/, "");
}

function supplierOptions(item: RaAutoProfitItem) {
  const fromList = (item.suppliers ?? []).filter(
    (supplier) => typeof supplier.supplier_url === "string" && supplier.supplier_url.length > 0,
  );
  if (fromList.length) {
    return fromList.slice(0, 3);
  }
  if (!item.supplier_url) {
    return [];
  }
  return [
    {
      supplier_name: item.supplier_name,
      supplier_title: null,
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
      gross_margin: item.gross_margin,
      gross_profit_usd: item.gross_profit_usd,
      gross_profit_cny: item.gross_profit_cny,
      verdict: item.verdict,
      is_lowest_price: true,
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
  const quantityLabel = [
    alignment.quantity?.amazon_pack_label,
    alignment.quantity?.supplier_pack_label ? `供应商${alignment.quantity.supplier_pack_label}` : null,
  ]
    .filter(Boolean)
    .join(" / ");
  return (
    <div className={styles.supplierTags}>
      <span data-status={alignment.match_status || "review"}>
        {alignmentStatusLabel(alignment.match_status)}
        {typeof alignment.match_score === "number" ? ` · ${alignment.match_score}` : ""}
      </span>
      {quantityStatus && quantityStatus !== "not_required" ? (
        <span data-status={quantityStatus === "aligned" ? "match" : "review"}>
          数量{quantityStatus === "aligned" ? "已对齐" : "待确认"}
          {quantityLabel ? ` · ${quantityLabel}` : ""}
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

function formatKnownCount(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "未记录";
  }
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatUsd(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "待计算";
  }
  return `$${value.toFixed(2)}`;
}

function amazonPriceUsd(
  value: Pick<RaAutoProfitItem, "amazon_price_usd" | "sell_price_usd"> |
    Pick<RaProfitSnapshot, "amazon_price_usd" | "sell_price_usd">,
) {
  return value.amazon_price_usd ?? value.sell_price_usd;
}

function formatCny(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "待获取";
  }
  return `￥${value.toFixed(2)}`;
}

function formatCnyRange(
  min: number | null | undefined,
  max: number | null | undefined,
  fallback: number | null | undefined,
) {
  if (typeof min === "number" && typeof max === "number" && Number.isFinite(min) && Number.isFinite(max)) {
    if (Math.abs(min - max) < 0.005) {
      return formatCny(min);
    }
    return `${formatCny(min)} - ${formatCny(max)}`;
  }
  return formatCny(fallback);
}

function formatUsdRange(
  min: number | null | undefined,
  max: number | null | undefined,
  fallback: number | null | undefined,
) {
  if (typeof min === "number" && typeof max === "number" && Number.isFinite(min) && Number.isFinite(max)) {
    if (Math.abs(min - max) < 0.005) {
      return formatUsd(min);
    }
    return `${formatUsd(min)} - ${formatUsd(max)}`;
  }
  return formatUsd(fallback);
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

function formatPercentRange(
  min: number | null | undefined,
  max: number | null | undefined,
  fallback: number | null | undefined,
) {
  if (typeof min === "number" && typeof max === "number" && Number.isFinite(min) && Number.isFinite(max)) {
    if (Math.abs(min - max) < 0.0005) {
      return formatPercent(min);
    }
    return `${formatPercent(min)} - ${formatPercent(max)}`;
  }
  return formatPercent(fallback);
}

function formatMonthlySales(item: Pick<
  RaAutoProfitItem,
  | "monthly_sales"
  | "monthly_sales_estimate"
  | "monthly_sales_estimate_min"
  | "monthly_sales_estimate_max"
  | "monthly_sales_confidence"
>) {
  if (typeof item.monthly_sales === "number" && Number.isFinite(item.monthly_sales)) {
    return `${formatKnownCount(item.monthly_sales)}（Keepa）`;
  }
  if (
    typeof item.monthly_sales_estimate_min === "number" &&
    typeof item.monthly_sales_estimate_max === "number"
  ) {
    return `${formatKnownCount(item.monthly_sales_estimate_min)}-${formatKnownCount(item.monthly_sales_estimate_max)}（估算）`;
  }
  if (typeof item.monthly_sales_estimate === "number" && Number.isFinite(item.monthly_sales_estimate)) {
    return `${formatKnownCount(item.monthly_sales_estimate)}（估算）`;
  }
  return "未记录";
}

function monthlySalesTitle(item: Pick<
  RaAutoProfitItem,
  | "monthly_sales"
  | "monthly_sales_estimate"
  | "monthly_sales_estimate_min"
  | "monthly_sales_estimate_max"
  | "monthly_sales_confidence"
  | "monthly_sales_source"
>) {
  const parts = [`月销量：${formatMonthlySales(item)}`];
  if (item.monthly_sales_source) {
    parts.push(`来源：${item.monthly_sales_source}`);
  }
  if (item.monthly_sales_confidence) {
    parts.push(`置信度：${item.monthly_sales_confidence}`);
  }
  return parts.join("；");
}

function itemMarginSortValue(item: RaAutoProfitItem) {
  const value = item.gross_margin_max ?? item.gross_margin ?? item.gross_margin_min;
  return typeof value === "number" && Number.isFinite(value) ? value : -999;
}

function itemVerdictFilter(item: RaAutoProfitItem) {
  if (item.verdict === "pass") {
    return "pass";
  }
  if (item.verdict === "reject" || item.verdict === "blocked") {
    return "reject";
  }
  return "pending";
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
  if (value === "paused") {
    return "已暂停（今日额度用完，明天自动继续）";
  }
  if (value === "cancelled") {
    return "已取消";
  }
  return value || "等待中";
}

function isTerminalStatus(value: string | null | undefined) {
  return (
    value === "completed" ||
    value === "partial" ||
    value === "failed" ||
    value === "cancelled" ||
    value === "paused"
  );
}

function formatRate(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "读取中";
  }
  return value.toFixed(4);
}

function aiVerdictLabel(value: string | null | undefined) {
  if (value === "pass") {
    return "AI通过";
  }
  if (value === "reject") {
    return "AI淘汰";
  }
  if (value === "review") {
    return "AI复核";
  }
  if (value === "skipped") {
    return "未执行";
  }
  return "AI等待";
}

function aiLayerLabel(value: string | null | undefined) {
  if (value === "deepseek") {
    return "DeepSeek";
  }
  if (value === "gpt") {
    return "GPT";
  }
  if (value === "opus") {
    return "Opus";
  }
  return value || "AI";
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
