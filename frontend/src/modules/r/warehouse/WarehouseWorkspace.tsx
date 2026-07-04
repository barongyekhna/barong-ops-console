"use client";

import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Copy,
  Database,
  RefreshCw,
  Search,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  deleteRejectedRwProducts,
  getRwCategoryTree,
  getRwPipeline,
  getRwProductsWithFilters,
  getRwRules,
  getRwSettings,
  getRwStatus,
  saveRwCategoryTree,
  updateRwSettings,
} from "@/modules/r/warehouse/api";
import type {
  RwCategoryNode,
  RwCategoryTreeResponse,
  RwPipelineResponse,
  RwProduct,
  RwProductsResponse,
  RwRulesResponse,
  RwRuntimeSettings,
  RwSettingsResponse,
  RwStatus,
} from "@/modules/r/warehouse/types";

import styles from "./WarehouseWorkspace.module.css";

type WarehouseView = "dashboard" | "products" | "rules" | "pipeline" | "batch";

type WarehouseState = {
  products: RwProductsResponse | null;
  rules: RwRulesResponse | null;
  status: RwStatus | null;
  pipeline: RwPipelineResponse | null;
  settings: RwSettingsResponse | null;
  categoryTree: RwCategoryTreeResponse | null;
};

type CompleteWarehouseState = {
  products: RwProductsResponse;
  rules: RwRulesResponse | null;
  status: RwStatus;
  pipeline: RwPipelineResponse;
  settings: RwSettingsResponse | null;
  categoryTree: RwCategoryTreeResponse | null;
};

type ProductFilters = {
  q: string;
  category_id: string;
  state: "pass" | "reject" | "pending_review" | "";
  sort_by: "updated_at" | "skill_score";
  sort_order: "asc" | "desc";
};

type RwEndpointKey = keyof WarehouseState;

const tabs: Array<{ href: string; label: string; view: WarehouseView }> = [
  { href: "/r-w/dashboard", label: "总览", view: "dashboard" },
  { href: "/r-w/products", label: "产品库", view: "products" },
  { href: "/r-w/pipeline", label: "抓取流水线", view: "pipeline" },
  { href: "/r-w/batch-status", label: "批次状态", view: "batch" },
  { href: "/r-w/rules", label: "规则", view: "rules" },
];

const DEEPSEEK_DAILY_REPORT_KEY_PREFIX = "rw-deepseek-daily-report-date";

function currency(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    currency: "USD",
    maximumFractionDigits: 2,
    style: "currency",
  }).format(value);
}

function percent(value: number) {
  return `${Math.round(value * 1000) / 10}%`;
}

function stateLabel(value: string) {
  const labels: Record<string, string> = {
    ai1_passed: "初筛通过",
    ai1_rejected: "初筛剔除",
    discovered: "已发现",
    enriched: "已富化",
    rejected: "规则剔除",
    rule_prefilter: "规则预筛",
    deepseek_realtime: "实时初筛",
    rule_passed: "待初筛",
    discovery: "类目发现",
    deadline: "到时停止",
    backoff: "限流等待",
    blocked: "阻塞",
  };
  return labels[value] ?? value;
}

function decisionLabel(value: string) {
  const labels: Record<string, string> = {
    pass: "通过",
    pending_review: "待复核",
    reject: "剔除",
  };
  return labels[value] ?? value;
}

function fulfillmentLabel(value: string | null) {
  if (value === "FBA" || value === "FBM") {
    return value;
  }
  return "履约未知";
}

function modeLabel(value: string) {
  const labels: Record<string, string> = {
    production: "生产运行",
    production_blocked: "等待密钥",
  };
  return labels[value] ?? value;
}

function eventLabel(value: string) {
  const labels: Record<string, string> = {
    deepseek_prefilter: "DeepSeek 初筛",
    keepa_cycle: "Keepa 循环",
    keepa_discovery: "Keepa 类目发现",
    keepa_fetch: "Keepa 抓取",
  };
  return labels[value] ?? value;
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    active: "运行中",
    backoff: "限流等待",
    blocked: "阻塞",
    failed: "失败",
    idle: "空闲",
    processed: "已处理",
    queued: "已入队",
    stored: "已入库",
    stopped: "已停止",
  };
  return labels[value] ?? value;
}

function priceTrendLabel(value: string | null) {
  if (!value) {
    return "未知";
  }
  const labels: Record<string, string> = {
    declining: "下行",
    price_war: "价格战",
    rising: "上行",
    stable: "平稳",
  };
  return labels[value] ?? value;
}

function rejectReasonLabel(value: string | null, features: Record<string, unknown>) {
  const reasonLabels: Record<string, string> = {
    brand_dominance_filter: "品牌占比过高",
    compliance_redline_filter: "命中合规红线",
    margin_check: "缺少成本或净利率不足",
    margin_too_low: "净利率低于规则阈值",
    price_band_filter: "售价不在 25-70 美元区间",
    price_out_of_band: "售价不在 25-70 美元区间",
    price_trend_filter: "价格趋势持续下行",
    price_trend_declining: "价格趋势持续下行",
    review_wall_filter: "评论壁垒过高",
    review_wall_too_high: "评论壁垒过高",
    seller_count_filter: "卖家数量过多",
    competition_filter: "卖家数量过多",
    too_many_sellers: "卖家数量过多",
    brand_dominance: "品牌垄断风险过高",
    redline_category: "命中合规红线",
    too_heavy: "重量超过规则阈值",
    viral_unproven: "疑似短期爆款，缺少稳定需求证明",
  };
  if (value) {
    return value
      .split(",")
      .map((item) => reasonLabels[item.trim()] ?? item.trim())
      .filter(Boolean)
      .join("；");
  }
  const deepseekReason = features.deepseek_reason;
  if (typeof deepseekReason === "string" && deepseekReason.trim()) {
    return deepseekReason;
  }
  return "暂无详细原因";
}

