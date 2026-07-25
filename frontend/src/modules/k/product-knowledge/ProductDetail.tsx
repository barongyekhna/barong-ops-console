"use client";

import {
  CheckCircle2,
  ChevronUp,
  Copy,
  Download,
  ExternalLink,
  FileText,
  ImagePlus,
  LoaderCircle,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  Save,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";

import type { ProductSellingPoints, BulletPoint } from "@/modules/k14/selling-points/types";
import {
  createKeyword,
  deleteKeyword,
  getKeywordsByProduct,
} from "@/modules/k19/keywords/api";
import type { KeywordEntry } from "@/modules/k19/keywords/types";

import {
  assignProductShipping,
  getProduct,
  getShippingClasses,
  mediaAssetFileUrl,
  mediaAssetThumbnailUrl,
  patchProductShipping,
  updateProduct,
  updateVariantPrices,
} from "./api";
import { CopyArtDirection } from "./CopyArtDirection";
import { ProductSpecsPanel } from "./ProductSpecsPanel";
import styles from "./ProductKnowledge.module.css";
import {
  displayProductKey,
  formatVariantDisplayName,
  formatVariantOptionLabel,
  mediaVariantDisplayName,
  variantAttributesFromJson,
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
  WShippingClassOption,
} from "./types";

const TARGET_ORGANIZATION = "涌龙麟（深圳）国际贸易有限公司";
const KEYWORD_RESEARCH_NOT_STARTED_MESSAGE =
  "关键词调研尚未开始，请先启动关键词调研。";
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
const SHIPPING_SELECTION_UNSET = "__shipping-selection-unset__";

type RiskDecisionValue = "approve" | "reject";
type KeywordReviewItem = {
  id?: string;
  keyword: string;
  source: "saved" | "ai" | "manual";
  detail: string;
};
type PendingMediaUpload = {
  id: string;
  fileName: string;
  variantSku: string;
};
type ProductDetailProps = {
  isGeneratingSellingPoints?: boolean;
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

function shippingOperationError(error: unknown) {
  return `运费操作失败：${error instanceof Error ? error.message : ""}`;
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

function displayMediaSource(source: string | null) {
  const labels: Record<string, string> = {
    i_system_asset: "I系统图片",
    manual_upload_image: "手动图片",
  };

  return labels[source ?? ""] ?? "手动图片";
}

function displayMediaStatus(status: string) {
  const labels: Record<string, string> = {
    active: "可用",
    available: "可用",
    bound: "已绑定",
    created: "已创建",
    pending: "待处理",
    rejected: "已拒绝",
    uploaded: "已上传",
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

function sellingPointsProgressPercent(
  sellingPoints: ProductSellingPoints | null,
  isGenerating: boolean,
  approved: boolean,
  hasManualDraft: boolean,
) {
  if (approved) {
    return 100;
  }
  if (sellingPoints || hasManualDraft) {
    return 72;
  }
  if (isGenerating) {
    return 36;
  }
  return 0;
}

function nextManualSellingPointId(bullets: BulletPoint[]) {
  const occupiedIds = new Set(
    bullets.map((bullet) => bullet.id).filter((id): id is string => Boolean(id)),
  );
  let ordinal = 1;
  while (occupiedIds.has(`manual_selling_point_${ordinal}`)) {
    ordinal += 1;
  }
  return `manual_selling_point_${ordinal}`;
}

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

function splitListText(value: string) {
  return value
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinListText(values: string[] | undefined) {
  return (values ?? []).join("\n");
}

function buildISystemHref(
  product: ProductKnowledgeListItem,
  variant: ProductKnowledgeVariant | null,
) {
  const params = new URLSearchParams({
    product_id: product.id,
    source: "k",
  });
  if (variant?.id) {
    params.set("variant_id", variant.id);
  }
  return `/image-system?${params.toString()}`;
}

export function ProductDetail({
  isGeneratingSellingPoints = false,
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
  const [targetMarket, setTargetMarket] = useState("US");
  const [serpQuery, setSerpQuery] = useState("");
  // 产品英文名内联编辑（品牌审查撞第三方品牌词时的自救入口）。
  const [isEditingName, setIsEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [isSavingName, setIsSavingName] = useState(false);
  const [nameError, setNameError] = useState("");
  const [selectedMediaFiles, setSelectedMediaFiles] = useState<File[]>([]);
  const [isDraggingMedia, setIsDraggingMedia] = useState(false);
  const [mediaError, setMediaError] = useState("");
  const [isUploadingMedia, setIsUploadingMedia] = useState(false);
  const [pendingMediaUploads, setPendingMediaUploads] = useState<PendingMediaUpload[]>(
    [],
  );
  const [deletingMediaIds, setDeletingMediaIds] = useState<string[]>([]);
  const [selectedVariantSku, setSelectedVariantSku] = useState("");
  const [imageSectionSubmitted, setImageSectionSubmitted] = useState(false);
  const [imageSectionTouched, setImageSectionTouched] = useState(false);
  const mediaInputRef = useRef<HTMLInputElement | null>(null);
  const [riskDecisions, setRiskDecisions] = useState<Record<string, RiskDecisionValue>>(
    {},
  );
  const [keywordEntries, setKeywordEntries] = useState<KeywordEntry[]>([]);
  const [manualKeywords, setManualKeywords] = useState<string[]>([]);
  const [manualKeywordInput, setManualKeywordInput] = useState("");
  const [removedGeneratedKeywords, setRemovedGeneratedKeywords] = useState<string[]>(
    [],
  );
  const [keywordReviewError, setKeywordReviewError] = useState("");
  const [isLoadingKeywords, setIsLoadingKeywords] = useState(false);
  const [isSavingKeywordReview, setIsSavingKeywordReview] = useState(false);
  const [pendingKeywordRemovalKeys, setPendingKeywordRemovalKeys] = useState<string[]>(
    [],
  );
  const [optimisticRemovedKeywordKeys, setOptimisticRemovedKeywordKeys] = useState<
    string[]
  >([]);
  const [keywordReviewSubmitted, setKeywordReviewSubmitted] = useState(false);
  const [keywordSectionTouched, setKeywordSectionTouched] = useState(false);
  const [sellingBullets, setSellingBullets] = useState<BulletPoint[]>([]);
  const [seoKeywordsText, setSeoKeywordsText] = useState("");
  const [marketTagsText, setMarketTagsText] = useState("");
  const [marketingCopy, setMarketingCopy] = useState("");
  const [translatedVersion, setTranslatedVersion] = useState("");
  const [chineseTranslation, setChineseTranslation] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("");
  const [sellingPointReviewError, setSellingPointReviewError] = useState("");
  const [isSavingSellingPoints, setIsSavingSellingPoints] = useState(false);
  const [sellingPointsApproved, setSellingPointsApproved] = useState(false);
  const [sellingPointsTouched, setSellingPointsTouched] = useState(false);
  const [isEditingSellingPoints, setIsEditingSellingPoints] = useState(false);
  const [sellingPointsCopyStatus, setSellingPointsCopyStatus] = useState("");
  const [variantPriceDrafts, setVariantPriceDrafts] = useState<
    Record<string, string>
  >({});
  const [isSavingVariantPrices, setIsSavingVariantPrices] = useState(false);
  const [variantPriceError, setVariantPriceError] = useState("");
  const [variantPriceStatus, setVariantPriceStatus] = useState("");
  const [shippingProduct, setShippingProduct] =
    useState<ProductKnowledgeDetail | null>(null);
  const [shippingClasses, setShippingClasses] = useState<WShippingClassOption[]>([]);
  const [shippingSelection, setShippingSelection] = useState(
    SHIPPING_SELECTION_UNSET,
  );
  const [shippingError, setShippingError] = useState("");
  const [shippingBusy, setShippingBusy] = useState<
    "save" | "assign" | "battery" | null
  >(null);
  const [packageIncludes, setPackageIncludes] = useState<string[]>([""]);
  const [packageError, setPackageError] = useState("");
  const [packageNotice, setPackageNotice] = useState("");
  const [shippingNotice, setShippingNotice] = useState("");
  const [isSavingPackage, setIsSavingPackage] = useState(false);
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
  const activeVariantCount = product?.variants?.length ?? 0;
  const selectedVariant = useMemo(
    () =>
      (product?.variants ?? []).find(
        (variant) => variant.variant_sku === selectedVariantSku,
      ) ?? null,
    [product?.variants, selectedVariantSku],
  );
  const selectedMediaLabel =
    selectedMediaFiles.length === 0
      ? "拖拽或选择本地图片"
      : selectedMediaFiles.length === 1
        ? selectedMediaFiles[0].name
        : `已选择 ${selectedMediaFiles.length} 张图片`;
  const variantSplitWarning = Boolean(
    product?.product_type === "variable_product" && activeVariantCount <= 1,
  );
  const keywordProgress = useMemo(
    () => keywordProgressPercent(workflow, keywordReviewSubmitted),
    [keywordReviewSubmitted, workflow],
  );
  const sellingPointsProgress = useMemo(
    () =>
      sellingPointsProgressPercent(
        sellingPoints,
        isGeneratingSellingPoints,
        sellingPointsApproved,
        sellingBullets.length > 0,
      ),
    [
      isGeneratingSellingPoints,
      sellingBullets.length,
      sellingPoints,
      sellingPointsApproved,
    ],
  );
  const riskKeywordKeys = useMemo(
    () => new Set(riskKeywords.map((item) => normalizeKeywordKey(item.term))),
    [riskKeywords],
  );
  const activeKeywordEntries = useMemo(
    () =>
      keywordEntries.filter(
        (entry) => entry.status !== "archived",
      ),
    [keywordEntries],
  );
  const nonRiskKeywords = useMemo<KeywordReviewItem[]>(() => {
    const savedKeys = new Set<string>();
    const removedKeys = new Set([
      ...removedGeneratedKeywords,
      ...optimisticRemovedKeywordKeys,
    ]);
    const savedItems = activeKeywordEntries
      .filter((entry) => !riskKeywordKeys.has(normalizeKeywordKey(entry.keyword)))
      .map((entry) => {
        savedKeys.add(normalizeKeywordKey(entry.keyword));
        return {
          detail: entry.source === "manual" ? "人工保存" : "已保存",
          id: entry.id,
          keyword: entry.keyword,
          source: "saved" as const,
        };
      });
    const aiItems = generatedNonRiskKeywords(workflow)
      .filter((keyword) => {
        const key = normalizeKeywordKey(keyword);
        return !savedKeys.has(key) && !riskKeywordKeys.has(key) && !removedKeys.has(key);
      })
      .map((keyword) => ({
        detail: "Claude 终筛",
        keyword,
        source: "ai" as const,
      }));
    const manualItems = manualKeywords
      .filter((keyword) => {
        const key = normalizeKeywordKey(keyword);
        return !savedKeys.has(key) && !riskKeywordKeys.has(key) && !removedKeys.has(key);
      })
      .map((keyword) => ({
        detail: "人工新增",
        keyword,
        source: "manual" as const,
      }));

    return [...savedItems, ...aiItems, ...manualItems];
  }, [
    activeKeywordEntries,
    manualKeywords,
    removedGeneratedKeywords,
    optimisticRemovedKeywordKeys,
    riskKeywordKeys,
    workflow,
  ]);
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
    setShippingClasses([]);
    setShippingSelection(SHIPPING_SELECTION_UNSET);
    setShippingError("");
    setShippingBusy(null);

    if (!productId) {
      return;
    }

    void refreshProductDetail(productId).catch((error) => {
      if (activeProductIdRef.current === productId) {
        setShippingError(shippingOperationError(error));
      }
    });

    return () => {
      if (activeProductIdRef.current === productId) {
        activeProductIdRef.current = null;
      }
    };
  }, [product?.id, refreshProductDetail]);

  useEffect(() => {
    if (
      !shippingProduct ||
      shippingProduct.id !== product?.id ||
      shippingProduct.channel !== "dtc"
    ) {
      return;
    }

    let cancelled = false;
    void getShippingClasses()
      .then((items) => {
        if (!cancelled) {
          setShippingClasses(items.filter((item) => item.active));
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setShippingError(shippingOperationError(error));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [product?.id, shippingProduct?.channel, shippingProduct?.id]);

  useEffect(() => {
    const items = Array.isArray(shippingProduct?.package_includes_json)
      ? shippingProduct.package_includes_json.filter(
          (item): item is string => typeof item === "string",
        )
      : [];
    setPackageIncludes(items.length > 0 ? items : [""]);
    setPackageError("");
  }, [shippingProduct?.id, shippingProduct?.package_includes_json]);

  const loadKeywordEntries = useCallback(async () => {
    if (!product) {
      setKeywordEntries([]);
      return;
    }

    setIsLoadingKeywords(true);
    try {
      const response = await getKeywordsByProduct(product.id);
      setKeywordEntries(response.keyword_entries);
    } catch (error) {
      setKeywordReviewError(
        error instanceof Error ? error.message : "关键词列表加载失败。",
      );
    } finally {
      setIsLoadingKeywords(false);
    }
  }, [product]);

  useEffect(() => {
    void loadKeywordEntries();
  }, [loadKeywordEntries]);

  useEffect(() => {
    setRiskDecisions({});
    setKeywordReviewError("");
    setKeywordReviewSubmitted(Boolean(workflow?.risk_approval_log_json));
  }, [workflow?.id, workflow?.risk_approval_log_json]);

  useEffect(() => {
    const firstVariantSku = product?.variants?.[0]?.variant_sku ?? "";
    setSelectedVariantSku(firstVariantSku);
    setTargetMarket(product?.target_market ?? "US");
    setSelectedMediaFiles([]);
    setMediaError("");
    setPendingMediaUploads([]);
    setDeletingMediaIds([]);
    setImageSectionSubmitted(false);
    setManualKeywords([]);
    setManualKeywordInput("");
    setRemovedGeneratedKeywords([]);
    setOptimisticRemovedKeywordKeys([]);
    setPendingKeywordRemovalKeys([]);
    setImageSectionTouched(false);
    setKeywordSectionTouched(false);
    setSellingPointsTouched(false);
    setSellingBullets([]);
    setIsEditingSellingPoints(false);
    setSellingPointsCopyStatus("");
  }, [product?.id]);

  useEffect(() => {
    if (!sellingPoints) {
      setSellingBullets([]);
      setSeoKeywordsText("");
      setMarketTagsText("");
      setMarketingCopy("");
      setTranslatedVersion("");
      setChineseTranslation("");
      setTargetLanguage("");
      setSellingPointsApproved(false);
      setSellingPointsTouched(false);
      setSellingPointsCopyStatus("");
      return;
    }

    setSellingBullets(
      sellingPoints.bullets.map((bullet) => ({
        ...bullet,
        evidence: bullet.evidence ?? "",
        review_decision:
          bullet.review_decision ??
          (sellingPoints.source === "manual_review" ? "approve" : "candidate"),
        verification_status: bullet.verification_status ?? "unverified",
      })),
    );
    setSeoKeywordsText(joinListText(sellingPoints.seo_keywords));
    setMarketTagsText(joinListText(sellingPoints.market_tags));
    setMarketingCopy(sellingPoints.marketing_copy ?? "");
    setTranslatedVersion(sellingPoints.translated_version ?? "");
    setChineseTranslation(sellingPoints.chinese_translation ?? "");
    setTargetLanguage(sellingPoints.target_language ?? sellingPoints.language ?? "");
    setSellingPointsApproved(sellingPoints.source === "manual_review");
    setSellingPointsTouched(false);
    setSellingPointsCopyStatus("");
  }, [sellingPoints]);

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
  const hasSellingPointsDraft = Boolean(sellingPoints) || sellingBullets.length > 0;
  const currentShippingProduct =
    shippingProduct?.id === currentProduct.id ? shippingProduct : null;
  const shippingClassName = currentShippingProduct?.shipping_class
    ? shippingClasses.find(
        (shippingClass) =>
          shippingClass.slug === currentShippingProduct.shipping_class,
      )?.name ?? currentShippingProduct.shipping_class
    : null;

  function updatePackageItem(index: number, value: string) {
    setPackageIncludes((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? value : item)),
    );
    setPackageError("");
    setPackageNotice("");
  }

  async function savePackageIncludes() {
    const populated = packageIncludes.map((item) => item.trim()).filter(Boolean);
    if (populated.some((item) => /[\u3400-\u9fff]/u.test(item))) {
      setPackageError("包装清单必须逐项使用英文，不能包含中文。");
      return;
    }
    setIsSavingPackage(true);
    setPackageError("");
    try {
      await updateProduct(currentProduct.id, {
        package_includes_json: populated.length > 0 ? populated : null,
      });
      await refreshProductDetail(currentProduct.id);
      setPackageNotice("包装清单已保存 ✓");
    } catch (error) {
      setPackageError(
        error instanceof Error ? error.message : "包装清单保存失败。",
      );
    } finally {
      setIsSavingPackage(false);
    }
  }

  async function saveShippingAssignment() {
    if (!currentShippingProduct || shippingSelection === SHIPPING_SELECTION_UNSET) {
      return;
    }

    const productId = currentShippingProduct.id;
    setShippingBusy("save");
    setShippingError("");
    try {
      await patchProductShipping(
        productId,
        shippingSelection
          ? {
              clear_review: true,
              shipping_class_slug: shippingSelection,
            }
          : {
              clear_review: false,
              shipping_class_slug: null,
            },
      );
      await refreshProductDetail(productId);
      if (activeProductIdRef.current === productId) {
        setShippingSelection(SHIPPING_SELECTION_UNSET);
        setShippingNotice("运费模板已保存 ✓");
      }
    } catch (error) {
      if (activeProductIdRef.current === productId) {
        setShippingNotice("");
        setShippingError(shippingOperationError(error));
      }
    } finally {
      if (activeProductIdRef.current === productId) {
        setShippingBusy(null);
      }
    }
  }

  async function reassignShipping() {
    if (!currentShippingProduct) {
      return;
    }

    const productId = currentShippingProduct.id;
    setShippingBusy("assign");
    setShippingError("");
    try {
      await assignProductShipping(productId);
      await refreshProductDetail(productId);
    } catch (error) {
      if (activeProductIdRef.current === productId) {
        setShippingError(shippingOperationError(error));
      }
    } finally {
      if (activeProductIdRef.current === productId) {
        setShippingBusy(null);
      }
    }
  }

  async function setContainsBattery(containsBattery: boolean) {
    if (!currentShippingProduct) {
      return;
    }

    const productId = currentShippingProduct.id;
    setShippingBusy("battery");
    setShippingError("");
    try {
      await patchProductShipping(productId, {
        contains_battery: containsBattery,
      });
      await refreshProductDetail(productId);
    } catch (error) {
      if (activeProductIdRef.current === productId) {
        setShippingError(shippingOperationError(error));
      }
    } finally {
      if (activeProductIdRef.current === productId) {
        setShippingBusy(null);
      }
    }
  }

  function buildWorkflowPayload(): KWorkflowStartPayload {
    const mainKeyword =
      currentProduct.main_keyword ?? currentProduct.primary_keyword ?? "";
    return {
      main_keyword: mainKeyword,
      seed_keywords: [],
      serp_query: serpQuery.trim() || mainKeyword || null,
      target_market: targetMarket,
    };
  }

  function submitWorkflowStart() {
    setKeywordSectionTouched(true);
    setKeywordReviewSubmitted(false);
    onStartWorkflow?.(buildWorkflowPayload());
  }

  function retryWorkflowStep(step: string) {
    setKeywordSectionTouched(true);
    setKeywordReviewSubmitted(false);
    onRetryWorkflowStep?.(step, buildWorkflowPayload());
  }

  function setUploadFiles(files: File[]) {
    if (files.length === 0) {
      return;
    }
    const invalidFile = files.find(
      (file) => file.type && !file.type.startsWith("image/"),
    );
    if (invalidFile) {
      setMediaError("只能上传图片文件。");
      return;
    }
    setMediaError("");
    setSelectedMediaFiles(files);
  }

  function handleMediaDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDraggingMedia(false);
    setUploadFiles(Array.from(event.dataTransfer.files));
  }

  async function createMedia() {
    if (selectedMediaFiles.length === 0) {
      setMediaError("请选择本地图片文件。");
      return;
    }
    if (!selectedVariantSku) {
      setMediaError("请选择图片绑定变体。");
      return;
    }
    const uploadBatch = selectedMediaFiles.map((file, index) => ({
      file,
      id: `${Date.now()}-${index}-${file.name}`,
    }));
    setPendingMediaUploads((current) => [
      ...uploadBatch.map((item) => ({
        fileName: item.file.name,
        id: item.id,
        variantSku: selectedVariantSku,
      })),
      ...current,
    ]);
    setIsUploadingMedia(true);
    setMediaError("");
    try {
      for (const item of uploadBatch) {
        await onCreateMedia?.(item.file, selectedVariantSku);
        setPendingMediaUploads((current) =>
          current.filter((pending) => pending.id !== item.id),
        );
      }
      setSelectedMediaFiles([]);
      if (mediaInputRef.current) {
        mediaInputRef.current.value = "";
      }
      setImageSectionTouched(true);
      setImageSectionSubmitted(false);
    } catch (error) {
      setMediaError(error instanceof Error ? error.message : "图片上传失败。");
    } finally {
      setPendingMediaUploads((current) =>
        current.filter((pending) =>
          uploadBatch.every((item) => item.id !== pending.id),
        ),
      );
      setIsUploadingMedia(false);
    }
  }

  async function deleteMedia(assetId: string) {
    setDeletingMediaIds((current) =>
      current.includes(assetId) ? current : [...current, assetId],
    );
    setMediaError("");
    try {
      await onDeleteMedia?.(assetId);
      setImageSectionTouched(true);
      setImageSectionSubmitted(false);
    } catch (error) {
      setMediaError(error instanceof Error ? error.message : "图片删除失败。");
    } finally {
      setDeletingMediaIds((current) =>
        current.filter((currentId) => currentId !== assetId),
      );
    }
  }

  function bindUploadedImage(assetId: string, variantSku: string) {
    setImageSectionTouched(true);
    setImageSectionSubmitted(false);
    onBindImage?.(assetId, variantSku);
  }

  function addManualKeyword() {
    const keyword = manualKeywordInput.trim();
    if (!keyword) {
      return;
    }
    const existing = new Set(nonRiskKeywords.map((item) => normalizeKeywordKey(item.keyword)));
    if (existing.has(normalizeKeywordKey(keyword))) {
      setKeywordReviewError("这个关键词已在非风险关键词列表中。");
      return;
    }
    setManualKeywords((current) => [...current, keyword]);
    setManualKeywordInput("");
    setKeywordSectionTouched(true);
    setKeywordReviewError("");
  }

  async function removeKeyword(item: KeywordReviewItem) {
    const key = normalizeKeywordKey(item.keyword);
    if (pendingKeywordRemovalKeys.includes(key)) {
      return;
    }
    if (item.source !== "saved") {
      setOptimisticRemovedKeywordKeys((current) =>
        current.includes(key) ? current : [...current, key],
      );
    }
    setPendingKeywordRemovalKeys((current) =>
      current.includes(key) ? current : [...current, key],
    );
    setKeywordReviewError("");
    setKeywordSectionTouched(true);
    if (item.source === "saved" && item.id) {
      try {
        await deleteKeyword(item.id);
        await loadKeywordEntries();
      } catch (error) {
        setOptimisticRemovedKeywordKeys((current) =>
          current.filter((currentKey) => currentKey !== key),
        );
        setKeywordReviewError(
          error instanceof Error ? error.message : "关键词移除失败。",
        );
      } finally {
        setPendingKeywordRemovalKeys((current) =>
          current.filter((currentKey) => currentKey !== key),
        );
      }
      return;
    }
    if (item.source === "manual") {
      setManualKeywords((current) =>
        current.filter((keyword) => normalizeKeywordKey(keyword) !== key),
      );
      setPendingKeywordRemovalKeys((current) =>
        current.filter((currentKey) => currentKey !== key),
      );
      return;
    }
    setRemovedGeneratedKeywords((current) =>
      current.includes(key) ? current : [...current, key],
    );
    setPendingKeywordRemovalKeys((current) =>
      current.filter((currentKey) => currentKey !== key),
    );
  }

  async function submitKeywordReview() {
    const missingRiskDecisions = riskKeywords.filter(
      (item) => !riskDecisions[item.term],
    );
    if (missingRiskDecisions.length > 0) {
      setKeywordReviewError("每个风险词都需要人工选择通过或拒绝。");
      return;
    }
    if (nonRiskKeywords.length === 0) {
      setKeywordReviewError(
        workflow
          ? "请至少保留一个非风险关键词。"
          : KEYWORD_RESEARCH_NOT_STARTED_MESSAGE,
      );
      return;
    }

    setIsSavingKeywordReview(true);
    setKeywordReviewError("");
    try {
      const savedKeys = new Set(
        activeKeywordEntries.map((entry) => normalizeKeywordKey(entry.keyword)),
      );
      const newKeywords = nonRiskKeywords.filter(
        (item) => !item.id && !savedKeys.has(normalizeKeywordKey(item.keyword)),
      );
      await Promise.all(
        newKeywords.map((item) =>
          createKeyword({
            keyword: item.keyword,
            product_id: currentProduct.id,
            source: item.source === "manual" ? "manual" : "K18",
            status: "active",
          }),
        ),
      );
      await onSubmitRiskReview?.(
        riskKeywords.map((item) => {
          const decision = riskDecisions[item.term] as RiskDecisionValue;

          return {
            decision,
            reason: decision === "reject" ? "Rejected in manual review" : null,
            term: item.term,
          };
        }),
        riskKeywords.length === 0,
      );

      await loadKeywordEntries();
      setManualKeywords([]);
      setKeywordSectionTouched(false);
      setKeywordReviewSubmitted(true);
    } catch (error) {
      setKeywordReviewError(
        error instanceof Error ? error.message : "关键词审核保存失败。",
      );
    } finally {
      setIsSavingKeywordReview(false);
    }
  }

  function updateBullet(index: number, patch: Partial<BulletPoint>) {
    setSellingPointsTouched(true);
    setSellingBullets((current) =>
      current.map((bullet, bulletIndex) =>
        bulletIndex === index ? { ...bullet, ...patch } : bullet,
      ),
    );
  }

  function addManualSellingPoint() {
    setSellingPointsTouched(true);
    setSellingPointsApproved(false);
    setSellingPointReviewError("");
    setIsEditingSellingPoints(true);
    setSellingBullets((current) => [
      ...current,
      {
        category: "benefit",
        evidence: "operator_fact",
        evidence_excerpt: "",
        id: nextManualSellingPointId(current),
        importance_score: 1,
        review_decision: "approve",
        text: "",
        verification_status: "unverified",
      },
    ]);
  }

  function removeSellingPoint(index: number) {
    setSellingPointsTouched(true);
    setSellingPointsApproved(false);
    setSellingPointReviewError("");
    setSellingBullets((current) =>
      current.filter((_, bulletIndex) => bulletIndex !== index),
    );
  }

  async function submitSellingPointsReview() {
    if (sellingBullets.length === 0) {
      setSellingPointReviewError("请至少新增一条卖点，再进行人工审核。");
      return;
    }
    const cleanedBullets = sellingBullets
      .map((bullet) => ({
        ...bullet,
        category: bullet.category.trim() || "conversion",
        importance_score: Number.isFinite(Number(bullet.importance_score))
          ? Number(bullet.importance_score)
          : 1,
        text: bullet.text.trim(),
        evidence: bullet.evidence?.trim() || null,
        evidence_excerpt:
          bullet.evidence_excerpt?.trim() ||
          (bullet.evidence?.trim() === "operator_fact" ? bullet.text.trim() : null),
        review_decision: bullet.review_decision ?? "candidate",
      }))
      .filter((bullet) => bullet.text.length > 0);
    if (cleanedBullets.length === 0) {
      setSellingPointReviewError("请至少保留一条卖点。");
      return;
    }
    const undecided = cleanedBullets.filter(
      (bullet) => (bullet.review_decision ?? "candidate") === "candidate",
    );
    if (undecided.length > 0) {
      setSellingPointReviewError("请逐条选择通过、编辑后通过或拒绝。");
      return;
    }
    const missingEvidence = cleanedBullets.filter(
      (bullet) =>
        bullet.review_decision !== "reject" && !bullet.evidence?.trim(),
    );
    if (missingEvidence.length > 0) {
      setSellingPointReviewError(
        "保留的每条卖点都必须填写 spec:<字段>、verified_feature:<ID> 或 operator_fact 证据。",
      );
      return;
    }

    setIsSavingSellingPoints(true);
    setSellingPointReviewError("");
    try {
      const baseSellingPoints: ProductSellingPoints = sellingPoints ?? {
        bullets: [],
        confidence_score: 1,
        language: targetLanguage.trim() || "en",
        market_tags: [],
        product_id: currentProduct.id,
        raw_input: "",
        seo_bullets: [],
        seo_keywords: [],
        source: "manual_input",
        title:
          currentProduct.product_name_en ??
          displayProductKey(currentProduct.product_key),
      };
      await onApproveSellingPoints?.({
        ...baseSellingPoints,
        bullets: cleanedBullets,
        confidence_score: baseSellingPoints.confidence_score ?? 1,
        chinese_translation: chineseTranslation.trim() || null,
        language: baseSellingPoints.language ?? (targetLanguage || "en"),
        market_tags: splitListText(marketTagsText),
        marketing_copy: marketingCopy.trim() || null,
        product_id: baseSellingPoints.product_id ?? currentProduct.id,
        raw_input: baseSellingPoints.raw_input ?? "",
        seo_bullets: baseSellingPoints.seo_bullets ?? [],
        seo_keywords: splitListText(seoKeywordsText),
        source: "manual_review",
        target_language:
          targetLanguage.trim() || baseSellingPoints.target_language,
        title:
          baseSellingPoints.title ??
          currentProduct.product_name_en ??
          displayProductKey(currentProduct.product_key),
        translated_version: translatedVersion.trim() || null,
      });
      setSellingPointsApproved(true);
      setSellingPointsTouched(false);
    } catch (error) {
      setSellingPointReviewError(
        error instanceof Error ? error.message : "卖点审核保存失败。",
      );
    } finally {
      setIsSavingSellingPoints(false);
    }
  }

  function buildSellingPointsCopyText() {
    const lines = [
      currentProduct.product_name_en ||
        displayProductKey(currentProduct.product_key),
      "",
      "卖点",
      ...sellingBullets.map((bullet, index) => {
        const category = bullet.category.trim() || "conversion";
        return `${index + 1}. [${category}] ${bullet.text.trim()}`;
      }),
      "",
      "SEO关键词",
      ...splitListText(seoKeywordsText).map((keyword) => `- ${keyword}`),
      "",
      "市场标签",
      ...splitListText(marketTagsText).map((tag) => `- ${tag}`),
      "",
      "转化文案",
      marketingCopy.trim(),
      "",
      "目标市场译文",
      translatedVersion.trim(),
      "",
      "中文翻译",
      chineseTranslation.trim(),
    ];

    return lines
      .filter((line, index, allLines) => {
        if (line.trim()) {
          return true;
        }
        return index > 0 && index < allLines.length - 1;
      })
      .join("\n");
  }

  async function copySellingPoints() {
    const text = buildSellingPointsCopyText();
    if (!text.trim()) {
      return;
    }

    try {
      await navigator.clipboard.writeText(text);
      setSellingPointsCopyStatus("已复制");
    } catch {
      setSellingPointsCopyStatus("复制失败");
    }
  }

  async function submitImageSection() {
    if (activeMediaAssets.length < 5) {
      setMediaError("请至少上传 5 张图片后再提交图片。");
      return;
    }

    setMediaError("");
    try {
      await onSubmitImages?.();
      setImageSectionTouched(false);
      setImageSectionSubmitted(true);
    } catch (error) {
      setMediaError(error instanceof Error ? error.message : "图片提交失败。");
    }
  }

  const iSystemHref = buildISystemHref(currentProduct, selectedVariant);

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

  async function saveVariantPrices() {
    if (!product) {
      return;
    }
    const variants = product.variants ?? [];
    const items: { variant_id: string; price_override: number }[] = [];
    for (const variant of variants) {
      const draft = variantPriceDrafts[variant.id];
      if (draft === undefined) {
        continue;
      }
      const trimmed = draft.trim();
      if (!trimmed) {
        setVariantPriceError("变体价格不能留空——多变体产品每个变体都必须有价。");
        return;
      }
      const parsed = Number(trimmed);
      if (!Number.isFinite(parsed) || parsed < 0) {
        setVariantPriceError(`「${formatVariantDisplayName(variant)}」的价格不是有效数字。`);
        return;
      }
      const current = variant.price_override;
      if (current !== null && Math.abs(current - parsed) < 0.005) {
        continue;
      }
      items.push({ price_override: parsed, variant_id: variant.id });
    }
    if (!items.length) {
      setVariantPriceError("");
      setVariantPriceStatus("没有改动。");
      return;
    }
    setIsSavingVariantPrices(true);
    setVariantPriceError("");
    setVariantPriceStatus("");
    try {
      await updateVariantPrices(product.id, items);
      const refreshed = await getProduct(product.id);
      onProductPatched?.(refreshed);
      setVariantPriceDrafts({});
      setVariantPriceStatus(`已保存 ${items.length} 个变体的价格。`);
    } catch (error) {
      setVariantPriceError(
        error instanceof Error ? error.message : "保存失败，请重试。",
      );
    } finally {
      setIsSavingVariantPrices(false);
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
        <section className={styles.workflowSection} aria-labelledby="k-variant-prices">
          <div className={styles.sellingPointsHeading}>
            <div>
              <h4 id="k-variant-prices">变体价格核对</h4>
              <p className={styles.sectionHint}>
                {product.product_type === "variable_product"
                  ? "多变体产品的价格全部按变体走（父级价格留空）。逐行核对，改完点保存。"
                  : "核对该产品的定价，改完点保存。"}
              </p>
            </div>
          </div>

          <div className={styles.variantPriceTableWrap}>
            <table className={styles.variantPriceTable}>
              <thead>
                <tr>
                  <th scope="col">变体</th>
                  <th scope="col">SKU</th>
                  {/* 站点单一币种结算,读取接口也不返 price_currency */}
                  <th scope="col">价格（USD）</th>
                </tr>
              </thead>
              <tbody>
                {(product.variants ?? []).map((variant) => {
                  const draft = variantPriceDrafts[variant.id];
                  const stored =
                    variant.price_override === null
                      ? ""
                      : String(variant.price_override);
                  const value = draft === undefined ? stored : draft;
                  const missing = value.trim() === "";
                  const changed = draft !== undefined && draft.trim() !== stored;
                  return (
                    <tr key={variant.id}>
                      <td>
                        <strong>{formatVariantDisplayName(variant)}</strong>
                      </td>
                      <td className={styles.variantPriceSku}>
                        {variant.variant_sku}
                      </td>
                      <td>
                        <div className={styles.variantPriceCell}>
                          <input
                            aria-label={`${formatVariantDisplayName(variant)} 的价格`}
                            data-missing={missing}
                            disabled={isSavingVariantPrices}
                            inputMode="decimal"
                            min={0}
                            onChange={(event) => {
                              setVariantPriceStatus("");
                              setVariantPriceDrafts((previous) => ({
                                ...previous,
                                [variant.id]: event.target.value,
                              }));
                            }}
                            placeholder="未设置"
                            step={0.01}
                            type="number"
                            value={value}
                          />
                          {missing ? (
                            <span
                              className={styles.variantPriceFlag}
                              data-tone="bad"
                            >
                              未设置
                            </span>
                          ) : null}
                          {changed ? (
                            <span
                              className={styles.variantPriceFlag}
                              data-tone="changed"
                            >
                              待保存
                            </span>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {variantPriceError ? (
            <p className={styles.sellingPointsError} role="alert">
              {variantPriceError}
            </p>
          ) : null}

          <div className={styles.variantPriceActions}>
            {variantPriceStatus ? (
              <span className={styles.variantPriceStatus}>{variantPriceStatus}</span>
            ) : null}
            <button
              className="secondary-button"
              disabled={
                isSavingVariantPrices ||
                Object.keys(variantPriceDrafts).length === 0
              }
              onClick={() => void saveVariantPrices()}
              type="button"
            >
              <CheckCircle2 aria-hidden="true" size={15} />
              {isSavingVariantPrices ? "保存中…" : "保存价格"}
            </button>
          </div>
        </section>
      ) : null}

      {currentShippingProduct?.channel === "dtc" ? (
        <section className={styles.workflowSection} aria-labelledby="k-shipping">
          <div className={styles.sellingPointsHeading}>
            <div>
              <h4 id="k-shipping">运费（独立站）</h4>
            </div>
          </div>

          <div className={styles.workflowMetrics}>
            <div>
              <dd>
                {shippingClassName ? (
                  <>
                    {shippingClassName}{" "}
                    <span className={styles.statusBadge}>
                      {currentShippingProduct.shipping_assignment?.rule_type
                        ? "规则判定"
                        : "手动指定"}
                    </span>
                  </>
                ) : (
                  "未分配——P 系列上架前必须解决"
                )}
              </dd>
            </div>
            {currentShippingProduct.shipping_review_needed ? (
              <div>
                <dd>
                  待复核：
                  {currentShippingProduct.shipping_assignment?.review_reason ||
                    "缺少判定依据"}
                </dd>
              </div>
            ) : null}
          </div>

          {currentShippingProduct.shipping_assignment?.used_kg != null ? (
            <p className={styles.sellingPointsEmpty}>
              判定重量 {currentShippingProduct.shipping_assignment.used_kg} kg
            </p>
          ) : null}

          <div className={styles.workflowStartGrid}>
            <label className={styles.field}>
              <select
                aria-label="选择运费类…"
                disabled={shippingBusy !== null}
                onChange={(event) => setShippingSelection(event.target.value)}
                value={shippingSelection}
              >
                <option disabled value={SHIPPING_SELECTION_UNSET}>
                  选择运费类…
                </option>
                <option value="">（清除指定）</option>
                {shippingClasses.map((shippingClass) => (
                  <option key={shippingClass.id} value={shippingClass.slug}>
                    {shippingClass.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="secondary-button"
              disabled={
                shippingBusy !== null ||
                shippingSelection === SHIPPING_SELECTION_UNSET
              }
              onClick={() => void saveShippingAssignment()}
              type="button"
            >
              {shippingBusy === "save" ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <Save aria-hidden="true" size={16} />
              )}
              保存指定
            </button>
            <button
              className="secondary-button"
              disabled={shippingBusy !== null}
              onClick={() => void reassignShipping()}
              type="button"
            >
              {shippingBusy === "assign" ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <RotateCcw aria-hidden="true" size={16} />
              )}
              按规则重判
            </button>
          </div>

          <div className={styles.workflowMetrics}>
            <div>
              <label>
                <input
                  checked={Boolean(currentShippingProduct.contains_battery)}
                  disabled={shippingBusy !== null}
                  onChange={(event) =>
                    void setContainsBattery(event.target.checked)
                  }
                  type="checkbox"
                />{" "}
                含电池（命中电池规则）
              </label>
            </div>
          </div>

          {shippingError ? (
            <p className={styles.sellingPointsError}>{shippingError}</p>
          ) : null}
          {shippingNotice ? (
            <p className={styles.spSaveNotice} role="status">{shippingNotice}</p>
          ) : null}
        </section>
      ) : null}

      <section className={styles.workflowSection} aria-labelledby="k-package-includes">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>套装证据</span>
            <h4 id="k-package-includes">包装清单 (What's in the box)</h4>
          </div>
          <button
            className="secondary-button"
            onClick={() => setPackageIncludes((current) => [...current, ""])}
            type="button"
          >
            <Plus aria-hidden="true" size={15} />
            添加组件
          </button>
        </div>
        <p className={styles.keywordAiNotice}>
          每行一个已核实的组件，必须用英文；件数声明将严格按此清单校验。
        </p>
        {packageIncludes.map((item, index) => (
          <div className={styles.workflowStartGrid} key={`package-item-${index}`}>
            <label className={styles.field}>
              <span>组件 {index + 1}</span>
              <input
                lang="en"
                onChange={(event) => updatePackageItem(index, event.target.value)}
                placeholder="e.g. 1.5 qt pot"
                value={item}
              />
            </label>
            <button
              className="secondary-button"
              disabled={packageIncludes.length <= 1}
              onClick={() =>
                setPackageIncludes((current) =>
                  current.filter((_, itemIndex) => itemIndex !== index),
                )
              }
              type="button"
            >
              删除
            </button>
          </div>
        ))}
        {packageError ? (
          <p className={styles.sellingPointsError}>{packageError}</p>
        ) : null}
        {packageNotice ? (
          <p className={styles.spSaveNotice} role="status">{packageNotice}</p>
        ) : null}
        <div className={styles.sectionFooter}>
          <span>留空表示未知，不会自动补齐或猜测组件。</span>
          <button
            className="primary-button"
            disabled={isSavingPackage}
            onClick={() => void savePackageIncludes()}
            type="button"
          >
            {isSavingPackage ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <Save aria-hidden="true" size={16} />
            )}
            保存包装清单
          </button>
        </div>
      </section>

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

      <section className={styles.workflowSection} aria-labelledby="k-keywords">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>关键词</span>
            <h4 id="k-keywords">关键词审核</h4>
          </div>
          <button
            className="secondary-button"
            disabled={isWorkflowBusy}
            onClick={onRefreshWorkflow}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={16} />
            刷新
          </button>
        </div>

        {workflowError ? (
          <p className={styles.sellingPointsError}>{workflowError}</p>
        ) : null}

        <div className={styles.workflowMetrics}>
          <div>
            <dt>状态</dt>
            <dd>{displayWorkflowRuntimeStatus(workflow?.status)}</dd>
          </div>
          <div>
            <dt>进度</dt>
            <dd>{keywordProgress}%</dd>
          </div>
        </div>

        <div
          aria-label="关键词进度"
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={keywordProgress}
          className={styles.workflowProgress}
          role="progressbar"
        >
          <span style={{ width: `${keywordProgress}%` }} />
        </div>

        <ol className={styles.workflowStages}>
          {KEYWORD_STEPS.map((step) => {
            const status = workflowStepStatus(workflow, step.key);
            const canRetry = isRetryableStepStatus(status);

            return (
              <li data-status={status} key={step.key}>
                <div>
                  <span>{step.label}</span>
                  <strong>{workflowStatusLabel(status)}</strong>
                </div>
                <button
                  className="secondary-button"
                  disabled={!canRetry || isWorkflowBusy}
                  onClick={() => retryWorkflowStep(step.key)}
                  type="button"
                >
                  {isWorkflowBusy && canRetry ? (
                    <LoaderCircle aria-hidden="true" className="spin" size={14} />
                  ) : (
                    <RotateCcw aria-hidden="true" size={14} />
                  )}
                  重试
                </button>
              </li>
            );
          })}
        </ol>
        <p className={styles.keywordAiNotice}>
          AI 调用可能失败，请点击对应步骤重试。
        </p>

        <div className={styles.workflowStartGrid}>
          <label className={styles.field}>
            <span>目标市场</span>
            <select
              onChange={(event) => setTargetMarket(event.target.value)}
              value={targetMarket}
            >
              <option value="US">美国</option>
              <option value="UK">英国</option>
              <option value="EU">欧盟</option>
              <option value="CN">中国</option>
              <option value="JP">日本</option>
              <option value="KR">韩国</option>
              <option value="RU">俄罗斯</option>
              <option value="GCC">中东</option>
              <option value="LATAM">拉美</option>
            </select>
          </label>
          <label className={styles.field}>
            <span>关键词查询</span>
            <input
              onChange={(event) => setSerpQuery(event.target.value)}
              placeholder={product.product_name_en || displayProductKey(product.product_key)}
              value={serpQuery}
            />
          </label>
          <button
            className="primary-button"
            disabled={isWorkflowBusy}
            onClick={submitWorkflowStart}
            type="button"
          >
            {isWorkflowBusy ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <Play aria-hidden="true" size={16} />
            )}
            启动关键词调研
          </button>
        </div>

        {keywordReviewError ? (
          <p className={styles.sellingPointsError}>{keywordReviewError}</p>
        ) : null}

        <div className={styles.keywordReviewGrid}>
          <div className={styles.keywordColumn}>
            <div className={styles.columnHeading}>
              <strong>非风险关键词</strong>
              <span>{nonRiskKeywords.length} 个</span>
            </div>
            <div className={styles.manualAddRow}>
              <input
                onChange={(event) => setManualKeywordInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    addManualKeyword();
                  }
                }}
                placeholder="人工添加非风险关键词"
                value={manualKeywordInput}
              />
              <button
                className="secondary-button"
                onClick={addManualKeyword}
                type="button"
              >
                <Plus aria-hidden="true" size={15} />
                添加
              </button>
            </div>
            {isLoadingKeywords ? (
              <p className={styles.sellingPointsEmpty}>正在加载关键词。</p>
            ) : null}
            {nonRiskKeywords.length === 0 && !isLoadingKeywords ? (
              <p className={styles.sellingPointsEmpty}>
                Claude 终筛后会在这里显示优质关键词。
              </p>
            ) : (
              <div className={styles.kwChipCloud}>
                {nonRiskKeywords.map((item) => {
                  const keywordKey = normalizeKeywordKey(item.keyword);
                  const isRemoving = pendingKeywordRemovalKeys.includes(keywordKey);

                  return (
                    <span
                      className={styles.kwChip}
                      data-removing={isRemoving}
                      key={`${item.source}-${item.id ?? item.keyword}`}
                      title={item.detail || item.keyword}
                    >
                      {item.keyword}
                      <button
                        aria-label={`移除 ${item.keyword}`}
                        disabled={isRemoving}
                        onClick={() => void removeKeyword(item)}
                        type="button"
                      >
                        {isRemoving ? (
                          <LoaderCircle
                            aria-hidden="true"
                            className="spin"
                            size={11}
                          />
                        ) : (
                          <X aria-hidden="true" size={11} />
                        )}
                      </button>
                    </span>
                  );
                })}
              </div>
            )}
          </div>

          <div className={styles.keywordColumn}>
            <div className={styles.columnHeading}>
              <strong>风险词</strong>
              <span>
                已决策 {
                  riskKeywords.filter((item) => riskDecisions[item.term]).length
                }/{riskKeywords.length}
              </span>
            </div>
            {riskKeywords.length > 0 ? (
              <div className={styles.riskBatchBar}>
                <button
                  className="secondary-button"
                  onClick={() => {
                    setKeywordSectionTouched(true);
                    setRiskDecisions(
                      Object.fromEntries(
                        riskKeywords.map((item) => [item.term, "approve" as const]),
                      ),
                    );
                  }}
                  type="button"
                >
                  <CheckCircle2 aria-hidden="true" size={14} />
                  全部通过
                </button>
                <button
                  className="secondary-button"
                  onClick={() => {
                    setKeywordSectionTouched(true);
                    setRiskDecisions(
                      Object.fromEntries(
                        riskKeywords.map((item) => [item.term, "reject" as const]),
                      ),
                    );
                  }}
                  type="button"
                >
                  <XCircle aria-hidden="true" size={14} />
                  全部拒绝
                </button>
              </div>
            ) : null}
            {riskKeywords.length === 0 ? (
              <p className={styles.sellingPointsEmpty}>
                暂无风险词。Claude 终筛完成后仍需提交关键词审核。
              </p>
            ) : (
              <ul className={styles.riskCompactList}>
                {riskKeywords.map((item) => {
                  const decision = riskDecisions[item.term];
                  return (
                    <li data-decision={decision ?? "none"} key={item.term}>
                      <span
                        className={styles.riskTermText}
                        title={item.reason || item.term}
                      >
                        <strong>{item.term}</strong>
                        {item.reason ? <em>{item.reason}</em> : null}
                      </span>
                      <span className={styles.riskActions}>
                        <button
                          aria-label={`通过 ${item.term}`}
                          aria-pressed={decision === "approve"}
                          data-kind="approve"
                          onClick={() => {
                            setKeywordSectionTouched(true);
                            setRiskDecisions((current) => ({
                              ...current,
                              [item.term]: "approve",
                            }));
                          }}
                          type="button"
                        >
                          <CheckCircle2 aria-hidden="true" size={15} />
                        </button>
                        <button
                          aria-label={`拒绝 ${item.term}`}
                          aria-pressed={decision === "reject"}
                          data-kind="reject"
                          onClick={() => {
                            setKeywordSectionTouched(true);
                            setRiskDecisions((current) => ({
                              ...current,
                              [item.term]: "reject",
                            }));
                          }}
                          type="button"
                        >
                          <XCircle aria-hidden="true" size={15} />
                        </button>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        {keywordReviewError ? (
          <p className={styles.sellingPointsError} role="alert">
            {keywordReviewError}
          </p>
        ) : null}
        <div className={styles.sectionFooter}>
          <span data-complete={keywordsComplete}>
            {keywordsComplete
              ? "关键词已保存"
              : keywordsDirty
                ? "关键词已修改，待重新提交"
                : "关键词待审核"}
          </span>
          <button
            className="primary-button"
            disabled={isSavingKeywordReview || isWorkflowBusy}
            onClick={() => void submitKeywordReview()}
            type="button"
          >
            {isSavingKeywordReview ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <ShieldCheck aria-hidden="true" size={16} />
            )}
            提交关键词
          </button>
        </div>
      </section>

      <section className={styles.workflowSection} aria-labelledby="k-image-system">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>图片</span>
            <h4 id="k-image-system">图片管理</h4>
          </div>
          <a className="secondary-button" href={iSystemHref}>
            <ExternalLink aria-hidden="true" size={16} />
            I系列
          </a>
        </div>

        <div className={styles.workflowMetrics}>
          <div>
            <dt>图片数</dt>
            <dd>{activeMediaAssets.length} / 5</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>
              {imagesComplete
                ? "已保存"
                : imagesDirty
                  ? "已修改，待重新提交"
                  : "待保存"}
            </dd>
          </div>
        </div>

        <label className={styles.field}>
          <span>变体</span>
          <select
            onChange={(event) => setSelectedVariantSku(event.target.value)}
            value={selectedVariantSku}
          >
            {(product.variants ?? []).map((variant, index) => (
              <option key={variant.variant_sku} value={variant.variant_sku}>
                {formatVariantOptionLabel(variant, index)}
              </option>
            ))}
          </select>
        </label>

        {variantSplitWarning ? (
          <p className={styles.sellingPointsEmpty}>
            当前后端只有 1 条变体记录。如果这其实是多个变体，请创建产品时用“添加变体”分别录入，每条变体会成为独立图片绑定目标。
          </p>
        ) : null}

        {selectedVariant ? (
          <div className={styles.variantImageFolder}>
            <strong>图片绑定目标</strong>
            <span>
              {formatVariantDisplayName(selectedVariant)} / {selectedVariant.variant_sku}
              {" / "}
              属性 {variantAttributesFromJson(selectedVariant.attributes_json).length} 项
            </span>
          </div>
        ) : null}

        <div className={styles.mediaCreateRow}>
          <div
            className={`${styles.mediaDropzone} ${
              isDraggingMedia ? styles.mediaDropzoneActive : ""
            }`}
            onClick={() => mediaInputRef.current?.click()}
            onDragEnter={(event) => {
              event.preventDefault();
              setIsDraggingMedia(true);
            }}
            onDragLeave={(event) => {
              event.preventDefault();
              setIsDraggingMedia(false);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleMediaDrop}
            role="button"
            tabIndex={0}
          >
            <input
              accept="image/*"
              hidden
              multiple
              onChange={(event) =>
                setUploadFiles(Array.from(event.target.files ?? []))
              }
              ref={mediaInputRef}
              type="file"
            />
            <ImagePlus aria-hidden="true" size={18} />
            <div>
              <strong>{selectedMediaLabel}</strong>
              <span>支持一次选择多张图片，上传后绑定当前 product / variant</span>
            </div>
          </div>
          <button
            className="secondary-button"
            disabled={
              isUploadingMedia ||
              !selectedVariantSku
            }
            onClick={() =>
              selectedMediaFiles.length === 0
                ? mediaInputRef.current?.click()
                : void createMedia()
            }
            type="button"
          >
            {isUploadingMedia ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <ImagePlus aria-hidden="true" size={16} />
            )}
            {selectedMediaFiles.length === 0
              ? "选择图片"
              : selectedMediaFiles.length > 1
              ? `上传 ${selectedMediaFiles.length} 张`
              : "上传"}
          </button>
        </div>
        {mediaError ? (
          <p className={styles.sellingPointsError}>{mediaError}</p>
        ) : null}

        <ul className={styles.mediaList}>
          {pendingMediaUploads.map((item) => (
            <li key={item.id}>
              <div>
                <strong>{item.fileName}</strong>
                <span>
                  {mediaVariantDisplayName(product.variants, item.variantSku)} / 正在上传
                </span>
              </div>
              <div>
                <button className="secondary-button" disabled type="button">
                  <LoaderCircle aria-hidden="true" className="spin" size={15} />
                  上传中
                </button>
              </div>
            </li>
          ))}
          {activeMediaAssets.map((asset) => (
            <li key={asset.id}>
              <div className={styles.mediaPreview}>
                <img
                  alt=""
                  decoding="async"
                  loading="lazy"
                  src={
                    asset.file_url_placeholder || mediaAssetThumbnailUrl(asset.id)
                  }
                />
              </div>
              <div className={styles.mediaMeta}>
                <strong>{asset.object_key || asset.id}</strong>
                <span>
                  {mediaVariantDisplayName(product.variants, asset.variant_sku)} /{" "}
                  {displayMediaSource(asset.source)} / {displayMediaStatus(asset.status)}
                </span>
              </div>
              <div>
                <a
                  className="secondary-button"
                  download
                  href={asset.file_url_placeholder || mediaAssetFileUrl(asset.id)}
                  rel="noreferrer"
                  target={asset.file_url_placeholder ? "_blank" : undefined}
                >
                  <Download aria-hidden="true" size={15} />
                  下载
                </a>
                <button
                  className="secondary-button"
                  disabled={
                    isWorkflowBusy ||
                    asset.source === "i_system_asset" ||
                    !asset.variant_sku
                  }
                  onClick={() =>
                    asset.variant_sku
                      ? bindUploadedImage(asset.id, asset.variant_sku)
                      : undefined
                  }
                  type="button"
                >
                  <Send aria-hidden="true" size={15} />
                  绑定
                </button>
                <button
                  className="secondary-button"
                  disabled={deletingMediaIds.includes(asset.id)}
                  onClick={() => void deleteMedia(asset.id)}
                  type="button"
                >
                  {deletingMediaIds.includes(asset.id) ? (
                    <LoaderCircle aria-hidden="true" className="spin" size={15} />
                  ) : (
                    <Trash2 aria-hidden="true" size={15} />
                  )}
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>
        {activeMediaAssets.length === 0 && pendingMediaUploads.length === 0 ? (
          <p className={styles.sellingPointsEmpty}>
            暂无已上传图片。请至少上传 5 张后提交图片。
          </p>
        ) : null}

        <div className={styles.sectionFooter}>
          <span data-complete={imagesComplete}>
            {imagesComplete
              ? "图片已保存"
              : imagesDirty
                ? "图片已修改，待重新提交"
                : "图片不少于 5 张后可保存"}
          </span>
          <button
            className="primary-button"
            disabled={activeMediaAssets.length < 5 || isWorkflowBusy}
            onClick={() => void submitImageSection()}
            type="button"
          >
            <CheckCircle2 aria-hidden="true" size={16} />
            提交图片
          </button>
        </div>
      </section>

      <section
        aria-labelledby="k-selling-points"
        className={styles.sellingPointsSection}
      >
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>卖点</span>
            <h4 id="k-selling-points">卖点整理</h4>
          </div>
          <div className={styles.headingActions}>
            {hasSellingPointsDraft ? (
              <button
                className="secondary-button"
                onClick={() => void copySellingPoints()}
                title="复制当前卖点"
                type="button"
              >
                <Copy aria-hidden="true" size={16} />
                {sellingPointsCopyStatus || "复制"}
              </button>
            ) : null}
            <button
              className="secondary-button"
              onClick={addManualSellingPoint}
              type="button"
            >
              <Plus aria-hidden="true" size={16} />
              新增手工卖点
            </button>
            <button
              className="secondary-button"
              disabled={isGeneratingSellingPoints}
              onClick={() => {
                setSellingPointsTouched(true);
                setSellingPointsApproved(false);
                setIsEditingSellingPoints(false);
                onGenerateSellingPoints?.();
              }}
              type="button"
            >
              {isGeneratingSellingPoints ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <Sparkles aria-hidden="true" size={16} />
              )}
              {sellingPoints ? "重新生成" : "生成"}
            </button>
          </div>
        </div>

        <div className={styles.workflowMetrics}>
          <div>
            <dt>进度</dt>
            <dd>{sellingPointsProgress}%</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>
              {sellingPointsComplete
                ? "已保存"
                : sellingPointsDirty
                  ? "已修改，待重新提交"
                  : "待审核"}
            </dd>
          </div>
        </div>
        <div
          aria-label="卖点进度"
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={sellingPointsProgress}
          className={styles.workflowProgress}
          role="progressbar"
        >
          <span style={{ width: `${sellingPointsProgress}%` }} />
        </div>

        {sellingPointsError ? (
          <p className={styles.sellingPointsError}>{sellingPointsError}</p>
        ) : null}
        {sellingPointReviewError ? (
          <p className={styles.sellingPointsError}>{sellingPointReviewError}</p>
        ) : null}

        {hasSellingPointsDraft && !isEditingSellingPoints ? (
          <div className={styles.sellingPointsResult}>
            {/* ---- 阅读模式：整洁展示，点「编辑」才出输入框 ---- */}
            <div className={styles.spReadHead}>
              <div className={styles.spChips}>
                <span className={styles.spMetaChip}>语言 {targetLanguage || "—"}</span>
                {seoKeywordsText
                  .split(/[,，\n]/)
                  .map((keyword) => keyword.trim())
                  .filter(Boolean)
                  .slice(0, 12)
                  .map((keyword) => (
                    <span className={styles.spKeywordChip} key={keyword}>
                      {keyword}
                    </span>
                  ))}
                {marketTagsText
                  .split(/[,，\n]/)
                  .map((tag) => tag.trim())
                  .filter(Boolean)
                  .slice(0, 8)
                  .map((tag) => (
                    <span className={styles.spTagChip} key={tag}>
                      {tag}
                    </span>
                  ))}
              </div>
              <button
                className="secondary-button"
                onClick={() => setIsEditingSellingPoints(true)}
                type="button"
              >
                <Pencil aria-hidden="true" size={15} />
                编辑
              </button>
            </div>

            <ol className={styles.spReadList}>
              {sellingBullets.map((bullet, index) => (
                <li
                  className={styles.spReadCard}
                  key={bullet.id || `${index}-${bullet.category}`}
                >
                  <div className={styles.spReadCardTop}>
                    <span className={styles.spCategoryBadge}>
                      {bullet.category || "卖点"}
                    </span>
                    <span
                      className={styles.spScoreBadge}
                      title="重要度"
                    >
                      ★ {Number(bullet.importance_score ?? 0).toFixed(1)}
                    </span>
                  </div>
                  <div className={styles.spBilingualRow}>
                    <p>{bullet.text}</p>
                    {bullet.text_zh ? (
                      <p className={styles.spZhText}>{bullet.text_zh}</p>
                    ) : null}
                  </div>
                  <small>
                    证据：{bullet.evidence || "未提供"} · {bullet.verification_status === "verified" ? "已核验" : "待核验"}
                  </small>
                </li>
              ))}
            </ol>

            {chineseTranslation ? (
              <details className={styles.spFold} open>
                <summary>中文翻译（供你审核）</summary>
                <p>{chineseTranslation}</p>
              </details>
            ) : null}
            {marketingCopy ? (
              <details className={styles.spFold}>
                <summary>转化文案</summary>
                <p>{marketingCopy}</p>
              </details>
            ) : null}
            {translatedVersion ? (
              <details className={styles.spFold}>
                <summary>目标市场译文</summary>
                <p>{translatedVersion}</p>
              </details>
            ) : null}
          </div>
        ) : null}

        {hasSellingPointsDraft && isEditingSellingPoints ? (
          <div className={styles.sellingPointsResult}>
            <div className={styles.spEditBar}>
              <span>编辑模式 —— 改完点「完成编辑」回到清爽视图，再提交卖点。</span>
              <button
                className="secondary-button"
                onClick={() => setIsEditingSellingPoints(false)}
                type="button"
              >
                <CheckCircle2 aria-hidden="true" size={15} />
                完成编辑
              </button>
            </div>
            <div className={styles.sellingPointEditorGrid}>
              <label className={styles.field}>
                <span>目标语言</span>
                <input
                  onChange={(event) => {
                    setSellingPointsTouched(true);
                    setTargetLanguage(event.target.value);
                  }}
                  value={targetLanguage}
                />
              </label>
              <label className={styles.field}>
                <span>SEO关键词</span>
                <textarea
                  onChange={(event) => {
                    setSellingPointsTouched(true);
                    setSeoKeywordsText(event.target.value);
                  }}
                  rows={3}
                  value={seoKeywordsText}
                />
              </label>
              <label className={styles.field}>
                <span>市场标签</span>
                <textarea
                  onChange={(event) => {
                    setSellingPointsTouched(true);
                    setMarketTagsText(event.target.value);
                  }}
                  rows={3}
                  value={marketTagsText}
                />
              </label>
            </div>

            <ul className={styles.sellingPointBullets}>
              {sellingBullets.map((bullet, index) => (
                <li
                  className={styles.spEditRow}
                  key={bullet.id || `${index}-${bullet.category}`}
                >
                  <div className={styles.spRowHead}>
                    <span className={styles.spRowOrdinal}>{index + 1}</span>
                    <label className={styles.field}>
                      <span>类别</span>
                      <input
                        aria-label="卖点类别"
                        onChange={(event) =>
                          updateBullet(index, { category: event.target.value })
                        }
                        value={bullet.category}
                      />
                    </label>
                    <label className={`${styles.field} ${styles.spRowScore}`}>
                      <span>重要度</span>
                      <input
                        aria-label="重要度"
                        min={0}
                        onChange={(event) =>
                          updateBullet(index, {
                            importance_score: Number(event.target.value),
                          })
                        }
                        step={0.1}
                        type="number"
                        value={bullet.importance_score}
                      />
                    </label>
                    <label className={`${styles.field} ${styles.spRowDecision}`}>
                      <span>逐条决定</span>
                      <select
                        aria-label="卖点审核决定"
                        onChange={(event) =>
                          updateBullet(index, {
                            review_decision: event.target.value as BulletPoint["review_decision"],
                          })
                        }
                        value={bullet.review_decision ?? "candidate"}
                      >
                        <option value="candidate">待决定</option>
                        <option value="approve">通过</option>
                        <option value="edit">编辑后通过</option>
                        <option value="reject">拒绝</option>
                      </select>
                    </label>
                    <button
                      className={`secondary-button ${styles.spRowDelete}`}
                      onClick={() => removeSellingPoint(index)}
                      type="button"
                    >
                      <Trash2 aria-hidden="true" size={15} />
                      删除
                    </button>
                  </div>

                  <label className={styles.field}>
                    <span>卖点文案</span>
                    <textarea
                      aria-label="卖点文案"
                      onChange={(event) =>
                        updateBullet(index, { text: event.target.value })
                      }
                      rows={2}
                      value={bullet.text}
                    />
                  </label>

                  {bullet.text_zh ? (
                    <p className={styles.spZhLine}>
                      <span>中文对照</span>
                      {bullet.text_zh}
                    </p>
                  ) : null}

                  <label className={styles.field}>
                    <span>证据</span>
                    <input
                      aria-label="卖点证据"
                      onChange={(event) =>
                        updateBullet(index, {
                          evidence: event.target.value,
                          verification_status: "unverified",
                        })
                      }
                      placeholder="spec:material / verified_feature:ID / operator_fact"
                      value={bullet.evidence ?? ""}
                    />
                  </label>
                </li>
              ))}
            </ul>

            <label className={styles.field}>
              <span>转化文案</span>
              <textarea
                onChange={(event) => {
                  setSellingPointsTouched(true);
                  setMarketingCopy(event.target.value);
                }}
                rows={4}
                value={marketingCopy}
              />
            </label>
            <label className={styles.field}>
              <span>目标市场译文</span>
              <textarea
                onChange={(event) => {
                  setSellingPointsTouched(true);
                  setTranslatedVersion(event.target.value);
                }}
                rows={4}
                value={translatedVersion}
              />
            </label>
            <label className={styles.field}>
              <span>中文翻译</span>
              <textarea
                onChange={(event) => {
                  setSellingPointsTouched(true);
                  setChineseTranslation(event.target.value);
                }}
                rows={5}
                value={chineseTranslation}
              />
            </label>
          </div>
        ) : null}

        {!hasSellingPointsDraft ? (
          <p className={styles.sellingPointsEmpty}>
            可直接新增手工卖点，或点击生成后逐条审核 AI 候选。
          </p>
        ) : null}

        {sellingPointReviewError ? (
          <p className={styles.sellingPointsError} role="alert">
            {sellingPointReviewError}
          </p>
        ) : null}
        <div className={styles.sectionFooter}>
          <span data-complete={sellingPointsComplete}>
            {sellingPointsComplete
              ? "卖点已保存"
              : sellingPointsDirty
                ? "卖点已修改，待重新提交"
                : "卖点待审核"}
          </span>
          <button
            className="primary-button"
            disabled={sellingBullets.length === 0 || isSavingSellingPoints}
            onClick={() => void submitSellingPointsReview()}
            type="button"
          >
            {isSavingSellingPoints ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <CheckCircle2 aria-hidden="true" size={16} />
            )}
            提交卖点
          </button>
        </div>
      </section>

      {product ? (
        <CopyArtDirection
          onAssetsSaved={onRefreshWorkflow}
          productId={product.id}
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
