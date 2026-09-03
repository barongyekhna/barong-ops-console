"use client";

import {
  CheckCircle2,
  ChevronUp,
  FileText,
  LoaderCircle,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";

import type { ProductSellingPoints } from "@/modules/k14/selling-points/types";

import type { GenerationJob } from "./api";
import {
  getProduct,
  updateProduct,
  updateVariantPrices,
} from "./api";
import { CopyArtDirection } from "./CopyArtDirection";
import { ProductMediaPanel } from "./ProductMediaPanel";
import { ProductSpecsPanel } from "./ProductSpecsPanel";
import styles from "./ProductKnowledge.module.css";
import { KeywordReviewPanel } from "./KeywordReviewPanel";
import { SellingPointsPanel } from "./SellingPointsPanel";
import {
  ShippingPackagePanel,
  shippingOperationError,
} from "./ShippingPackagePanel";
import { VariantPricesPanel } from "./VariantPricesPanel";
import {
  displayProductKey,
  formatVariantDisplayName,
} from "./display";
import type {
  KMediaAsset,
  KRiskReviewDecision,
  KWorkflowExecution,
  KWorkflowStartPayload,
  ProductKnowledgeDetail,
  ProductKnowledgeListItem,
  ProductKnowledgeVariant,
  ProductReadinessState,
} from "./types";

const TARGET_ORGANIZATION = "涌龙麟（深圳）国际贸易有限公司";
const KEYWORD_STEPS = [
  {
    key: "serp_keyword_fetch",
    label: "SERP",
  },
  {
    key: "ai_filter_chatgpt",
    label: "ChatGPT",
  },
  {
    key: "ai_filter_claude_opus",
    label: "Claude",
  },
] as const;
const WORKFLOW_STEP_ALIASES: Record<string, string[]> = {
  ai_filter_claude_opus: ["ai_filter_claude_opus", "keyword_optimization_ai"],
  risk_term_manual_review: ["risk_term_manual_review", "risk_term_review_manual"],
};
const WORKFLOW_STEP_ORDER = [
  "serp_keyword_fetch",
  "ai_filter_chatgpt",
  "ai_filter_claude_opus",
  "risk_term_manual_review",
] as const;
const WORKFLOW_STEP_INDEX = new Map<string, number>(
  WORKFLOW_STEP_ORDER.flatMap((step, index) =>
    (WORKFLOW_STEP_ALIASES[step] ?? [step]).map(
      (alias): [string, number] => [alias, index],
    ),
  ),
);

type KeywordReviewItem = {
  id?: string;
  keyword: string;
  source: "saved" | "ai" | "manual";
  detail: string;
};
type ProductDetailProps = {
  isGeneratingSellingPoints?: boolean;
  /** 后台卖点生成任务（三阶段 bullets → zh → copy）的最新状态。 */
  sellingPointsJob?: GenerationJob | null;
  isSavingProductInfo?: boolean;
  isWorkflowBusy?: boolean;
  mediaAssets?: KMediaAsset[];
  onApproveSellingPoints?: (sellingPoints: ProductSellingPoints) => Promise<void> | void;
  onBindImage?: (assetId: string, variantSku: string) => void;
  onBindISystemImage?: (imageAssetId: string, variantSku: string) => void;
  onCreateMedia?: (
    file: File,
    variantSku: string,
  ) => Promise<KMediaAsset | void> | KMediaAsset | void;
  onCollapse?: () => void;
  onDeleteMedia?: (assetId: string) => Promise<void> | void;
  onGenerateSellingPoints?: () => void;
  onProductPatched?: (updated: ProductKnowledgeListItem) => void;
  onRefreshWorkflow?: () => void;
  onRetryWorkflowStep?: (
    step: string,
    payload: KWorkflowStartPayload,
  ) => void;
  onSaveProductInfo?: () => Promise<void> | void;
  onStartWorkflow?: (payload: KWorkflowStartPayload) => void;
  onSubmitImages?: () => Promise<void> | void;
  onSubmitRiskReview?: (
    decisions: KRiskReviewDecision[],
    confirmNoRiskTerms: boolean,
  ) => Promise<void> | void;
  product: ProductKnowledgeListItem | null;
  productInfoSaveError?: string;
  readiness?: ProductReadinessState | null;
  sellingPoints?: ProductSellingPoints | null;
  sellingPointsError?: string;
  workflow?: KWorkflowExecution | null;
  workflowError?: string;
};

function displayValue(value: string | null | undefined) {
  return value && value.trim().length > 0 ? value : "未设置";
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "未设置";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function displayReviewStatus(status: string) {
  const labels: Record<string, string> = {
    ai_structured: "AI 已结构化",
    approved: "已通过",
    archived: "已归档",
    blocked: "已阻塞",
    draft: "草稿",
    needs_review: "待审核",
    reviewed: "已审核",
  };

  return labels[status] ?? "待处理";
}

function displayWorkflowRuntimeStatus(status: string | null | undefined) {
  if (!status) {
    return "未启动";
  }

  const labels: Record<string, string> = {
    blocked: "已阻塞",
    created: "已创建",
    exported: "已完成",
    failed: "失败",
    in_progress: "进行中",
    queued: "排队中",
    ready_for_export: "已完成",
    running: "运行中",
    succeeded: "已完成",
  };

  return labels[status] ?? "待处理";
}

function displayProductType(type: string | null | undefined) {
  const labels: Record<string, string> = {
    simple_product: "单产品",
    variable_product: "多变体产品",
  };

  return type ? labels[type] ?? type : "未设置";
}

function workflowAliasesForStep(step: string) {
  return new Set(WORKFLOW_STEP_ALIASES[step] ?? [step]);
}

function workflowStepIndex(step: string) {
  return WORKFLOW_STEP_INDEX.get(step) ?? Number.POSITIVE_INFINITY;
}

function isCompleteStatus(status: string) {
  return ["completed", "succeeded", "ready_for_export", "exported"].includes(
    status,
  );
}

function isActiveStatus(status: string) {
  return ["created", "queued", "running", "in_progress"].includes(status);
}

function workflowStepStatus(workflow: KWorkflowExecution | null, step: string): string {
  if (!workflow) {
    return "pending";
  }

  const aliases = workflowAliasesForStep(step);
  const latest = [...workflow.trace_json]
    .reverse()
    .find((item) => aliases.has(item.step));
  const latestStatus = latest?.status;
  const stepIndex = workflowStepIndex(step);
  const currentIndex = workflowStepIndex(workflow.current_step);

  if (latestStatus === "failed" || latestStatus === "blocked") {
    return latestStatus;
  }
  if (aliases.has(workflow.current_step)) {
    return latestStatus ?? workflow.status;
  }
  if (stepIndex < currentIndex) {
    return latestStatus && isCompleteStatus(latestStatus)
      ? latestStatus
      : "completed";
  }
  if (
    workflow.status === "succeeded" ||
    workflow.status === "ready_for_export" ||
    workflow.status === "exported"
  ) {
    return latestStatus ?? "completed";
  }
  return latestStatus ?? "pending";
}

function workflowStatusLabel(status: string) {
  if (isCompleteStatus(status)) {
    return "已完成";
  }
  if (isActiveStatus(status)) {
    return "进行中";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "blocked") {
    return "阻塞";
  }
  return "等待";
}

function isRetryableStepStatus(status: string) {
  return status === "failed" || status === "blocked";
}

function keywordProgressPercent(
  workflow: KWorkflowExecution | null,
  keywordReviewSubmitted: boolean,
) {
  if (keywordReviewSubmitted || workflow?.risk_approval_log_json) {
    return 100;
  }
  if (!workflow) {
    return 0;
  }

  const statuses = KEYWORD_STEPS.map((step) =>
    workflowStepStatus(workflow, step.key),
  );
  const completed = statuses.filter(isCompleteStatus).length;
  const active = statuses.some(isActiveStatus) ? 0.5 : 0;
  const base = Math.round(((completed + active) / (KEYWORD_STEPS.length + 1)) * 100);
  return Math.min(92, Math.max(12, base));
}

/** 三阶段任务的分步文案。null 表示不在生成中。 */



function normalizeKeywordKey(value: string) {
  return value.trim().toLocaleLowerCase();
}

function dedupeKeywords(values: string[]) {
  const seen = new Set<string>();
  const output: string[] = [];

  for (const value of values) {
    const keyword = value.trim();
    const key = normalizeKeywordKey(keyword);
    if (!keyword || seen.has(key)) {
      continue;
    }
    seen.add(key);
    output.push(keyword);
  }

  return output;
}

function stringListFromUnknown(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => {
      if (typeof item === "string") {
        return item;
      }
      if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        return String(
          record.keyword ??
            record.term ??
            record.text ??
            record.query ??
            "",
        );
      }
      return "";
    })
    .filter((item) => item.trim().length > 0);
}