function fallbackImageUrl(asin: string) {
  const cleaned = asin.trim().toUpperCase();
  if (cleaned.length !== 10) {
    return null;
  }
  return `https://images-na.ssl-images-amazon.com/images/P/${cleaned}.01._SCLZZZZZZZ_.jpg`;
}

function productImageCandidates(product: RwProduct) {
  const cleaned = product.asin.trim().toUpperCase();
  const candidates = [
    product.image_url,
    product.image_url?.replace(
      "https://images-na.ssl-images-amazon.com/images/I/",
      "https://m.media-amazon.com/images/I/",
    ),
    cleaned.length === 10
      ? `https://m.media-amazon.com/images/P/${cleaned}.01._SL160_.jpg`
      : null,
    cleaned.length === 10
      ? `https://images-na.ssl-images-amazon.com/images/P/${cleaned}.01._SCLZZZZZZZ_.jpg`
      : null,
  ];
  return candidates.filter(
    (candidate, index): candidate is string =>
      Boolean(candidate) && candidates.indexOf(candidate) === index,
  );
}

function ProductImage({ product }: { product: RwProduct }) {
  const candidates = useMemo(() => productImageCandidates(product), [product]);
  const [candidateIndex, setCandidateIndex] = useState(0);
  const src = candidates[candidateIndex] ?? null;

  useEffect(() => {
    setCandidateIndex(0);
  }, [candidates]);

  if (!src) {
    return <span>无图</span>;
  }
  return (
    <img
      alt={product.title_zh ?? product.title}
      loading="lazy"
      onError={() => {
        setCandidateIndex((current) => current + 1);
      }}
      src={src}
    />
  );
}

