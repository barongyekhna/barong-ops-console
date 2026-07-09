"use client";

import {
  AlertTriangle,
  ArrowLeft,
  ChevronRight,
  ClipboardList,
  ExternalLink,
  ImagePlus,
  LoaderCircle,
  PackageOpen,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";

import type { ProductSellingPoints } from "@/modules/k14/selling-points/types";

import {
  approveProductSellingPoints,
  bindProductImage,
  controlWorkflow,
  createProduct,
  deleteProduct,
  deleteMediaAsset,
  enrichProductWithDeepSeek,
  generateProductCopyBatch,
  generateProductImageBriefBatch,
  generateProductSellingPoints,
  getLatestWorkflow,
  getMediaAssets,
  getProductReadiness,
  getProductSellingPoints,
  getProducts,
  PRODUCT_CREATE_FAILURE_MESSAGE,
  ProductKnowledgeApiError,
  reviewWorkflowRiskTerms,
  submitProductKeywords,
  startWorkflow,
  submitProductImages,
  updateProduct,
  uploadProductMediaAsset,
} from "./api";
import { DashboardScene } from "@/components/dashboard-scene";
import { ProductDetail } from "./ProductDetail";
import { ProductForm } from "./ProductForm";
import { displayProductKey } from "./display";
import styles from "./ProductKnowledge.module.css";
import type {
  ProductCreateFormPayload,
  KMediaAsset,
  ProductReadinessState,
  KRiskReviewDecision,
  KWorkflowExecution,
  KWorkflowStartPayload,
  ProductKnowledgeListItem,
  ProductKnowledgeListResponse,
} from "./types";

const PRODUCT_LIST_PAGE_SIZE = 25;
const PRODUCT_LIST_FETCH_LIMIT = 100;

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function displayReviewStatus(status: string) {
  const labels: Record<string, string> = {
    approved: "已通过",
    archived: "已归档",
    draft: "草稿",
    pending: "待审核",
    pending_review: "待审核",
    rejected: "已拒绝",
    review: "审核中",
  };

  return labels[status] ?? "待处理";
}

type PipeState = "done" | "active" | "blocked" | "pending";

const PIPELINE_STAGES: Array<{ label: string; code: string }> = [
  { label: "关键词", code: "KEYWORDS" },
  { label: "图片", code: "IMAGES" },
  { label: "卖点", code: "SELLING" },
  { label: "准备", code: "READY" },
];

// 由 readiness 推导 4 段流水线状态：关键词 / 图片 / 卖点 / 准备。
function pipelineStates(readiness: ProductReadinessState | null): PipeState[] {
  if (!readiness) {
    return ["pending", "pending", "pending", "pending"];
  }
  const sections = [
    readiness.keywords,
    readiness.images,
    readiness.selling_points,
  ];
  const states: PipeState[] = sections.map((section) =>
    section.status === "blocked"
      ? "blocked"
      : section.submitted
        ? "done"
        : "pending",
  );
  states.push(readiness.ready ? "done" : "pending");
  const activeIndex = states.findIndex((state) => state === "pending");
  if (activeIndex >= 0) {
    states[activeIndex] = "active";
  }
  return states;
}

function formatError(error: unknown, fallback: string) {
  const rawStatus =
    error instanceof ProductKnowledgeApiError ||
    (typeof error === "object" && error !== null && "status" in error)
      ? Number((error as { status?: unknown }).status)
      : null;
  const status =
    typeof rawStatus === "number" && Number.isFinite(rawStatus)
      ? rawStatus
      : null;

  if (status !== null) {
    if (status === 403) {
      return "当前账号暂未开通该操作权限。";
    }
  }
  if (error instanceof ProductKnowledgeApiError || error instanceof Error) {
    return error.message;
  }

  return fallback;
}

function formatCreateError(error: unknown) {
  if (error instanceof ProductKnowledgeApiError) {
    if (error.status === 409 || /request conflict/i.test(error.message)) {
      return PRODUCT_CREATE_FAILURE_MESSAGE;
    }
    return error.message || PRODUCT_CREATE_FAILURE_MESSAGE;
  }
  if (error instanceof Error && /request conflict/i.test(error.message)) {
    return PRODUCT_CREATE_FAILURE_MESSAGE;
  }
  return PRODUCT_CREATE_FAILURE_MESSAGE;
}

function nextOpenProductId(
  response: ProductKnowledgeListResponse,
  currentId: string | null,
  preferredId?: string,
) {
  const ids = new Set(response.items.map((item) => item.id));

  if (preferredId && ids.has(preferredId)) {
    return preferredId;
  }
  if (currentId && ids.has(currentId)) {
    return currentId;
  }

  return null;
}

export function ProductList() {
  function openFullProductList() {
    const openedWindow = window.open(
      "/products/full",
      "_blank",
      "noopener,noreferrer",
    );
    if (openedWindow) {
      openedWindow.opener = null;
    }
  }

  return (
    <section className={styles.listPanel} aria-labelledby="product-list-entry">
      <div className={styles.panelHeading}>
        <div>
          <span className={styles.eyebrow}>产品</span>
          <h3 id="product-list-entry">产品列表</h3>
        </div>
        <button
          className="primary-button"
          onClick={openFullProductList}
          type="button"
        >
          <ExternalLink aria-hidden="true" size={16} />
          打开产品列表
        </button>
      </div>
    </section>
  );
}

export function ProductListFull() {
  const [products, setProducts] = useState<ProductKnowledgeListItem[]>([]);
  const [openProductId, setOpenProductId] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [sellingPointsByProductId, setSellingPointsByProductId] = useState<
    Record<string, ProductSellingPoints>
  >({});
  const [workflowByProductId, setWorkflowByProductId] = useState<
    Record<string, KWorkflowExecution | null>
  >({});
  const [mediaByProductId, setMediaByProductId] = useState<
    Record<string, KMediaAsset[]>
  >({});
  const [readinessByProductId, setReadinessByProductId] = useState<
    Record<string, ProductReadinessState>
  >({});
  const [showCreate, setShowCreate] = useState(false);
  const [rowReadiness, setRowReadiness] = useState<
    Record<string, ProductReadinessState>
  >({});
  const attemptedReadinessRef = useRef<Set<string>>(new Set());
  const [deleteCandidate, setDeleteCandidate] =
    useState<ProductKnowledgeListItem | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [createError, setCreateError] = useState("");
  const [productSaveError, setProductSaveError] = useState("");
  const [sellingPointsError, setSellingPointsError] = useState("");
  const [workflowError, setWorkflowError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [savingProductId, setSavingProductId] = useState<string | null>(null);
  const [generatingProductId, setGeneratingProductId] = useState<string | null>(
    null,
  );
  const [workflowBusyAction, setWorkflowBusyAction] = useState<string | null>(
    null,
  );
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState<null | "copy" | "brief">(null);
  const [batchNotice, setBatchNotice] = useState("");
  const [batchError, setBatchError] = useState("");

  const openProduct = useMemo(
    () => products.find((product) => product.id === openProductId) ?? null,
    [products, openProductId],
  );
  const pageCount = Math.max(
    1,
    Math.ceil(products.length / PRODUCT_LIST_PAGE_SIZE),
  );
  const pageItems = useMemo(() => {
    const start = (currentPage - 1) * PRODUCT_LIST_PAGE_SIZE;
    return products.slice(start, start + PRODUCT_LIST_PAGE_SIZE);
  }, [currentPage, products]);
  const pageStart =
    products.length === 0 ? 0 : (currentPage - 1) * PRODUCT_LIST_PAGE_SIZE + 1;
  const pageEnd = Math.min(
    currentPage * PRODUCT_LIST_PAGE_SIZE,
    products.length,
  );
  const deleteConfirmationKey = deleteCandidate
    ? displayProductKey(deleteCandidate.product_key)
    : "";
  const canConfirmDelete =
    deleteCandidate !== null &&
    deleteConfirmation.trim() === deleteConfirmationKey &&
    !isDeleting;

  function openImageSystem(
    product: ProductKnowledgeListItem,
    event: MouseEvent<HTMLButtonElement>,
  ) {
    event.stopPropagation();
    const params = new URLSearchParams({
      product_id: product.id,
      source: "k",
    });
    const firstVariant = product.variants?.[0] ?? null;
    if (firstVariant?.id) {
      params.set("variant_id", firstVariant.id);
    }
    const openedWindow = window.open(
      `/image-system?${params.toString()}`,
      "_blank",
      "noopener,noreferrer",
    );
    if (openedWindow) {
      openedWindow.opener = null;
    }
  }

  const loadProducts = useCallback(
    async (preferredOpenId?: string, query?: string) => {
      setIsLoading(true);
      setLoadError("");
      attemptedReadinessRef.current = new Set();
      setRowReadiness({});

      try {
        const trimmedQuery = query?.trim() ?? "";
        const firstPage = await getProducts({
          limit: PRODUCT_LIST_FETCH_LIMIT,
          offset: 0,
          q: trimmedQuery || undefined,
        });
        const allItems = [...firstPage.items];
        for (
          let offset = firstPage.items.length;
          offset < firstPage.count;
          offset += PRODUCT_LIST_FETCH_LIMIT
        ) {
          const nextPage = await getProducts({
            limit: PRODUCT_LIST_FETCH_LIMIT,
            offset,
            q: trimmedQuery || undefined,
          });
          allItems.push(...nextPage.items);
          if (nextPage.items.length === 0) {
            break;
          }
        }
        const response = {
          ...firstPage,
          count: Math.max(firstPage.count, allItems.length),
          items: allItems,
        };
        const preferredIndex = preferredOpenId
          ? response.items.findIndex((item) => item.id === preferredOpenId)
          : -1;
        setProducts(response.items);
        setOpenProductId((currentId) =>
          nextOpenProductId(response, currentId, preferredOpenId),
        );
        setCurrentPage((current) => {
          if (preferredIndex >= 0) {
            return Math.floor(preferredIndex / PRODUCT_LIST_PAGE_SIZE) + 1;
          }
          const nextPageCount = Math.max(
            1,
            Math.ceil(response.items.length / PRODUCT_LIST_PAGE_SIZE),
          );
          return Math.min(Math.max(current, 1), nextPageCount);
        });
      } catch (error) {
        setProducts([]);
        setOpenProductId(null);
        setLoadError(
          formatError(error, "产品知识库接口暂不可用。"),
        );
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void loadProducts(undefined, activeSearch);
  }, [activeSearch, loadProducts]);

  const loadWorkflowRuntime = useCallback(async (productId: string) => {
    setWorkflowError("");

    try {
      const [workflow, media, readiness, sellingPoints] = await Promise.all([
        getLatestWorkflow(productId),
        getMediaAssets(productId),
        getProductReadiness(productId),
        getProductSellingPoints(productId),
      ]);
      setWorkflowByProductId((current) => ({
        ...current,
        [productId]: workflow,
      }));
      setMediaByProductId((current) => ({
        ...current,
        [productId]: media.items,
      }));
      setReadinessByProductId((current) => ({
        ...current,
        [productId]: readiness,
      }));
      setSellingPointsByProductId((current) => {
        if (!sellingPoints) {
          const { [productId]: _removed, ...rest } = current;
          return rest;
        }

        return {
          ...current,
          [productId]: sellingPoints,
        };
      });
    } catch (error) {
      setWorkflowError(
        formatError(error, "流程运行状态加载失败。"),
      );
    }
  }, []);

  useEffect(() => {
    if (!openProductId) {
      return;
    }

    void loadWorkflowRuntime(openProductId);
  }, [loadWorkflowRuntime, openProductId]);

  // 名册进度灯：为当前页产品拉取 readiness（ref 记录已尝试，失败也不重拉）。
  useEffect(() => {
    if (openProductId) {
      return;
    }
    const missing = pageItems.filter(
      (item) => !attemptedReadinessRef.current.has(item.id),
    );
    if (missing.length === 0) {
      return;
    }
    for (const item of missing) {
      attemptedReadinessRef.current.add(item.id);
    }
    let cancelled = false;
    void (async () => {
      const results = await Promise.all(
        missing.map(async (item) => {
          try {
            return [item.id, await getProductReadiness(item.id)] as const;
          } catch {
            return null;
          }
        }),
      );
      if (cancelled) {
        return;
      }
      setRowReadiness((current) => {
        const next = { ...current };
        for (const entry of results) {
          if (entry) {
            next[entry[0]] = entry[1];
          }
        }
        return next;
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [openProductId, pageItems]);

  async function handleCreate(payload: ProductCreateFormPayload) {
    setIsCreating(true);
    setCreateError("");

    try {
      const createdProduct = await createProduct(payload);
      let deepSeekError = "";

      if (payload.target_market) {
        try {
          await enrichProductWithDeepSeek(createdProduct.id);
        } catch (error) {
          deepSeekError = formatError(
            error,
            "产品已创建，但 DeepSeek 转换未完成。",
          );
        }
      }

      await loadProducts(createdProduct.id, activeSearch);
      setShowCreate(false);
      if (deepSeekError) {
        setCreateError(deepSeekError);
      }
    } catch (error) {
      setCreateError(formatCreateError(error));
      throw error;
    } finally {
      setIsCreating(false);
    }
  }

  function toggleProduct(productId: string) {
    setOpenProductId((currentId) => (currentId === productId ? null : productId));
    setProductSaveError("");
    setSellingPointsError("");
    setWorkflowError("");
  }

  const pageItemIds = useMemo(
    () => pageItems.map((item) => item.id),
    [pageItems],
  );
  const allPageSelected =
    pageItemIds.length > 0 && pageItemIds.every((id) => selectedIds.has(id));

  function toggleSelect(productId: string) {
    setBatchNotice("");
    setBatchError("");
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(productId)) {
        next.delete(productId);
      } else {
        next.add(productId);
      }
      return next;
    });
  }

  function toggleSelectAllOnPage() {
    setBatchNotice("");
    setBatchError("");
    setSelectedIds((current) => {
      const next = new Set(current);
      if (pageItemIds.every((id) => next.has(id))) {
        for (const id of pageItemIds) {
          next.delete(id);
        }
      } else {
        for (const id of pageItemIds) {
          next.add(id);
        }
      }
      return next;
    });
  }

  function clearSelection() {
    setSelectedIds(new Set());
    setBatchNotice("");
    setBatchError("");
  }

  async function handleBatchGenerate(kind: "copy" | "brief") {
    // Only enqueue products that still exist in the loaded roster.
    const ids = [...selectedIds].filter((id) =>
      products.some((product) => product.id === id),
    );
    if (ids.length === 0) {
      return;
    }
    setBatchBusy(kind);
    setBatchNotice("");
    setBatchError("");
    try {
      const result =
        kind === "copy"
          ? await generateProductCopyBatch(ids)
          : await generateProductImageBriefBatch(ids);
      const label = kind === "copy" ? "文案" : "作图指令";
      const hint =
        kind === "copy"
          ? "机器后台批量生成，进入各产品「文案」区可看进度并审核。"
          : "作图指令需产品已有文案；缺文案的会自动跳过失败。进入各产品可查看。";
      setBatchNotice(
        `已提交 ${result.jobs.length} 个产品的${label}生成任务。${hint}`,
      );
      setSelectedIds(new Set());
    } catch (error) {
      setBatchError(formatError(error, "批量生成提交失败，请重试。"));
    } finally {
      setBatchBusy(null);
    }
  }

  function closeDeleteModal() {
    if (isDeleting) {
      return;
    }
    setDeleteCandidate(null);
    setDeleteConfirmation("");
    setDeleteError("");
  }

  function requestDelete(
    product: ProductKnowledgeListItem,
    event: MouseEvent<HTMLButtonElement>,
  ) {
    event.stopPropagation();
    setDeleteCandidate(product);
    setDeleteConfirmation("");
    setDeleteError("");
  }

  async function confirmDelete() {
    if (!deleteCandidate || !canConfirmDelete) {
      return;
    }

    setIsDeleting(true);
    setDeleteError("");

    try {
      await deleteProduct(deleteCandidate.id, deleteCandidate.product_key);
      if (openProductId === deleteCandidate.id) {
        setOpenProductId(null);
      }
      setWorkflowByProductId((current) => {
        const { [deleteCandidate.id]: _workflow, ...rest } = current;
        return rest;
      });
      setMediaByProductId((current) => {
        const { [deleteCandidate.id]: _media, ...rest } = current;
        return rest;
      });
      setReadinessByProductId((current) => {
        const { [deleteCandidate.id]: _readiness, ...rest } = current;
        return rest;
      });
      setSellingPointsByProductId((current) => {
        const { [deleteCandidate.id]: _sellingPoints, ...rest } = current;
        return rest;
      });
      setDeleteCandidate(null);
      setDeleteConfirmation("");
      await loadProducts(undefined, activeSearch);
    } catch (error) {
      setDeleteError(formatError(error, "产品删除失败。"));
    } finally {
      setIsDeleting(false);
    }
  }

  function goToPage(page: number) {
    setOpenProductId(null);
    setCurrentPage(Math.min(Math.max(page, 1), pageCount));
  }

  function submitSearch() {
    const query = searchInput.trim();
    setCurrentPage(1);
    setOpenProductId(null);
    if (query === activeSearch) {
      void loadProducts(undefined, query);
      return;
    }
    setActiveSearch(query);
  }

  function clearSearch() {
    setSearchInput("");
    setCurrentPage(1);
    setOpenProductId(null);
    setActiveSearch("");
  }

  async function handleGenerateSellingPoints() {
    if (!openProduct) {
      return;
    }

    setGeneratingProductId(openProduct.id);
    setSellingPointsError("");

    try {
      const sellingPoints = await generateProductSellingPoints(openProduct.id);
      setSellingPointsByProductId((current) => ({
        ...current,
        [openProduct.id]: sellingPoints,
      }));
      await loadWorkflowRuntime(openProduct.id);
    } catch (error) {
      setSellingPointsError(
        formatError(error, "卖点生成失败。"),
      );
    } finally {
      setGeneratingProductId(null);
    }
  }

  async function handleApproveSellingPoints(sellingPoints: ProductSellingPoints) {
    if (!openProduct) {
      return;
    }

    setGeneratingProductId(openProduct.id);
    setSellingPointsError("");

    try {
      const approved = await approveProductSellingPoints(
        openProduct.id,
        sellingPoints,
      );
      setSellingPointsByProductId((current) => ({
        ...current,
        [openProduct.id]: approved,
      }));
      await loadWorkflowRuntime(openProduct.id);
    } catch (error) {
      setSellingPointsError(
        formatError(error, "卖点审核保存失败。"),
      );
      throw error;
    } finally {
      setGeneratingProductId(null);
    }
  }

  async function runWorkflowAction(
    actionName: string,
    callback: () => Promise<void>,
  ) {
    setWorkflowBusyAction(actionName);
    setWorkflowError("");

    try {
      await callback();
    } catch (error) {
      setWorkflowError(formatError(error, "流程操作失败。"));
    } finally {
      setWorkflowBusyAction(null);
    }
  }

  async function handleStartWorkflow(payload: KWorkflowStartPayload) {
    if (!openProduct) {
      return;
    }

    await runWorkflowAction("start", async () => {
      const workflow = await startWorkflow(openProduct.id, payload);
      setWorkflowByProductId((current) => ({
        ...current,
        [openProduct.id]: workflow,
      }));
    });
  }

  async function handleRetryWorkflowStep(
    step: string,
    payload: KWorkflowStartPayload,
  ) {
    if (!openProduct) {
      return;
    }
    const workflow = workflowByProductId[openProduct.id] ?? null;

    await runWorkflowAction(`retry-${step}`, async () => {
      const updated = await controlWorkflow(openProduct.id, "retry", {
        execution_id: workflow?.id ?? null,
        step,
        workflow_payload: payload,
      });
      setWorkflowByProductId((current) => ({
        ...current,
        [openProduct.id]: updated,
      }));
      await loadWorkflowRuntime(openProduct.id);
    });
  }

  async function handleSubmitRiskReview(
    decisions: KRiskReviewDecision[],
    confirmNoRiskTerms: boolean,
  ) {
    if (!openProduct) {
      return;
    }
    const workflow = workflowByProductId[openProduct.id] ?? null;

    setWorkflowBusyAction("risk-review");
    setWorkflowError("");
    try {
      const canUseWorkflowReview = Boolean(
        workflow?.id &&
          (workflow.current_step === "risk_term_manual_review" ||
            workflow.current_step === "risk_term_review_manual" ||
            workflow.risk_approval_log_json?.approved === true),
      );
      if (canUseWorkflowReview) {
        const updated = await reviewWorkflowRiskTerms(openProduct.id, {
          confirm_no_risk_terms: confirmNoRiskTerms,
          decisions,
          execution_id: workflow?.id ?? null,
        });
        setWorkflowByProductId((current) => ({
          ...current,
          [openProduct.id]: updated,
        }));
      } else {
        await submitProductKeywords(openProduct.id);
      }
      await loadWorkflowRuntime(openProduct.id);
    } catch (error) {
      setWorkflowError(formatError(error, "关键词审核保存失败。"));
      throw error;
    } finally {
      setWorkflowBusyAction(null);
    }
  }

  async function handleSaveProductInfo() {
    if (!openProduct) {
      return;
    }

    setSavingProductId(openProduct.id);
    setProductSaveError("");
    try {
      const updated = await updateProduct(openProduct.id, {
        review_status: "approved",
      });
      setProducts((current) =>
        current.map((product) =>
          product.id === openProduct.id
            ? {
                ...product,
                ...updated,
              }
            : product,
        ),
      );
    } catch (error) {
      setProductSaveError(formatError(error, "商品信息保存失败。"));
      throw error;
    } finally {
      setSavingProductId(null);
    }
  }

  async function handleSubmitImages(): Promise<void> {
    if (!openProduct) {
      return;
    }

    const productId = openProduct.id;
    setWorkflowError("");
    try {
      await submitProductImages(productId);
      await loadWorkflowRuntime(productId);
    } catch (error) {
      setWorkflowError(formatError(error, "图片提交失败。"));
      throw error;
    }
  }

  async function handleCreateMedia(
    file: File,
    variantSku: string,
  ): Promise<KMediaAsset | void> {
    if (!openProduct) {
      return;
    }

    const productId = openProduct.id;
    setWorkflowError("");
    try {
      const asset = await uploadProductMediaAsset(productId, file, variantSku);
      setMediaByProductId((current) => {
        const existing = current[productId] ?? [];

        return {
          ...current,
          [productId]: [
            asset,
            ...existing.filter((item) => item.id !== asset.id),
          ],
        };
      });
      void loadWorkflowRuntime(productId);
      return asset;
    } catch (error) {
      setWorkflowError(formatError(error, "图片上传失败。"));
      throw error;
    }
  }

  async function handleDeleteMedia(assetId: string) {
    if (!openProduct) {
      return;
    }

    const productId = openProduct.id;
    setWorkflowError("");
    setMediaByProductId((current) => ({
      ...current,
      [productId]: (current[productId] ?? []).filter(
        (asset) => asset.id !== assetId,
      ),
    }));
    try {
      await deleteMediaAsset(assetId);
      void loadWorkflowRuntime(productId);
    } catch (error) {
      setWorkflowError(formatError(error, "图片删除失败。"));
      void loadWorkflowRuntime(productId);
      throw error;
    }
  }

  async function handleBindImage(assetId: string, variantSku: string) {
    if (!openProduct) {
      return;
    }

    await runWorkflowAction("image-bind", async () => {
      const workflow = await bindProductImage(openProduct.id, {
        asset_id: assetId,
        source_type: "manual_upload_image",
        variant_sku: variantSku,
      });
      setWorkflowByProductId((current) => ({
        ...current,
        [openProduct.id]: workflow,
      }));
      await loadWorkflowRuntime(openProduct.id);
    });
  }

  async function handleBindISystemImage(imageAssetId: string, variantSku: string) {
    if (!openProduct) {
      return;
    }

    await runWorkflowAction("i-system-image-bind", async () => {
      const workflow = await bindProductImage(openProduct.id, {
        i_system_image_asset_id: imageAssetId,
        source_type: "i_system_asset",
        variant_sku: variantSku,
      });
      setWorkflowByProductId((current) => ({
        ...current,
        [openProduct.id]: workflow,
      }));
      await loadWorkflowRuntime(openProduct.id);
    });
  }

  return (
    <section
      aria-label="产品知识库"
      className={`${styles.workspace} mm-page k-page`}
    >
      <DashboardScene />

      <div className={styles.kCommandBar}>
        <div>
          <span className={styles.eyebrow}>K 系列</span>
          <h2>产品知识库</h2>
          <p>创建产品后进入档案，逐步完成关键词、图片与卖点审核。</p>
        </div>
        <div className={styles.kCommandActions}>
          <button
            className="primary-button"
            onClick={() => {
              setCreateError("");
              setOpenProductId(null);
              setShowCreate(true);
            }}
            type="button"
          >
            <Plus aria-hidden="true" size={16} />
            新建产品
          </button>
          <button
            className="secondary-button"
            disabled={isLoading}
            onClick={() => void loadProducts(undefined, activeSearch)}
            type="button"
          >
            {isLoading ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <RotateCcw aria-hidden="true" size={16} />
            )}
            刷新
          </button>
        </div>
      </div>

      {showCreate ? (
        <div className={styles.createPanel}>
          <button
            aria-label="取消"
            className={styles.createClose}
            disabled={isCreating}
            onClick={() => setShowCreate(false)}
            type="button"
          >
            <X aria-hidden="true" size={15} />
            取消
          </button>
          <ProductForm
            error={createError}
            isSubmitting={isCreating}
            onCreate={handleCreate}
            onDismissError={() => setCreateError("")}
          />
        </div>
      ) : null}

      {openProduct ? (
        <div className={styles.dossier}>
          <div className={styles.dossierBar}>
            <button
              className={styles.backButton}
              onClick={() => setOpenProductId(null)}
              type="button"
            >
              <ArrowLeft aria-hidden="true" size={16} />
              返回名册
            </button>
            <div className={styles.dossierTitle}>
              <strong>
                {openProduct.product_name_en ||
                  displayProductKey(openProduct.product_key)}
              </strong>
              <span>
                {openProduct.parent_sku ||
                  openProduct.sku ||
                  displayProductKey(openProduct.product_key)}
              </span>
            </div>
            <div className={styles.dossierActions}>
              <button
                className="secondary-button"
                onClick={(event) => openImageSystem(openProduct, event)}
                type="button"
              >
                <ImagePlus aria-hidden="true" size={15} />
                作图
              </button>
              <button
                className={`secondary-button ${styles.dangerButton}`}
                onClick={(event) => requestDelete(openProduct, event)}
                type="button"
              >
                <Trash2 aria-hidden="true" size={15} />
                删除
              </button>
            </div>
          </div>

          <div className={styles.pipeline}>
            {pipelineStates(
              readinessByProductId[openProduct.id] ??
                rowReadiness[openProduct.id] ??
                null,
            ).map((state, index) => (
              <div
                className={styles.pipeStage}
                data-state={state}
                key={PIPELINE_STAGES[index].code}
              >
                <span className={styles.pipeDot}>
                  {state === "done" ? "✓" : index + 1}
                </span>
                <span className={styles.pipeText}>
                  <strong>{PIPELINE_STAGES[index].label}</strong>
                  <span>{PIPELINE_STAGES[index].code}</span>
                </span>
                {index < PIPELINE_STAGES.length - 1 ? (
                  <span className={styles.pipeConn} />
                ) : null}
              </div>
            ))}
          </div>

          <ProductDetail
            isGeneratingSellingPoints={generatingProductId === openProduct.id}
            isSavingProductInfo={savingProductId === openProduct.id}
            isWorkflowBusy={workflowBusyAction !== null}
            mediaAssets={mediaByProductId[openProduct.id] ?? []}
            onApproveSellingPoints={(sellingPoints) =>
              handleApproveSellingPoints(sellingPoints)
            }
            onBindImage={(assetId, variantSku) =>
              void handleBindImage(assetId, variantSku)
            }
            onBindISystemImage={(imageAssetId, variantSku) =>
              void handleBindISystemImage(imageAssetId, variantSku)
            }
            onCollapse={() => setOpenProductId(null)}
            onCreateMedia={(file, variantSku) =>
              handleCreateMedia(file, variantSku)
            }
            onDeleteMedia={(assetId) => handleDeleteMedia(assetId)}
            onGenerateSellingPoints={handleGenerateSellingPoints}
            onRefreshWorkflow={() => void loadWorkflowRuntime(openProduct.id)}
            onRetryWorkflowStep={(step, payload) =>
              void handleRetryWorkflowStep(step, payload)
            }
            onSaveProductInfo={() => void handleSaveProductInfo()}
            onSubmitImages={handleSubmitImages}
            onStartWorkflow={(payload) => void handleStartWorkflow(payload)}
            onSubmitRiskReview={(decisions, confirmNoRiskTerms) =>
              handleSubmitRiskReview(decisions, confirmNoRiskTerms)
            }
            product={openProduct}
            readiness={readinessByProductId[openProduct.id] ?? null}
            sellingPoints={sellingPointsByProductId[openProduct.id] ?? null}
            productInfoSaveError={productSaveError}
            sellingPointsError={sellingPointsError}
            workflow={workflowByProductId[openProduct.id] ?? null}
            workflowError={workflowError}
          />
        </div>
      ) : (
        <section
          aria-labelledby="products-full-title"
          className={styles.listPanel}
        >
          <form
            className={styles.searchBar}
            onSubmit={(event) => {
              event.preventDefault();
              submitSearch();
            }}
          >
            <label className={styles.field}>
              <span>搜索</span>
              <input
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="输入 SKU / Product Key 精确搜索，或输入关键词模糊搜索"
                type="search"
                value={searchInput}
              />
            </label>
            <button className="secondary-button" disabled={isLoading} type="submit">
              <Search aria-hidden="true" size={16} />
              搜索
            </button>
            <button
              className="secondary-button"
              disabled={isLoading || (!activeSearch && !searchInput)}
              onClick={clearSearch}
              type="button"
            >
              <X aria-hidden="true" size={16} />
              清空
            </button>
          </form>

          {activeSearch ? (
            <p className={styles.searchHint}>
              当前搜索：{activeSearch}
            </p>
          ) : null}

          {batchNotice ? (
            <p className={styles.batchNotice} role="status">
              {batchNotice}
            </p>
          ) : null}

          {batchError ? (
            <p className={styles.sellingPointsError} role="alert">
              {batchError}
            </p>
          ) : null}

          {selectedIds.size > 0 ? (
            <div className={styles.batchBar}>
              <span className={styles.batchCount}>
                已选 {selectedIds.size} 个产品
              </span>
              <div className={styles.batchActions}>
                <button
                  className="primary-button"
                  disabled={batchBusy !== null}
                  onClick={() => void handleBatchGenerate("copy")}
                  type="button"
                >
                  {batchBusy === "copy" ? (
                    <LoaderCircle aria-hidden="true" className="spin" size={16} />
                  ) : (
                    <Sparkles aria-hidden="true" size={16} />
                  )}
                  批量生成文案
                </button>
                <button
                  className="secondary-button"
                  disabled={batchBusy !== null}
                  onClick={() => void handleBatchGenerate("brief")}
                  title="作图指令需产品先有文案，缺文案的会跳过失败"
                  type="button"
                >
                  {batchBusy === "brief" ? (
                    <LoaderCircle aria-hidden="true" className="spin" size={16} />
                  ) : (
                    <ClipboardList aria-hidden="true" size={16} />
                  )}
                  批量生成作图指令
                </button>
                <button
                  className="secondary-button"
                  disabled={batchBusy !== null}
                  onClick={clearSelection}
                  type="button"
                >
                  <X aria-hidden="true" size={16} />
                  清空选择
                </button>
              </div>
            </div>
          ) : null}

          {products.length > 0 ? (
            <div className={styles.listMeta}>
              <span>
                显示 {pageStart}-{pageEnd} / 共 {products.length} 条
              </span>
              <div className={styles.pagination}>
                <button
                  className="secondary-button"
                  disabled={currentPage <= 1}
                  onClick={() => goToPage(currentPage - 1)}
                  type="button"
                >
                  上一页
                </button>
                <strong>
                  {currentPage} / {pageCount}
                </strong>
                <button
                  className="secondary-button"
                  disabled={currentPage >= pageCount}
                  onClick={() => goToPage(currentPage + 1)}
                  type="button"
                >
                  下一页
                </button>
              </div>
            </div>
          ) : null}

          {isLoading ? (
            <div className={styles.state} aria-label="正在加载产品">
              <LoaderCircle aria-hidden="true" className="spin" size={22} />
              <span>正在加载产品</span>
            </div>
          ) : null}

          {!isLoading && loadError ? (
            <div className={styles.errorState} role="alert">
              <AlertTriangle aria-hidden="true" size={20} />
              <div>
                <strong>产品接口请求失败</strong>
                <span>{loadError}</span>
              </div>
            </div>
          ) : null}

          {!isLoading && !loadError && products.length === 0 ? (
            <div className={styles.state}>
              <PackageOpen aria-hidden="true" size={22} />
              <span>暂无产品。</span>
            </div>
          ) : null}

          {!isLoading && !loadError && pageItems.length > 0 ? (
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th className={styles.selectCell} scope="col">
                      <input
                        aria-label="全选本页产品"
                        checked={allPageSelected}
                        onChange={toggleSelectAllOnPage}
                        type="checkbox"
                      />
                    </th>
                    <th scope="col">产品</th>
                    <th scope="col">内部编号</th>
                    <th scope="col">品牌</th>
                    <th scope="col">审核</th>
                    <th scope="col">进度</th>
                    <th scope="col">更新时间</th>
                    <th scope="col">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {pageItems.map((product) => {
                    const stageStates = pipelineStates(
                      rowReadiness[product.id] ?? null,
                    );
                    const hasReadiness = product.id in rowReadiness;

                    return (
                        <tr
                          key={product.id}
                          onClick={() => toggleProduct(product.id)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              toggleProduct(product.id);
                            }
                          }}
                          role="button"
                          tabIndex={0}
                        >
                          <td
                            className={styles.selectCell}
                            onClick={(event) => event.stopPropagation()}
                          >
                            <input
                              aria-label="选择该产品"
                              checked={selectedIds.has(product.id)}
                              onChange={() => toggleSelect(product.id)}
                              onClick={(event) => event.stopPropagation()}
                              type="checkbox"
                            />
                          </td>
                          <td>
                            <strong>
                              {product.product_name_en ||
                                displayProductKey(product.product_key)}
                            </strong>
                            <span>{displayProductKey(product.product_key)}</span>
                          </td>
                          <td>{product.parent_sku || product.sku || "未设置"}</td>
                          <td>{product.brand_name || "未设置"}</td>
                          <td>
                            <span className={styles.statusBadge}>
                              {displayReviewStatus(product.review_status)}
                            </span>
                          </td>
                          <td>
                            {hasReadiness ? (
                              <span className={styles.rosterLights}>
                                {stageStates.map((state, index) => (
                                  <span
                                    className={styles.lightDot}
                                    data-state={state}
                                    key={PIPELINE_STAGES[index].code}
                                    title={PIPELINE_STAGES[index].label}
                                  />
                                ))}
                              </span>
                            ) : (
                              <span className={styles.lightsLoading}>· · ·</span>
                            )}
                          </td>
                          <td>{formatDate(product.updated_at)}</td>
                          <td>
                            <div className={styles.rowActions}>
                              <button className="secondary-button" type="button">
                                <ChevronRight aria-hidden="true" size={15} />
                                详情
                              </button>
                              <button
                                className="secondary-button"
                                onClick={(event) => openImageSystem(product, event)}
                                type="button"
                              >
                                <ImagePlus aria-hidden="true" size={15} />
                                Create Image
                              </button>
                              <button
                                className={`secondary-button ${styles.dangerButton}`}
                                onClick={(event) => requestDelete(product, event)}
                                type="button"
                              >
                                <Trash2 aria-hidden="true" size={15} />
                                删除
                              </button>
                            </div>
                          </td>
                        </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      )}

      {deleteCandidate ? (
        <div
          className={styles.modalBackdrop}
          onMouseDown={closeDeleteModal}
          role="presentation"
        >
          <div
            aria-labelledby="delete-product-title"
            aria-modal="true"
            className={styles.confirmModal}
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
          >
            <div className={styles.confirmModalHeading}>
              <div>
                <span className={styles.eyebrow}>删除产品</span>
                <h3 id="delete-product-title">确认删除</h3>
              </div>
              <button
                aria-label="取消删除"
                className="secondary-button"
                disabled={isDeleting}
                onClick={closeDeleteModal}
                type="button"
              >
                <X aria-hidden="true" size={16} />
              </button>
            </div>

            <dl className={styles.confirmMeta}>
              <div>
                <dt>产品名称</dt>
                <dd>
                  {deleteCandidate.product_name_en ||
                    displayProductKey(deleteCandidate.product_key)}
                </dd>
              </div>
              <div>
                <dt>产品ID</dt>
                <dd>{deleteConfirmationKey}</dd>
              </div>
            </dl>

            <label className={styles.field}>
              <span>输入产品ID确认删除</span>
              <input
                autoFocus
                onChange={(event) => setDeleteConfirmation(event.target.value)}
                value={deleteConfirmation}
              />
            </label>

            {deleteError ? (
              <p className={styles.sellingPointsError} role="alert">
                {deleteError}
              </p>
            ) : null}

            <div className={styles.confirmActions}>
              <button
                className="secondary-button"
                disabled={isDeleting}
                onClick={closeDeleteModal}
                type="button"
              >
                取消
              </button>
              <button
                className={`primary-button ${styles.confirmDeleteButton}`}
                disabled={!canConfirmDelete}
                onClick={() => void confirmDelete()}
                type="button"
              >
                {isDeleting ? (
                  <LoaderCircle aria-hidden="true" className="spin" size={16} />
                ) : (
                  <Trash2 aria-hidden="true" size={16} />
                )}
                确认删除
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