function normalizeRiskKeywords(workflow: KWorkflowExecution | null) {
  const values = workflow?.claude_filter_result_json?.risk_keywords ?? [];

  return values
    .map((item) => {
      if (typeof item === "string") {
        return { reason: null, term: item };
      }

      return {
        reason: item.reason ?? null,
        term: item.term ?? "",
      };
    })
    .filter((item) => item.term.trim().length > 0);
}

function generatedNonRiskKeywords(workflow: KWorkflowExecution | null) {
  const claude = workflow?.claude_filter_result_json;
  const finalSet = workflow?.final_keyword_set_json;

  return dedupeKeywords([
    ...stringListFromUnknown(claude?.final_keywords),
    ...stringListFromUnknown(claude?.high_value_keywords),
    ...stringListFromUnknown(claude?.low_value_keywords),
    ...stringListFromUnknown(finalSet?.primary_keywords),
    ...stringListFromUnknown(finalSet?.secondary_keywords),
    ...stringListFromUnknown(finalSet?.longtail_keywords),
  ]);
}


export function ProductDetail({
  isGeneratingSellingPoints = false,
  sellingPointsJob = null,
  isSavingProductInfo = false,
  isWorkflowBusy = false,
  mediaAssets = [],
  onApproveSellingPoints,
  onBindImage,
  onBindISystemImage,
  onCreateMedia,
  onCollapse,
  onDeleteMedia,
  onGenerateSellingPoints,
  onProductPatched,
  onRefreshWorkflow,
  onRetryWorkflowStep,
  onSaveProductInfo,
  onStartWorkflow,
  onSubmitImages,
  onSubmitRiskReview,
  product,
  productInfoSaveError = "",
  readiness = null,
  sellingPoints = null,
  sellingPointsError = "",
  workflow = null,
  workflowError = "",
}: ProductDetailProps) {
  // 产品英文名内联编辑（品牌审查撞第三方品牌词时的自救入口）。
  const [isEditingName, setIsEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [isSavingName, setIsSavingName] = useState(false);
  const [nameError, setNameError] = useState("");
  // 取图绑定的乐观状态覆盖 + 忙碌集合
  const [imageSectionSubmitted, setImageSectionSubmitted] = useState(false);
  const [imageSectionTouched, setImageSectionTouched] = useState(false);
  const [keywordReviewSubmitted, setKeywordReviewSubmitted] = useState(false);
  const [keywordSectionTouched, setKeywordSectionTouched] = useState(false);
  const [sellingPointsApproved, setSellingPointsApproved] = useState(false);
  const [sellingPointsTouched, setSellingPointsTouched] = useState(false);
  // 后台三阶段任务的派生状态。
  const sellingPointsStage = sellingPointsJob?.stage ?? null;
  // 详情重拉失败。原来这条错误借运费板块的 shippingError 显示，
  // 那个 state 随面板搬走了；不补这一个就等于把「详情没加载出来」吞掉。
  const [detailError, setDetailError] = useState("");
  const [shippingProduct, setShippingProduct] =
    useState<ProductKnowledgeDetail | null>(null);
  const activeProductIdRef = useRef<string | null>(product?.id ?? null);
  activeProductIdRef.current = product?.id ?? null;

  const refreshProductDetail = useCallback(async (productId: string) => {
    const detail = await getProduct(productId);
    if (activeProductIdRef.current === productId) {
      setShippingProduct(detail);
    }
    return detail;
  }, []);

  const riskKeywords = useMemo(() => normalizeRiskKeywords(workflow), [workflow]);
  const activeMediaAssets = useMemo(
    () => mediaAssets.filter((asset) => asset.status !== "removed"),
    [mediaAssets],
  );
  const keywordProgress = useMemo(
    () => keywordProgressPercent(workflow, keywordReviewSubmitted),
    [keywordReviewSubmitted, workflow],
  );
  const keywordsDirty = Boolean(readiness?.keywords.dirty || keywordSectionTouched);
  const imagesDirty = Boolean(readiness?.images.dirty || imageSectionTouched);
  const sellingPointsDirty = Boolean(
    readiness?.selling_points.dirty || sellingPointsTouched,
  );
  const keywordsComplete = readiness
    ? readiness.keywords.submitted &&
      !keywordsDirty
    : keywordReviewSubmitted || Boolean(workflow?.risk_approval_log_json);
  const imagesComplete = readiness
    ? readiness.images.submitted &&
      !imagesDirty
    : imageSectionSubmitted && activeMediaAssets.length >= 5;
  const sellingPointsComplete = readiness
    ? readiness.selling_points.submitted &&
      !sellingPointsDirty
    : sellingPointsApproved;
  const pSeriesReady = keywordsComplete && imagesComplete && sellingPointsComplete;
  const isWorkflowLive =
    workflow?.status === "created" ||
    workflow?.status === "queued" ||
    workflow?.status === "running" ||
    workflow?.status === "in_progress";

  useEffect(() => {
    const productId = product?.id ?? null;
    activeProductIdRef.current = productId;
    setShippingProduct(null);
    setDetailError("");

    if (!productId) {
      return;
    }

    void refreshProductDetail(productId).catch((error) => {
      if (activeProductIdRef.current === productId) {
        setDetailError(shippingOperationError(error));
      }
    });

    return () => {
      if (activeProductIdRef.current === productId) {
        activeProductIdRef.current = null;
      }
    };
  }, [product?.id, refreshProductDetail]);

  useEffect(() => {
    setImageSectionSubmitted(false);
    setImageSectionTouched(false);
    setKeywordSectionTouched(false);
    setSellingPointsTouched(false);
  }, [product?.id]);

  useEffect(() => {
    if (!isWorkflowLive || !onRefreshWorkflow) {
      return;
    }

    const timer = window.setInterval(() => {
      onRefreshWorkflow();
    }, 5000);

    return () => window.clearInterval(timer);
  }, [isWorkflowLive, onRefreshWorkflow]);

  if (!product) {
    return (
      <aside className={styles.detail} aria-label="产品详情">
        <div className={styles.emptyDetailIcon}>
          <FileText aria-hidden="true" size={22} />
        </div>
        <div>
          <h3>未选择产品</h3>
          <p>从列表选择产品后查看详情。</p>
        </div>
      </aside>
    );
  }
  const currentProduct = product;
  const currentShippingProduct =
    shippingProduct?.id === currentProduct.id ? shippingProduct : null;
  async function saveProductName() {
    if (!product) {
      return;
    }
    const trimmed = nameDraft.trim();
    if (!trimmed) {
      setNameError("产品名不能为空。");
      return;
    }
    setIsSavingName(true);
    setNameError("");
    try {
      const updated = await updateProduct(product.id, {
        product_name_en: trimmed,
      });
      onProductPatched?.(updated);
      setIsEditingName(false);
    } catch (error) {
      setNameError(error instanceof Error ? error.message : "保存失败，请重试。");
    } finally {
      setIsSavingName(false);
    }
  }

  return (
    <aside className={styles.detail} aria-label="产品详情">
      <div className={styles.detailHeading}>
        <div>
          <span className={styles.eyebrow}>详情</span>
          {isEditingName ? (
            <div className={styles.nameEditRow}>
              <input
                aria-label="产品英文名"
                disabled={isSavingName}
                onChange={(event) => setNameDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    void saveProductName();
                  } else if (event.key === "Escape") {
                    setIsEditingName(false);
                    setNameError("");
                  }
                }}
                value={nameDraft}
              />
              <button
                className="primary-button"
                disabled={isSavingName}
                onClick={() => void saveProductName()}
                type="button"
              >
                {isSavingName ? (
                  <LoaderCircle aria-hidden="true" className="spin" size={15} />
                ) : (
                  <Save aria-hidden="true" size={15} />
                )}
                保存
              </button>
              <button
                className="secondary-button"
                disabled={isSavingName}
                onClick={() => {
                  setIsEditingName(false);
                  setNameError("");
                }}
                type="button"
              >
                取消
              </button>
            </div>
          ) : (
            <h3>
              {displayValue(product.product_name_en)}
              <button
                aria-label="编辑产品名"
                className={styles.nameEditButton}
                onClick={() => {
                  setNameDraft(product.product_name_en ?? "");
                  setNameError("");
                  setIsEditingName(true);
                }}
                title="编辑产品英文名"
                type="button"
              >
                <Pencil aria-hidden="true" size={14} />
              </button>
            </h3>
          )}
          {nameError ? (
            <p className={styles.sellingPointsError}>{nameError}</p>
          ) : null}
        </div>
        <div className={styles.detailActions}>
          <span className={styles.statusBadge}>
            {displayReviewStatus(product.review_status)}
          </span>
          <button
            className="secondary-button"
            onClick={onCollapse}
            type="button"
          >
            <ChevronUp aria-hidden="true" size={16} />
            收起
          </button>
        </div>
      </div>

      <dl className={styles.detailGrid}>
        <div>
          <dt>组织</dt>
          <dd>{product.organization_name || TARGET_ORGANIZATION}</dd>
        </div>
        <div>
          <dt>产品编号</dt>
          <dd>{displayProductKey(product.product_key)}</dd>
        </div>
        <div>
          <dt>父级 SKU</dt>
          <dd>{displayValue(product.parent_sku ?? product.sku)}</dd>
        </div>
        <div>
          <dt>品牌</dt>
          <dd>{displayValue(product.brand_name)}</dd>
        </div>
        <div>
          <dt>类型</dt>
          <dd>{displayProductType(product.product_type)}</dd>
        </div>
        <div>
          <dt>变体</dt>
          <dd>{product.variant_count ?? product.variants?.length ?? 0}</dd>
        </div>
        <div>
          <dt>更新</dt>
          <dd>{formatDate(product.updated_at)}</dd>
        </div>
      </dl>

      {(product.variants?.length ?? 0) > 0 ? (
        <VariantPricesPanel
          onProductPatched={onProductPatched}
          product={product}
        />
      ) : null}

      {detailError ? (
        <p className={styles.sellingPointsError} role="alert">
          {detailError}
        </p>
      ) : null}

      {currentShippingProduct ? (
        <ShippingPackagePanel
          key={currentShippingProduct.id}
          onRefreshDetail={refreshProductDetail}
          productDetail={currentShippingProduct}
        />
      ) : null}

      {currentShippingProduct ? (
        <ProductSpecsPanel
          onProductUpdated={(updated) => {
            if (activeProductIdRef.current === updated.id) {
              setShippingProduct(updated);
            }
          }}
          product={currentShippingProduct}
        />
      ) : (
        <section className={styles.workflowSection} aria-labelledby="k-fact-specs">
          <div className={styles.specInlineState}>
            <LoaderCircle aria-hidden="true" className="spin" size={16} />
            正在加载事实规格…
          </div>
        </section>
      )}

      <KeywordReviewPanel
        complete={keywordsComplete}
        dirty={keywordsDirty}
        generatedKeywords={generatedNonRiskKeywords(workflow)}
        isRetryableStepStatus={isRetryableStepStatus}
        isWorkflowBusy={isWorkflowBusy}
        key={currentProduct.id}
        keywordProgress={keywordProgress}
        keywordSteps={KEYWORD_STEPS}
        normalizeKeywordKey={normalizeKeywordKey}
        onRefreshWorkflow={onRefreshWorkflow}
        onRetryWorkflowStep={onRetryWorkflowStep}
        onStartWorkflow={onStartWorkflow}
        onSubmitRiskReview={onSubmitRiskReview}
        onSubmittedChange={setKeywordReviewSubmitted}
        onTouchedChange={setKeywordSectionTouched}
        product={currentProduct}
        productPlaceholder={
          currentProduct.product_name_en ||
          displayProductKey(currentProduct.product_key)
        }
        riskKeywords={riskKeywords}
        runtimeStatusLabel={displayWorkflowRuntimeStatus}
        statusLabel={workflowStatusLabel}
        stepStatus={(step: string) => workflowStepStatus(workflow, step)}
        workflow={workflow ?? null}
        workflowError={workflowError}
      />

      <ProductMediaPanel
        complete={imagesComplete}
        dirty={imagesDirty}
        isWorkflowBusy={isWorkflowBusy}
        key={currentProduct.id}
        mediaAssets={mediaAssets}
        onBindImage={onBindImage}
        onCreateMedia={onCreateMedia}
        onDeleteMedia={onDeleteMedia}
        onSubmitImages={onSubmitImages}
        onSubmittedChange={setImageSectionSubmitted}
        onTouchedChange={setImageSectionTouched}
        product={currentProduct}
        refreshProductDetail={refreshProductDetail}
      />

      <SellingPointsPanel
        complete={sellingPointsComplete}
        dirty={sellingPointsDirty}
        isGeneratingSellingPoints={isGeneratingSellingPoints}
        key={currentProduct.id}
        onApprovedChange={setSellingPointsApproved}
        onApproveSellingPoints={onApproveSellingPoints}
        onGenerateSellingPoints={onGenerateSellingPoints}
        onTouchedChange={setSellingPointsTouched}
        product={currentProduct}
        sellingPoints={sellingPoints}
        sellingPointsError={sellingPointsError}
        sellingPointsJob={sellingPointsJob}
        sellingPointsStage={sellingPointsStage}
      />

      {product ? (
        <CopyArtDirection
          onAssetsSaved={onRefreshWorkflow}
          productId={product.id}
          sku={product.sku}
          channel={(product as { channel?: string | null }).channel ?? null}
        />
      ) : null}

      <section className={styles.workflowSection} aria-labelledby="k-p-readiness">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>P系列</span>
            <h4 id="k-p-readiness">准备状态</h4>
          </div>
          <span className={styles.statusBadge}>
            {pSeriesReady ? "已就绪" : "未就绪"}
          </span>
        </div>
        <div className={styles.readinessGrid}>
          <span data-complete={keywordsComplete}>关键词</span>
          <span data-complete={imagesComplete}>图片</span>
          <span data-complete={sellingPointsComplete}>卖点</span>
        </div>
        {productInfoSaveError ? (
          <p className={styles.sellingPointsError}>{productInfoSaveError}</p>
        ) : null}
        <div className={styles.sectionFooter}>
          <span data-complete={pSeriesReady}>
            {pSeriesReady
              ? "三大板块已完成"
              : "完成并提交关键词、图片和卖点后可保存"}
          </span>
          <button
            className="primary-button"
            disabled={!pSeriesReady || isSavingProductInfo}
            onClick={() => void onSaveProductInfo?.()}
            type="button"
          >
            {isSavingProductInfo ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <Save aria-hidden="true" size={16} />
            )}
            保存商品信息
          </button>
        </div>
      </section>
    </aside>
  );
}