function AsinTag({ asin }: { asin: string }) {
  const [copied, setCopied] = useState(false);

  async function copyAsin() {
    try {
      await window.navigator.clipboard.writeText(asin);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button
      className={styles.asinTag}
      onClick={() => {
        void copyAsin();
      }}
      title="复制 ASIN"
      type="button"
    >
      <Copy aria-hidden="true" size={13} />
      <span>{asin}</span>
      {copied ? <span className={styles.copyState}>已复制</span> : null}
    </button>
  );
}

function BsrCell({ product }: { product: RwProduct }) {
  const bestsellerParentRank = numberFeature(product, "bestseller_parent_rank");
  const bestsellerParentCategory =
    stringFeature(product, "bestseller_parent_category") ?? "大类目";
  const subcategoryRank = numberFeature(product, "subcategory_rank") ?? product.bsr;
  const subcategoryName = stringFeature(product, "subcategory_name") ?? product.category;

  return (
    <div className={styles.bsrStack}>
      <span>
        <strong>BestSeller 大类目</strong>
        {bestsellerParentRank === null
          ? "暂无"
          : `#${bestsellerParentRank.toLocaleString("zh-CN")}`}
        <em>{bestsellerParentCategory}</em>
      </span>
      <span>
        <strong>产品小类目</strong>
        #{subcategoryRank.toLocaleString("zh-CN")}
        <em>{subcategoryName}</em>
      </span>
    </div>
  );
}

function monthlySalesDisplay(product: RwProduct) {
  const realMonthlySales = numberFeature(product, "monthly_sales");
  if (realMonthlySales !== null) {
    return `月销量 ${realMonthlySales.toLocaleString("zh-CN")}`;
  }
  const estimate = numberFeature(product, "monthly_sales_estimate");
  if (estimate === null) {
    return "月销量 未知";
  }
  const minimum = numberFeature(product, "monthly_sales_estimate_min");
  const maximum = numberFeature(product, "monthly_sales_estimate_max");
  const confidence = stringFeature(product, "monthly_sales_confidence");
  const confidenceLabel: Record<string, string> = {
    high: "高",
    low: "低",
    medium: "中",
  };
  const suffix = `估算${
    confidence ? `·置信度${confidenceLabel[confidence] ?? confidence}` : ""
  }`;
  if (minimum !== null && maximum !== null && minimum !== maximum) {
    return `月销量约 ${minimum.toLocaleString("zh-CN")}-${maximum.toLocaleString(
      "zh-CN",
    )}（${suffix}）`;
  }
  return `月销量约 ${estimate.toLocaleString("zh-CN")}（${suffix}）`;
}

function productMetrics(
  products: readonly RwProduct[],
  counts: RwStatus["runtime"]["counts"] | undefined,
  productResponseCount: number | undefined,
) {
  const passed =
    counts?.passed ??
    products.filter((product) => product.pipeline_decision === "pass").length;
  const rejected =
    counts?.rejected ??
    products.filter((product) => product.pipeline_decision === "reject").length;
  const pending =
    counts?.pending_review ??
    products.filter((product) => product.pipeline_decision === "pending_review").length;
  const productsWithMargin = products.filter(
    (product): product is RwProduct & { margin: number } =>
      typeof product.margin === "number",
  );
  const averageMargin =
    productsWithMargin.length === 0
      ? null
      : productsWithMargin.reduce((total, product) => total + product.margin, 0) /
        productsWithMargin.length;
  return {
    averageMargin,
    passed,
    pending,
    rejected,
    total: counts?.total_products ?? productResponseCount ?? products.length,
  };
}

function numberFeature(product: RwProduct, key: string) {
  const value = product.features[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() && !Number.isNaN(Number(value))) {
    return Number(value);
  }
  return null;
}

function stringFeature(product: RwProduct, key: string) {
  const value = product.features[key];
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  return null;
}

function ViewTabs({ activeView }: { activeView: WarehouseView }) {
  return (
    <div className={styles.tabs}>
      {tabs.map((tab) => (
        <Link
          className={`${styles.tab} ${
            activeView === tab.view ? styles.tabActive : ""
          }`}
          href={tab.href}
          key={tab.view}
        >
          <Database aria-hidden="true" size={16} />
          <span>{tab.label}</span>
        </Link>
      ))}
    </div>
  );
}

function ProductsTable({ products }: { products: readonly RwProduct[] }) {
  if (products.length === 0) {
    return <div className={styles.empty}>后端产品库暂无记录。</div>;
  }

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>产品</th>
            <th>价格</th>
            <th>BSR</th>
            <th>评论</th>
            <th>卖家</th>
            <th>利润率</th>
            <th>分数</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {products.map((product) => {
            const monthlySales = monthlySalesDisplay(product);
            return (
              <tr key={product.asin}>
                <td>
                  <div className={styles.productCell}>
                    <div className={styles.productPreview}>
                      <ProductImage product={product} />
                    </div>
                    <div>
                      <strong>{product.title_zh ?? "中文名翻译中"}</strong>
                      <span>{product.title}</span>
                      <span className={styles.metaLine}>
                        <AsinTag asin={product.asin} />
                        <span>{product.brand ?? "未知品牌"}</span>
                        <span>{product.category}</span>
                      </span>
                      <span>
                        评分 {product.rating ?? "无"} · 趋势 {priceTrendLabel(product.price_trend)}
                      </span>
                      <span className={styles.metaLine}>
                        <span>{fulfillmentLabel(product.fulfillment_method)}</span>
                        <span className={styles.salesTag}>{monthlySales}</span>
                        {product.lithium_battery_warning ? (
                          <span className={styles.lithiumTag}>锂电提示</span>
                        ) : null}
                      </span>
                    </div>
                  </div>
                </td>
                <td>{product.price === null ? "无" : currency(product.price)}</td>
                <td>
                  <BsrCell product={product} />
                </td>
                <td>{product.reviews.toLocaleString("zh-CN")}</td>
                <td>{product.seller_count}</td>
                <td>
                  {product.margin === null ? "未计算" : percent(product.margin)}
                  {product.margin_confidence === "unknown" ? (
                    <span className={styles.stateText}>缺成本</span>
                  ) : null}
                </td>
                <td>{product.skill_score ?? "待跑"}</td>
                <td>
                  <span
                    className={`${styles.badge} ${
                      product.pipeline_decision === "reject" ? styles.rejectBadge : ""
                    }`}
                    title={
                      product.pipeline_decision === "reject"
                        ? rejectReasonLabel(product.rule_reject_reason, product.features)
                        : undefined
                    }
                  >
                    {decisionLabel(product.pipeline_decision)}
                  </span>
                  <span className={styles.stateText}>{stateLabel(product.state)}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RulesList({ rules }: { rules: RwRulesResponse }) {
  return (
    <div className={styles.ruleList}>
      {rules.items.map((rule) => (
        <div className={styles.ruleRow} key={rule.id}>
          <strong>{rule.label}</strong>
          <span className={styles.muted}>{rule.threshold}</span>
          <span className={styles.badge}>{rule.result}</span>
        </div>
      ))}
    </div>
  );
}

function CategorySelectionList({
  depth = 0,
  node,
  onToggleCategory,
  saving,
}: {
  depth?: number;
  node: RwCategoryNode;
  onToggleCategory: (categoryId: string, selected: boolean) => void;
  saving: boolean;
}) {
  return (
    <div className={styles.categoryNode}>
      <label style={{ paddingLeft: depth * 16 }}>
        <input
          checked={node.selected}
          aria-busy={saving}
          disabled={saving}
          onChange={(event) => {
            onToggleCategory(node.id, event.target.checked);
          }}
          type="checkbox"
        />
        <span>{node.name}</span>
      </label>
      {node.children.map((child) => (
        <CategorySelectionList
          depth={depth + 1}
          key={child.id}
          node={child}
          onToggleCategory={onToggleCategory}
          saving={saving}
        />
      ))}
    </div>
  );
}

function PipelineView({ pipeline }: { pipeline: RwPipelineResponse }) {
  const workers = pipeline.runtime.workers;
  const events = pipeline.runtime.events;
  return (
    <section className={styles.panel}>
      <div className={styles.panelHeader}>
        <div>
          <h2>抓取流水线</h2>
          <p>Keepa → 规则预筛 → DeepSeek 初筛 → 入库 → 页面刷新</p>
        </div>
        <span className={styles.badge}>5 秒刷新</span>
      </div>
      <div className={styles.workerGrid}>
        {workers.length === 0 ? (
          <div className={styles.empty}>尚未收到 worker 心跳。</div>
        ) : (
          workers.map((worker) => (
            <div className={styles.workerRow} key={worker.worker_name}>
              <strong>{worker.worker_name}</strong>
              <span>{statusLabel(worker.status)}</span>
              <span>Keepa {worker.loop_interval_seconds} 秒/轮</span>
              <span>DeepSeek 实时/条</span>
              <span>队列 {worker.queue_pending}</span>
              <span>{worker.last_heartbeat_at ?? "暂无心跳"}</span>
            </div>
          ))
        )}
      </div>
      <div className={styles.eventList}>
        {events.length === 0 ? (
          <div className={styles.empty}>暂无流水线事件。</div>
        ) : (
          events.map((event, index) => (
            <div className={styles.eventRow} key={`${event.created_at}-${index}`}>
              <div>
                <strong>{eventLabel(event.event_type)}</strong>
                <span>{event.asin ?? event.category_id ?? "系统事件"}</span>
              </div>
              <span>{stateLabel(event.stage)}</span>
              <span>
                {event.score_action ? decisionLabel(event.score_action) : statusLabel(event.status)}
              </span>
              <span>{event.created_at}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function BatchStatusView({
  categoryTree,
  onSaveCategories,
  onSaveSettings,
  savingCategory,
  savingSettings,
  settings,
  status,
}: {
  categoryTree: RwCategoryTreeResponse | null;
  onSaveCategories: (selectedCategories: string[]) => Promise<void>;
  onSaveSettings: (settings: Partial<RwRuntimeSettings>) => Promise<void>;
  savingCategory: boolean;
  savingSettings: boolean;
  settings: RwSettingsResponse | null;
  status: RwStatus;
}) {
  const queue = status.runtime.queue;
  const runtimeSettings = settings?.settings;
  const [draftCategoryTree, setDraftCategoryTree] =
    useState<RwCategoryTreeResponse | null>(categoryTree);
  const [categoryDirty, setCategoryDirty] = useState(false);
  const [draft, setDraft] = useState<RwRuntimeSettings>({
    deepseek_batch_size: runtimeSettings?.deepseek_batch_size ?? 100,
    deepseek_interval_seconds:
      runtimeSettings?.deepseek_interval_seconds ??
      status.runtime.workers[0]?.deepseek_interval_seconds ??
      300,
    deepseek_max_runtime_seconds:
      runtimeSettings?.deepseek_max_runtime_seconds ?? 240,
    deepseek_schedule_enabled:
      runtimeSettings?.deepseek_schedule_enabled ??
      status.deepseek_batch.schedule_enabled ??
      false,
    deepseek_timezone:
      runtimeSettings?.deepseek_timezone ??
      status.deepseek_batch.timezone ??
      "Asia/Shanghai",
    deepseek_window_end:
      runtimeSettings?.deepseek_window_end ??
      status.deepseek_batch.window_end ??
      "05:00",
    deepseek_window_start:
      runtimeSettings?.deepseek_window_start ??
      status.deepseek_batch.window_start ??
      "01:00",
    discovery_categories_per_cycle:
      runtimeSettings?.discovery_categories_per_cycle ?? 20,
    keepa_429_backoff_seconds:
      runtimeSettings?.keepa_429_backoff_seconds ?? 60,
    keepa_batch_size: runtimeSettings?.keepa_batch_size ?? 20,
    selected_categories: runtimeSettings?.selected_categories ?? null,
  });

  useEffect(() => {
    if (!runtimeSettings) {
      return;
    }
    setDraft(runtimeSettings);
  }, [runtimeSettings]);

  useEffect(() => {
    if (categoryDirty) {
      return;
    }
    setDraftCategoryTree(categoryTree);
  }, [categoryDirty, categoryTree]);

  const draftSelectedCategories = draftCategoryTree
    ? collectSelectedCategoryIds(draftCategoryTree.root)
    : [];

  function toggleDraftCategory(categoryId: string, selected: boolean) {
    setDraftCategoryTree((current) => {
      if (!current) {
        return current;
      }
      const nextTree = updateCategoryTreeSelection(current, categoryId, selected);
      return {
        ...nextTree,
        selected_categories: collectSelectedCategoryIds(nextTree.root),
      };
    });
    setCategoryDirty(true);
  }

  return (
    <section className={styles.panel}>
      <div className={styles.panelHeader}>
        <div>
          <h2>批次状态</h2>
          <p>DeepSeek 抓取后实时初筛，Keepa 队列持续按类目处理。</p>
        </div>
        <span className={styles.badge}>实时初筛</span>
      </div>
      <dl className={styles.statusGrid}>
        <div>
          <dt>DeepSeek 模式</dt>
          <dd>抓取后实时运行</dd>
        </div>
        <div>
          <dt>DeepSeek 模型</dt>
          <dd>{status.deepseek_batch.model ?? "deepseek-v4-pro"}</dd>
        </div>
        <div>
          <dt>DeepSeek 已处理</dt>
          <dd>{status.deepseek_batch.total_processed}</dd>
        </div>
        <div>
          <dt>DeepSeek 通过</dt>
          <dd>{status.deepseek_batch.pass_count}</dd>
        </div>
        <div>
          <dt>DeepSeek 剔除</dt>
          <dd>{status.deepseek_batch.fail_count}</dd>
        </div>
        <div>
          <dt>队列待处理</dt>
          <dd>{queue.pending ?? 0}</dd>
        </div>
        <div>
          <dt>队列处理中</dt>
          <dd>{queue.picked ?? 0}</dd>
        </div>
      </dl>
      <form
        className={styles.settingsGrid}
        onSubmit={(event) => {
          event.preventDefault();
          const { selected_categories: _selectedCategories, ...runtimeDraft } = draft;
          void onSaveSettings({
            discovery_categories_per_cycle: runtimeDraft.discovery_categories_per_cycle,
            keepa_429_backoff_seconds: runtimeDraft.keepa_429_backoff_seconds,
            keepa_batch_size: runtimeDraft.keepa_batch_size,
            deepseek_schedule_enabled: false,
          });
        }}
      >
        <label>
          <span>Keepa 每轮产品数</span>
          <input
            max={20}
            min={1}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                keepa_batch_size: Number(event.target.value),
              }))
            }
            type="number"
            value={draft.keepa_batch_size}
          />
        </label>
        <label>
          <span>每轮发现类目数</span>
          <input
            max={20}
            min={1}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                discovery_categories_per_cycle: Number(event.target.value),
              }))
            }
            type="number"
            value={draft.discovery_categories_per_cycle}
          />
        </label>
        <label>
          <span>429 暂停秒数</span>
          <input
            min={60}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                keepa_429_backoff_seconds: Number(event.target.value),
              }))
            }
            step={60}
            type="number"
            value={draft.keepa_429_backoff_seconds}
          />
        </label>
        <button className={styles.filterButton} disabled={savingSettings} type="submit">
          {savingSettings ? "保存中" : "保存设置"}
        </button>
      </form>
      <div className={styles.categorySelector}>
        <div className={styles.selectorHeader}>
          <strong>Keepa 抓取类目</strong>
          <span>
            草稿 {draftSelectedCategories.length} 个 / 已保存 {status.category_tree.selected_count} 个
            {typeof status.category_tree.runnable_selected_count === "number"
              ? ` / 实抓 ${status.category_tree.runnable_selected_count} 个`
              : ""}
          </span>
        </div>
        <div className={styles.selectorActions}>
          <button
            className={styles.filterButton}
            disabled={!categoryDirty || savingCategory}
            onClick={() => {
              void onSaveCategories(draftSelectedCategories)
                .then(() => {
                  setCategoryDirty(false);
                })
                .catch(() => undefined);
            }}
            type="button"
          >
            {savingCategory ? "保存中" : categoryDirty ? "保存类目设置" : "类目已保存"}
          </button>
        </div>
        {draftCategoryTree ? (
          <div className={styles.categoryTree}>
            <CategorySelectionList
              node={draftCategoryTree.root}
              onToggleCategory={toggleDraftCategory}
              saving={savingCategory}
            />
          </div>
        ) : (
          <div className={styles.empty}>类目树暂不可用。</div>
        )}
      </div>
    </section>
  );
}

