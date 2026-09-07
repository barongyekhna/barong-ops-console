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
import { apiRequest } from "@/lib/api";
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import { useAuth } from "@/components/auth-provider";
import { DashboardScene } from "@/components/dashboard-scene";
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
const PRODUCT_PAGE_SIZE = 50;
const PRODUCT_REFRESH_INTERVAL_MS = 20_000;
const PIPELINE_REFRESH_INTERVAL_MS = 15_000;
const CATEGORY_TREE_REFRESH_INTERVAL_MS = 300_000;

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

function fbaFeeValue(product: RwProduct) {
  if (typeof product.fba_fee === "number" && Number.isFinite(product.fba_fee)) {
    return product.fba_fee;
  }
  const featureFee = numberFeature(product, "fba_fee_usd");
  if (featureFee !== null) {
    return featureFee;
  }
  return numberFeature(product, "fba_pick_pack_fee_usd");
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
    seller_count_filter: "历史报价数规则",
    competition_filter: "历史报价数规则",
    too_many_sellers: "历史报价数规则",
    brand_dominance: "品牌垄断风险过高",
    deepseek_edible_product: "DeepSeek 剔除：食品/保健品/药品/可食用品",
    deepseek_liquid_powder_spray_product: "DeepSeek 剔除：液体/粉末/喷雾内容物",
    deepseek_pest_control_product: "DeepSeek 剔除：杀虫/灭虫/虫害控制产品",
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

function productImageCandidates(product: RwProduct) {
  const cleaned = product.asin.trim().toUpperCase();
  const featureCandidates = product.features.image_candidates;
  const keepaCandidates = Array.isArray(featureCandidates)
    ? featureCandidates.filter(
        (candidate): candidate is string =>
          typeof candidate === "string" && candidate.startsWith("http"),
      )
    : [];
  const candidates = [
    ...keepaCandidates,
    product.image_url,
    product.image_url?.replace(
      "https://images-na.ssl-images-amazon.com/images/I/",
      "https://m.media-amazon.com/images/I/",
    ),
  ];
  return candidates.filter(
    (candidate, index): candidate is string =>
      typeof candidate === "string" &&
      !isAsinFallbackImage(candidate, cleaned) &&
      candidates.indexOf(candidate) === index,
  );
}

function isAsinFallbackImage(candidate: string, asin: string) {
  if (!asin) {
    return false;
  }
  const upper = candidate.toUpperCase();
  return upper.includes(`/IMAGES/P/${asin}.01.`);
}

function ProductImage({ product }: { product: RwProduct }) {
  const candidates = useMemo(() => productImageCandidates(product), [product]);
  const [candidateIndex, setCandidateIndex] = useState(0);
  const [previewPosition, setPreviewPosition] = useState<{ left: number; top: number } | null>(
    null,
  );
  const src = candidates[candidateIndex] ?? null;

  useEffect(() => {
    setCandidateIndex(0);
  }, [candidates]);

  if (!src) {
    return <span>无图</span>;
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
        alt={product.title_zh ?? product.title}
        loading="lazy"
        onError={() => {
          setCandidateIndex((current) => current + 1);
          setPreviewPosition(null);
        }}
        src={src}
      />
      {previewPosition ? (
        <span
          className={styles.imageZoomPreview}
          style={{ left: previewPosition.left, top: previewPosition.top }}
        >
          <img alt="" src={src} />
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

function FbaFeeTag({ product }: { product: RwProduct }) {
  const fee = fbaFeeValue(product);
  const referralFee = product.referral_fee_percentage ?? numberFeature(product, "referral_fee_percentage");
  if (fee === null) {
    return (
      <span className={styles.fbaFeeMissingTag} title="历史产品正在按 Keepa token 节流补齐 FBA 费用">
        FBA费待补
      </span>
    );
  }
  return (
    <span
      className={styles.fbaFeeTag}
      title={
        referralFee === null
          ? "Keepa fbaFees.pickAndPackFee"
          : `Keepa FBA履约费；平台佣金 ${Math.round(referralFee * 100) / 100}%`
      }
    >
      FBA费 {currency(fee)}
    </span>
  );
}

function BsrCell({ product }: { product: RwProduct }) {
  const bestsellerParentRank = numberFeature(product, "bestseller_parent_rank");
  const bestsellerParentCategory =
    stringFeature(product, "bestseller_parent_category") ?? "大类目";
  const subcategoryRank = numberFeature(product, "subcategory_rank");
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
        {subcategoryRank === null
          ? "暂无真实排名"
          : `#${subcategoryRank.toLocaleString("zh-CN")}`}
        <em>{subcategoryName}</em>
      </span>
    </div>
  );
}

function categoryPathDisplay(product: RwProduct) {
  const featurePath = product.features.amazon_category_path;
  if (Array.isArray(featurePath)) {
    const labels = featurePath.filter(
      (item): item is string => typeof item === "string" && item.trim().length > 0,
    );
    if (labels.length > 0) {
      return labels.join(" > ");
    }
  }
  if (product.category_path.length > 0) {
    return product.category_path.join(" > ");
  }
  return product.category;
}

function monthlySalesDisplay(product: RwProduct) {
  const finalMonthlySales = numberFeature(product, "monthly_sales_value");
  const valueSource = stringFeature(product, "monthly_sales_value_source");
  const dataConflict = booleanFeature(product, "monthly_sales_data_conflict");
  if (finalMonthlySales !== null) {
    const sourceLabel =
      valueSource === "keepa_monthly_sold"
        ? "Keepa"
        : valueSource
          ? "BSR修正"
          : "最终值";
    return `月销量 ${finalMonthlySales.toLocaleString("zh-CN")}（${sourceLabel}${
      dataConflict ? "·原始值冲突" : ""
    }）`;
  }
  const realMonthlySales = numberFeature(product, "monthly_sales");
  if (realMonthlySales !== null) {
    return `月销量 ${realMonthlySales.toLocaleString("zh-CN")}（Keepa原始）`;
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

function booleanFeature(product: RwProduct, key: string) {
  const value = product.features[key];
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["true", "1", "yes"].includes(normalized)) {
      return true;
    }
    if (["false", "0", "no"].includes(normalized)) {
      return false;
    }
  }
  return false;
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

function ProductsTable({
  backendProductCount,
  products,
}: {
  backendProductCount: number;
  products: readonly RwProduct[];
}) {
  const [transferChannel, setTransferChannel] = useState<"dtc" | "amazon">("dtc");
  const [busyAsin, setBusyAsin] = useState<string | null>(null);
  const [transferMsg, setTransferMsg] = useState("");

  async function handleTransferToK(asin: string) {
    setBusyAsin(asin);
    setTransferMsg("");
    try {
      // 那段读 `barong_ops_access_token` 拼 Bearer 的代码是死的：全仓 19 处
      // getItem、0 处 setItem，代理 route.ts 也不读 Authorization。
      // 认证一直靠同源 Cookie，收口后升级成 Cookie + X-Session-Token。
      const data = await apiRequest<{
        created?: unknown[];
        skipped?: unknown[];
      }>("/k/products/import-from-r", {
        body: { asins: [asin], channel: transferChannel },
        method: "POST",
      });
      const group = transferChannel === "amazon" ? "亚马逊" : "独立站";
      if (data.created?.length) {
        setTransferMsg(`${asin} 已搬入 K · ${group}分组`);
      } else if (data.skipped?.length) {
        setTransferMsg(`${asin} 已在 K 中，跳过`);
      } else {
        setTransferMsg(`${asin} 搬运未成功`);
      }
    } catch (error) {
      setTransferMsg(
        `${asin} 搬运失败：${error instanceof Error ? error.message : ""}`,
      );
    } finally {
      setBusyAsin(null);
    }
  }
  if (products.length === 0) {
    if (backendProductCount > 0) {
      return (
        <div className={styles.empty}>
          产品列表正在刷新，后端产品库已有{" "}
          {backendProductCount.toLocaleString("zh-CN")} 条记录。
        </div>
      );
    }
    return <div className={styles.empty}>后端产品库暂无记录。</div>;
  }

  return (
    <div className={styles.tableWrap}>
      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          marginBottom: 10,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontSize: "0.82rem", color: "var(--mm-dim, var(--color-muted))" }}>
          搬入 K 的分组：
        </span>
        <label style={{ display: "inline-flex", gap: 5, alignItems: "center", fontSize: "0.85rem" }}>
          <input checked={transferChannel === "dtc"} name="rw-transfer-channel" onChange={() => setTransferChannel("dtc")} type="radio" />
          独立站
        </label>
        <label style={{ display: "inline-flex", gap: 5, alignItems: "center", fontSize: "0.85rem" }}>
          <input checked={transferChannel === "amazon"} name="rw-transfer-channel" onChange={() => setTransferChannel("amazon")} type="radio" />
          亚马逊
        </label>
        {transferMsg ? (
          <span style={{ fontSize: "0.82rem", color: "var(--mm-cyan, var(--color-primary-strong))" }}>{transferMsg}</span>
        ) : null}
      </div>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>产品</th>
            <th>价格</th>
            <th>FBA费</th>
            <th>BSR</th>
            <th>评论</th>
            <th>ASIN 报价数</th>
            <th>利润率</th>
            <th>分数</th>
            <th>状态</th>
            <th>搬入 K</th>
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
                      <strong>{product.title_zh ?? product.title}</strong>
                      <span>{product.title_zh ? product.title : "中文名待 R-A 选中后翻译"}</span>
                      <span className={styles.metaLine}>
                        <AsinTag asin={product.asin} />
                        <span>{product.brand ?? "未知品牌"}</span>
                        <span className={styles.categoryPath}>
                          {categoryPathDisplay(product)}
                        </span>
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
                  <FbaFeeTag product={product} />
                </td>
                <td>
                  <BsrCell product={product} />
                </td>
                <td>{product.reviews.toLocaleString("zh-CN")}</td>
                <td>{product.seller_count ?? "未记录"}</td>
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
                <td>
                  <button
                    disabled={busyAsin === product.asin}
                    onClick={() => void handleTransferToK(product.asin)}
                    style={{
                      padding: "4px 10px",
                      borderRadius: 6,
                      border: "1px solid var(--mm-cyan, color-mix(in srgb, var(--color-primary-strong) 40%, transparent))",
                      background: "color-mix(in srgb, var(--color-primary-strong) 10%, transparent)",
                      color: "var(--mm-cyan, var(--color-primary-strong))",
                      cursor: "pointer",
                      fontSize: "0.78rem",
                      whiteSpace: "nowrap",
                    }}
                    type="button"
                  >
                    {busyAsin === product.asin ? "搬运中…" : "搬进 K"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ProductPagination({
  loading,
  onPageChange,
  products,
}: {
  loading: boolean;
  onPageChange: (page: number) => void;
  products: RwProductsResponse;
}) {
  const page = products.page ?? 1;
  const pageSize = products.page_size ?? PRODUCT_PAGE_SIZE;
  const totalPages = products.total_pages ?? Math.max(1, Math.ceil(products.count / pageSize));
  const start = products.count === 0 ? 0 : (page - 1) * pageSize + 1;
  const end =
    products.count === 0
      ? 0
      : Math.min(products.count, start + (products.returned_count ?? products.items.length) - 1);

  return (
    <div className={styles.pagination}>
      <span>
        第 {page} / {totalPages} 页，每页 {pageSize} 条，显示 {start}-{end} / 共{" "}
        {products.count.toLocaleString("zh-CN")} 条
      </span>
      <div>
        <button
          className={styles.filterButton}
          disabled={loading || page <= 1}
          onClick={() => onPageChange(page - 1)}
          type="button"
        >
          上一页
        </button>
        <button
          className={styles.filterButton}
          disabled={loading || page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          type="button"
        >
          下一页
        </button>
      </div>
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
        <span className={styles.categoryLabel}>
          <span>{node.name}</span>
          <em>{node.id}</em>
        </span>
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
  const [productPage, setProductPage] = useState(1);
  const [filters, setFilters] = useState<ProductFilters>({
    category_id: "",
    q: "",
    state: "",
    sort_by: "updated_at",
    sort_order: "desc",
  });
  const stateRef = useRef(state);
  const filtersRef = useRef(filters);
  const productPageRef = useRef(productPage);
  const lastProductRefreshAtRef = useRef(0);
  const lastPipelineRefreshAtRef = useRef(0);
  const lastCategoryTreeRefreshAtRef = useRef(0);
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
    productPageRef.current = productPage;
  }, [productPage]);

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
        const now = Date.now();
        const shouldLoadProducts =
          firstLoad ||
          !currentState.products ||
          now - lastProductRefreshAtRef.current >= PRODUCT_REFRESH_INTERVAL_MS;
        const shouldLoadPipeline =
          firstLoad ||
          !currentState.pipeline ||
          view === "pipeline" ||
          now - lastPipelineRefreshAtRef.current >= PIPELINE_REFRESH_INTERVAL_MS;
        const shouldLoadCategoryTree =
          firstLoad ||
          !currentState.categoryTree ||
          ((view === "batch" || view === "products") &&
            now - lastCategoryTreeRefreshAtRef.current >=
              CATEGORY_TREE_REFRESH_INTERVAL_MS);
        const requests: Array<[
          RwEndpointKey,
          Promise<WarehouseState[RwEndpointKey]>,
        ]> = [["status", getRwStatus()]];
        if (shouldLoadPipeline) {
          requests.push(["pipeline", getRwPipeline()]);
        }
        if (shouldLoadProducts) {
          requests.push([
            "products",
            getRwProductsWithFilters({
              category_id: filtersRef.current.category_id || undefined,
              include_categories: false,
              page: productPageRef.current,
              page_size: PRODUCT_PAGE_SIZE,
              q: filtersRef.current.q || undefined,
              state: filtersRef.current.state || undefined,
              sort_by: filtersRef.current.sort_by,
              sort_order: filtersRef.current.sort_order,
            }),
          ]);
        }
        if (firstLoad || view === "rules" || !currentState.rules) {
          requests.push(["rules", getRwRules()]);
        }
        if (firstLoad || view === "batch" || !currentState.settings) {
          requests.push(["settings", getRwSettings()]);
        }
        if (shouldLoadCategoryTree) {
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
                if (requests[index][0] === "products") {
                  lastProductRefreshAtRef.current = Date.now();
                }
                if (requests[index][0] === "pipeline") {
                  lastPipelineRefreshAtRef.current = Date.now();
                }
                if (requests[index][0] === "categoryTree") {
                  lastCategoryTreeRefreshAtRef.current = Date.now();
                }
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
      include_categories:
        !stateRef.current.categoryTree &&
        (!stateRef.current.products?.category_options ||
          stateRef.current.products.category_options.length === 0),
      page: productPageRef.current,
      page_size: PRODUCT_PAGE_SIZE,
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
          updated.products = mergeProductResponse(current.products, response);
          stateRef.current = updated;
          return updated;
        });
        lastProductRefreshAtRef.current = Date.now();
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
  }, [filters, productPage]);

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
  const productCategoryOptions = useMemo(
    () =>
      collectCategoryOptions(
        readyState?.categoryTree?.root ?? null,
        readyState?.products.category_options ?? [],
      ),
    [readyState?.categoryTree?.root, readyState?.products.category_options],
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

  async function refreshProductsOnly(
    activeFilters: ProductFilters = filtersRef.current,
    page: number = productPageRef.current,
  ) {
    setRefreshing(true);
    try {
      const response = await getRwProductsWithFilters({
        category_id: activeFilters.category_id || undefined,
        include_categories:
          !stateRef.current.categoryTree &&
          (!stateRef.current.products?.category_options ||
            stateRef.current.products.category_options.length === 0),
        page,
        page_size: PRODUCT_PAGE_SIZE,
        q: activeFilters.q || undefined,
        sort_by: activeFilters.sort_by,
        sort_order: activeFilters.sort_order,
        state: activeFilters.state || undefined,
      });
      setState((current) => {
        const updated = {
          ...current,
          products: mergeProductResponse(current.products, response),
        };
        stateRef.current = updated;
        return updated;
      });
      lastProductRefreshAtRef.current = Date.now();
      setLastRefresh(new Date().toLocaleTimeString("zh-CN"));
      setError(null);
    } catch {
      setError("产品列表刷新失败，已保留上一轮可读数据。");
    } finally {
      setRefreshing(false);
    }
  }

  function updateProductFilters(updater: (current: ProductFilters) => ProductFilters) {
    setProductPage(1);
    productPageRef.current = 1;
    setFilters(updater);
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
    <div className={`${styles.workspace} mm-page r-w-page`}>
      <DashboardScene />
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
      <div className="rw-head">
        <span className="rw-eyebrow">R 系列 · 数据仓库</span>
        <h1 className="rw-title">R-W 产品数据仓库</h1>
        <p className="rw-sub">
          Keepa 常驻抓取 · 规则预筛 · DeepSeek 初筛 · 实时入库
        </p>
      </div>
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
          <ProductsTable backendProductCount={metrics.total} products={products} />
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
                updateProductFilters((current) => ({ ...current, q: event.target.value }))
              }
              placeholder="搜索标题 / ASIN / 类目"
              value={filters.q}
            />
            <select
              onChange={(event) =>
                updateProductFilters((current) => ({
                  ...current,
                  category_id: event.target.value,
                }))
              }
              value={filters.category_id}
            >
              <option value="">全部类目</option>
              {productCategoryOptions.map((category) => (
                <option key={category.id} value={category.id}>
                  {`${"　".repeat(category.depth)}${category.label} · ${category.id}`}
                </option>
              ))}
            </select>
            <select
              onChange={(event) =>
                updateProductFilters((current) => ({
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
                setProductPage(1);
                productPageRef.current = 1;
                void refreshProductsOnly(filters, 1);
              }}
              type="button"
            >
              <Search aria-hidden="true" size={15} />
              筛选
            </button>
            <button
              className={styles.filterButton}
              onClick={() =>
                updateProductFilters((current) => ({
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
                updateProductFilters((current) => ({
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
          <ProductsTable backendProductCount={metrics.total} products={products} />
          <ProductPagination
            loading={refreshing}
            onPageChange={(page) => {
              setProductPage(page);
              productPageRef.current = page;
            }}
            products={readyState.products}
          />
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
    category_options: [],
    count: 0,
    filters: {
      category_id: filters.category_id || null,
      page: 1,
      page_size: PRODUCT_PAGE_SIZE,
      q: filters.q || null,
      sort_by: filters.sort_by,
      sort_order: filters.sort_order,
      state: filters.state || null,
    },
    has_next: false,
    has_previous: false,
    items: [],
    mode: "production",
    organization: status.organization,
    page: 1,
    page_size: PRODUCT_PAGE_SIZE,
    returned_count: 0,
    total_pages: 1,
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
    target.products = mergeProductResponse(
      target.products,
      value as RwProductsResponse,
    );
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

function mergeProductResponse(
  current: RwProductsResponse | null,
  next: RwProductsResponse,
): RwProductsResponse {
  if (next.category_options && next.category_options.length > 0) {
    return next;
  }
  if (!current?.category_options || current.category_options.length === 0) {
    return next;
  }
  return {
    ...next,
    category_options: current.category_options,
  };
}

function collectCategoryOptions(
  root: RwCategoryNode | null,
  productOptions: NonNullable<RwProductsResponse["category_options"]>,
) {
  const options: Array<{ depth: number; id: string; label: string }> = [];
  const seen = new Set<string>();
  productOptions.forEach((option) => {
    if (!option.id || seen.has(option.id)) {
      return;
    }
    seen.add(option.id);
    options.push({ depth: 0, id: option.id, label: option.label || option.id });
  });
  function visit(node: RwCategoryNode, depth: number) {
    if (depth > 0 && !seen.has(node.id)) {
      seen.add(node.id);
      options.push({ depth: depth - 1, id: node.id, label: node.name });
    }
    node.children.forEach((child) => visit(child, depth + 1));
  }
  if (root) {
    visit(root, 0);
  }
  return options;
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