export function WarehouseWorkspace({ view }: { view: WarehouseView }) {
  const { user } = useAuth();
  const [state, setState] = useState<WarehouseState>({
    categoryTree: null,
    pipeline: null,
    products: null,
    rules: null,
    settings: null,
    status: null,
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [savingCategory, setSavingCategory] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [deletingRejected, setDeletingRejected] = useState(false);
  const [showDeepseekReport, setShowDeepseekReport] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [filters, setFilters] = useState<ProductFilters>({
    category_id: "",
    q: "",
    state: "",
    sort_by: "updated_at",
    sort_order: "desc",
  });
  const stateRef = useRef(state);
  const filtersRef = useRef(filters);
  const deepseekDailyReportKey = `${DEEPSEEK_DAILY_REPORT_KEY_PREFIX}:${
    user?.id ?? "anonymous"
  }`;

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);

  useEffect(() => {
    if (!state.status || typeof window === "undefined") {
      return;
    }
    const today = new Date().toISOString().slice(0, 10);
    if (window.localStorage.getItem(deepseekDailyReportKey) !== today) {
      setShowDeepseekReport(true);
    }
  }, [deepseekDailyReportKey, state.status]);

  useEffect(() => {
    let cancelled = false;
    let firstLoad = true;

    async function load() {
      if (firstLoad) {
        setLoading(true);
      } else {
        setRefreshing(true);
      }
      try {
        const currentState = stateRef.current;
        const requests: Array<[
          RwEndpointKey,
          Promise<WarehouseState[RwEndpointKey]>,
        ]> = [
          ["status", getRwStatus()],
          [
            "products",
            getRwProductsWithFilters({
              category_id: filtersRef.current.category_id || undefined,
              q: filtersRef.current.q || undefined,
              state: filtersRef.current.state || undefined,
              sort_by: filtersRef.current.sort_by,
              sort_order: filtersRef.current.sort_order,
            }),
          ],
          ["pipeline", getRwPipeline()],
        ];
        if (firstLoad || view === "rules" || !currentState.rules) {
          requests.push(["rules", getRwRules()]);
        }
        if (firstLoad || view === "batch" || !currentState.settings) {
          requests.push(["settings", getRwSettings()]);
        }
        if (
          firstLoad ||
          view === "batch" ||
          view === "products" ||
          !currentState.categoryTree
        ) {
          requests.push(["categoryTree", getRwCategoryTree()]);
        }
        const results = await Promise.allSettled(
          requests.map(([, request]) => request),
        );
        if (!cancelled) {
          const failed = results.filter((result) => result.status === "rejected");
          let nextState = stateRef.current;
          setState((current) => {
            const updated = { ...current };
            results.forEach((result, index) => {
              if (result.status === "fulfilled") {
                applyWarehouseStateValue(
                  updated,
                  requests[index][0],
                  result.value,
                );
              }
            });
            nextState = updated;
            stateRef.current = updated;
            return updated;
          });
          setLastRefresh(new Date().toLocaleTimeString("zh-CN"));
          if (failed.length === 0) {
            setError(null);
          } else if (readableWarehouseState(nextState, filtersRef.current)) {
            setError("部分后端数据刷新失败，已保留上一轮可读数据。");
          } else {
            const loadError = failed[0].reason;
            setError(
              loadError instanceof Error && loadError.message.includes("无权")
                ? "暂无权限，请联系管理员开通权限。"
                : "R-W 后端连接中，页面会自动重试。",
            );
          }
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error && loadError.message.includes("无权")
              ? "暂无权限，请联系管理员开通权限。"
              : "R-W 后端连接中，页面会自动重试。",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
          firstLoad = false;
        }
      }
    }

    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [view]);

  useEffect(() => {
    if (!stateRef.current.products) {
      return;
    }
    let cancelled = false;
    setRefreshing(true);
    getRwProductsWithFilters({
      category_id: filters.category_id || undefined,
      q: filters.q || undefined,
      state: filters.state || undefined,
      sort_by: filters.sort_by,
      sort_order: filters.sort_order,
    })
      .then((response) => {
        if (cancelled) {
          return;
        }
        setState((current) => {
          const updated = { ...current, products: response };
          stateRef.current = updated;
          return updated;
        });
        setError(null);
      })
      .catch(() => {
        if (!cancelled) {
          setError("产品列表刷新失败，已保留上一轮可读数据。");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setRefreshing(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [filters]);

  const readyState = readableWarehouseState(state, filters);
  const products = state.products?.items ?? [];
  const metrics = useMemo(
    () =>
      productMetrics(
        products,
        readyState?.status.runtime.counts,
        state.products?.count,
      ),
    [products, readyState?.status.runtime.counts, state.products?.count],
  );
  const categoryLabels = useMemo(
    () => collectCategoryLabels(readyState?.categoryTree?.root ?? null),
    [readyState?.categoryTree?.root],
  );

  async function saveSettings(settings: Partial<RwRuntimeSettings>) {
    setSavingSettings(true);
    try {
      const response = await updateRwSettings(settings);
      setState((current) => {
        const updated = { ...current, settings: response };
        stateRef.current = updated;
        return updated;
      });
      setError(null);
    } catch {
      setError("R-W 运行设置保存失败，现有页面数据已保留。");
    } finally {
      setSavingSettings(false);
    }
  }

  async function refreshProductsOnly(activeFilters: ProductFilters = filtersRef.current) {
    setRefreshing(true);
    try {
      const response = await getRwProductsWithFilters({
        category_id: activeFilters.category_id || undefined,
        q: activeFilters.q || undefined,
        sort_by: activeFilters.sort_by,
        sort_order: activeFilters.sort_order,
        state: activeFilters.state || undefined,
      });
      setState((current) => {
        const updated = { ...current, products: response };
        stateRef.current = updated;
        return updated;
      });
      setLastRefresh(new Date().toLocaleTimeString("zh-CN"));
      setError(null);
    } catch {
      setError("产品列表刷新失败，已保留上一轮可读数据。");
    } finally {
      setRefreshing(false);
    }
  }

  async function saveCategories(selectedCategories: string[]) {
    setSavingCategory(true);
    try {
      const response = await saveRwCategoryTree(selectedCategories);
      const [settingsResponse, statusResponse] = await Promise.all([
        getRwSettings(),
        getRwStatus(),
      ]);
      const runnableCategories =
        response.runnable_selected_categories ?? response.selected_categories;
      setState((current) => {
        const updated: WarehouseState = {
          ...current,
          categoryTree: response,
          settings: settingsResponse,
          status: {
            ...statusResponse,
            category_tree: {
              ...statusResponse.category_tree,
              selected_categories: response.selected_categories,
              selected_count:
                response.selected_count ?? response.selected_categories.length,
              runnable_selected_categories: runnableCategories,
              runnable_selected_count:
                response.runnable_selected_count ?? runnableCategories.length,
            },
          },
        };
        stateRef.current = updated;
        return updated;
      });
      setError(null);
    } catch {
      setError("Keepa 抓取类目保存失败，现有页面数据已保留。");
      throw new Error("rw_category_save_failed");
    } finally {
      setSavingCategory(false);
    }
  }

  async function removeRejectedProducts() {
    setDeletingRejected(true);
    try {
      const result = await deleteRejectedRwProducts();
      setState((current) => {
        const remainingItems =
          current.products?.items.filter(
            (product) => product.pipeline_decision !== "reject",
          ) ?? [];
        const updated = {
          ...current,
          products: current.products
            ? {
                ...current.products,
                count: Math.max(0, current.products.count - result.deleted),
                items: remainingItems,
                returned_count: remainingItems.length,
              }
            : current.products,
          status: current.status
            ? {
                ...current.status,
                runtime: {
                  ...current.status.runtime,
                  counts: {
                    ...current.status.runtime.counts,
                    rejected: 0,
                    total_products: Math.max(
                      0,
                      (current.status.runtime.counts.total_products ?? 0) -
                        result.deleted,
                    ),
                  },
                },
              }
            : current.status,
        };
        stateRef.current = updated;
        return updated;
      });
      setError(null);
    } catch {
      setError("移除未通过产品失败，现有页面数据已保留。");
    } finally {
      setDeletingRejected(false);
    }
  }

  if (loading) {
    return (
      <div className={styles.message} role="status">
        <RefreshCw aria-hidden="true" className="spin" size={18} />
        <span>正在加载 R-W 实时数据。</span>
      </div>
    );
  }

  if (!readyState) {
    return (
      <div className={styles.message} role="alert">
        <AlertCircle aria-hidden="true" size={18} />
        <span>{error ?? "R-W 数据未加载。"}</span>
      </div>
    );
  }

  return (
    <div className={styles.workspace}>
      {showDeepseekReport ? (
        <div className={styles.popupBackdrop} role="presentation">
          <section
            aria-modal="true"
            className={styles.popup}
            role="dialog"
          >
            <strong>DeepSeek 今日初筛报告</strong>
            <dl className={styles.popupStats}>
              <div>
                <dt>运行模式</dt>
                <dd>抓取后实时初筛</dd>
              </div>
              <div>
                <dt>已处理</dt>
                <dd>{readyState.status.deepseek_batch.total_processed}</dd>
              </div>
              <div>
                <dt>通过</dt>
                <dd>{readyState.status.deepseek_batch.pass_count}</dd>
              </div>
              <div>
                <dt>剔除</dt>
                <dd>{readyState.status.deepseek_batch.fail_count}</dd>
              </div>
            </dl>
            <button
              className={styles.popupButton}
              onClick={() => {
                window.localStorage.setItem(
                  deepseekDailyReportKey,
                  new Date().toISOString().slice(0, 10),
                );
                setShowDeepseekReport(false);
              }}
              type="button"
            >
              知道了
            </button>
          </section>
        </div>
      ) : null}
      {error ? (
        <div className={styles.warningMessage} role="status">
          <AlertCircle aria-hidden="true" size={16} />
          <span>{error}</span>
        </div>
      ) : null}
      <div className={styles.toolbar}>
        <ViewTabs activeView={view} />
        <div className={styles.headerStatusGroup}>
          <span className={styles.skillHint}>{readyState.status.skill.label}</span>
          <span className={styles.statusPill}>
            <CheckCircle2 aria-hidden="true" size={16} />
            {modeLabel(readyState.status.mode)}
          </span>
          <span className={styles.livePill}>
            <Activity aria-hidden="true" size={16} />
            {refreshing ? "刷新中" : `已刷新 ${lastRefresh ?? ""}`}
          </span>
        </div>
      </div>

      <section className={styles.metrics} aria-label="R-W 实时指标">
        <div className={styles.metric}>
          <span>产品数</span>
          <strong>{metrics.total}</strong>
        </div>
        <div className={styles.metric}>
          <span>通过</span>
          <strong>{metrics.passed}</strong>
        </div>
        <div className={styles.metric}>
          <span>待复核</span>
          <strong>{metrics.pending}</strong>
        </div>
        <div className={styles.metric}>
          <span>剔除</span>
          <strong>{metrics.rejected}</strong>
        </div>
        <div className={styles.metric}>
          <span>平均利润率</span>
          <strong>{metrics.averageMargin === null ? "未计算" : percent(metrics.averageMargin)}</strong>
        </div>
      </section>

      {view === "dashboard" ? (
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h2>实时仓库总览</h2>
              <p>{readyState.status.organization}</p>
            </div>
            <span className={`${styles.badge} ${readyState.status.waiting_for_keys ? styles.warningBadge : ""}`}>
              {readyState.status.waiting_for_keys ? "等待 Keepa 密钥" : "自动运行"}
            </span>
          </div>
          <ProductsTable products={products} />
        </section>
      ) : null}

      {view === "products" ? (
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h2>产品数据仓库</h2>
              <p>来自 Keepa 抓取和自动评分流水线的 ASIN 记录。</p>
            </div>
          </div>
          <div className={styles.filters}>
            <input
              onChange={(event) =>
                setFilters((current) => ({ ...current, q: event.target.value }))
              }
              placeholder="搜索标题 / ASIN / 类目"
              value={filters.q}
            />
            <select
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  category_id: event.target.value,
                }))
              }
              value={filters.category_id}
            >
              <option value="">全部类目</option>
              {readyState.status.category_tree.selected_categories.map((category) => (
                <option key={category} value={category}>
                  {categoryLabels.get(category) ?? category}
                </option>
              ))}
            </select>
            <select
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  sort_by: event.target.value as ProductFilters["sort_by"],
                }))
              }
              value={filters.sort_by}
            >
              <option value="updated_at">更新时间</option>
              <option value="skill_score">初筛分数</option>
            </select>
            <button
              className={styles.filterButton}
              disabled={refreshing}
              onClick={() => {
                void refreshProductsOnly(filters);
              }}
              type="button"
            >
              <Search aria-hidden="true" size={15} />
              筛选
            </button>
            <button
              className={styles.filterButton}
              onClick={() =>
                setFilters((current) => ({
                  ...current,
                  state: current.state === "pass" ? "" : "pass",
                }))
              }
              type="button"
            >
              {filters.state === "pass" ? "查看全部产品" : "一键查看通过产品"}
            </button>
            <button
              className={styles.filterButton}
              disabled={deletingRejected}
              onClick={() => {
                void removeRejectedProducts();
              }}
              type="button"
            >
              {deletingRejected ? "移除中" : "一键移除未通过产品"}
            </button>
            <button
              className={styles.filterButton}
              onClick={() =>
                setFilters((current) => ({
                  ...current,
                  sort_order: current.sort_order === "asc" ? "desc" : "asc",
                }))
              }
              type="button"
            >
              {filters.sort_by === "skill_score" ? "评分" : "时间"}
              {filters.sort_order === "asc" ? "升序" : "降序"}
            </button>
          </div>
          <ProductsTable products={products} />
        </section>
      ) : null}

      {view === "pipeline" ? <PipelineView pipeline={readyState.pipeline} /> : null}

      {view === "batch" ? (
        <BatchStatusView
          categoryTree={readyState.categoryTree}
          onSaveCategories={saveCategories}
          onSaveSettings={saveSettings}
          savingCategory={savingCategory}
          savingSettings={savingSettings}
          settings={readyState.settings}
          status={readyState.status}
        />
      ) : null}

      {view === "rules" ? (
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h2>规则引擎</h2>
              <p>R-W 生产流水线当前强制执行的硬性过滤规则。</p>
            </div>
            <span className={styles.badge}>已启用</span>
          </div>
          {readyState.rules ? (
            <RulesList rules={readyState.rules} />
          ) : (
            <div className={styles.empty}>规则接口暂不可用，页面其它数据已保留。</div>
          )}
        </section>
      ) : null}
    </div>
  );
}

function readableWarehouseState(
  value: WarehouseState,
  filters: ProductFilters,
): CompleteWarehouseState | null {
  if (!value.status) {
    return null;
  }
  return {
    categoryTree: value.categoryTree,
    pipeline: value.pipeline ?? emptyPipelineResponse(value.status),
    products: value.products ?? emptyProductsResponse(value.status, filters),
    rules: value.rules,
    settings: value.settings,
    status: value.status,
  };
}

function emptyProductsResponse(
  status: RwStatus,
  filters: ProductFilters,
): RwProductsResponse {
  return {
    count: 0,
    filters: {
      category_id: filters.category_id || null,
      q: filters.q || null,
      sort_by: filters.sort_by,
      sort_order: filters.sort_order,
      state: filters.state || null,
    },
    items: [],
    mode: "production",
    organization: status.organization,
    returned_count: 0,
  };
}

function emptyPipelineResponse(status: RwStatus): RwPipelineResponse {
  return {
    mode: "production",
    module: "R-W",
    organization: status.organization,
    refresh_seconds: 5,
    runtime: status.runtime,
  };
}

function applyWarehouseStateValue(
  target: WarehouseState,
  key: RwEndpointKey,
  value: WarehouseState[RwEndpointKey],
) {
  if (key === "status") {
    target.status = value as RwStatus;
  } else if (key === "products") {
    target.products = value as RwProductsResponse;
  } else if (key === "rules") {
    target.rules = value as RwRulesResponse;
  } else if (key === "pipeline") {
    target.pipeline = value as RwPipelineResponse;
  } else if (key === "categoryTree") {
    target.categoryTree = value as RwCategoryTreeResponse;
  } else {
    target.settings = value as RwSettingsResponse;
  }
}

function collectCategoryLabels(root: RwCategoryNode | null) {
  const labels = new Map<string, string>();
  function visit(node: RwCategoryNode) {
    labels.set(node.id, node.name);
    node.children.forEach(visit);
  }
  if (root) {
    visit(root);
  }
  return labels;
}

function collectSelectedCategoryIds(root: RwCategoryNode) {
  const selected: string[] = [];
  function visit(node: RwCategoryNode) {
    if (node.selected) {
      selected.push(node.id);
    }
    node.children.forEach(visit);
  }
  visit(root);
  return selected;
}

function updateCategoryTreeSelection(
  tree: RwCategoryTreeResponse,
  categoryId: string,
  selected: boolean,
): RwCategoryTreeResponse {
  return {
    ...tree,
    root: updateCategoryNodeSelection(tree.root, categoryId, selected),
  };
}

function updateCategoryNodeSelection(
  node: RwCategoryNode,
  categoryId: string,
  selected: boolean,
): RwCategoryNode {
  if (node.id === categoryId) {
    return setCategorySubtree(node, selected);
  }
  return {
    ...node,
    children: node.children.map((child) =>
      updateCategoryNodeSelection(child, categoryId, selected),
    ),
  };
}

function setCategorySubtree(node: RwCategoryNode, selected: boolean): RwCategoryNode {
  return {
    ...node,
    selected,
    children: node.children.map((child) => setCategorySubtree(child, selected)),
  };
}
