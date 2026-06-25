"use client";

import {
  AlertTriangle,
  ChevronDown,
  ExternalLink,
  LoaderCircle,
  PackageOpen,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type MouseEvent,
} from "react";

import { generateSellingPoints } from "@/modules/k14/selling-points/api";
import type { ProductSellingPoints } from "@/modules/k14/selling-points/types";

import {
  bindProductImage,
  controlWorkflow,
  createMediaAsset,
  createProduct,
  deleteProduct,
  enrichProductWithDeepSeek,
  exportWorkflow,
  getLatestWorkflow,
  getMediaAssets,
  getProducts,
  PRODUCT_CREATE_FAILURE_MESSAGE,
  ProductKnowledgeApiError,
  reviewWorkflowRiskTerms,
  startWorkflow,
} from "./api";
import { ProductDetail } from "./ProductDetail";
import { ProductForm } from "./ProductForm";
import { displayProductKey } from "./display";
import styles from "./ProductKnowledge.module.css";
import type {
  ProductCreateFormPayload,
  KMediaAsset,
  KRiskReviewDecision,
  KWorkflowExecution,
  KWorkflowExportResponse,
  KWorkflowStartPayload,
  ProductKnowledgeListItem,
  ProductKnowledgeListResponse,
} from "./types";

const PRODUCT_LIST_PAGE_SIZE = 25;

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
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
    if (status === 503) {
      return "K 模块服务配置暂不可用，请检查 API key 绑定或稍后重试。";
    }
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
          <span className={styles.eyebrow}>Products</span>
          <h3 id="product-list-entry">Product List</h3>
        </div>
        <button
          className="primary-button"
          onClick={openFullProductList}
          type="button"
        >
          <ExternalLink aria-hidden="true" size={16} />
          Open Product List
        </button>
      </div>
    </section>
  );
}

export function ProductListFull() {
  const [products, setProducts] = useState<ProductKnowledgeListItem[]>([]);
  const [openProductId, setOpenProductId] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [sellingPointsByProductId, setSellingPointsByProductId] = useState<
    Record<string, ProductSellingPoints>
  >({});
  const [workflowByProductId, setWorkflowByProductId] = useState<
    Record<string, KWorkflowExecution | null>
  >({});
  const [mediaByProductId, setMediaByProductId] = useState<
    Record<string, KMediaAsset[]>
  >({});
  const [exportByProductId, setExportByProductId] = useState<
    Record<string, KWorkflowExportResponse>
  >({});
  const [deleteCandidate, setDeleteCandidate] =
    useState<ProductKnowledgeListItem | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [createError, setCreateError] = useState("");
  const [sellingPointsError, setSellingPointsError] = useState("");
  const [workflowError, setWorkflowError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [generatingProductId, setGeneratingProductId] = useState<string | null>(
    null,
  );
  const [workflowBusyAction, setWorkflowBusyAction] = useState<string | null>(
    null,
  );

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

  const loadProducts = useCallback(
    async (preferredOpenId?: string) => {
      setIsLoading(true);
      setLoadError("");

      try {
        const response = await getProducts();
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
          formatError(error, "The Product Knowledge API is unavailable."),
        );
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void loadProducts();
  }, [loadProducts]);

  const loadWorkflowRuntime = useCallback(async (productId: string) => {
    setWorkflowError("");

    try {
      const [workflow, media] = await Promise.all([
        getLatestWorkflow(productId),
        getMediaAssets(productId),
      ]);
      setWorkflowByProductId((current) => ({
        ...current,
        [productId]: workflow,
      }));
      setMediaByProductId((current) => ({
        ...current,
        [productId]: media.items,
      }));
    } catch (error) {
      setWorkflowError(
        formatError(error, "Workflow runtime state could not be loaded."),
      );
    }
  }, []);

  useEffect(() => {
    if (!openProductId) {
      return;
    }

    void loadWorkflowRuntime(openProductId);
  }, [loadWorkflowRuntime, openProductId]);

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
            "Product was created, but DeepSeek conversion could not be completed.",
          );
        }
      }

      await loadProducts(createdProduct.id);
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
    setSellingPointsError("");
    setWorkflowError("");
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
      setDeleteCandidate(null);
      setDeleteConfirmation("");
      await loadProducts();
    } catch (error) {
      setDeleteError(formatError(error, "Product could not be deleted."));
    } finally {
      setIsDeleting(false);
    }
  }

  function goToPage(page: number) {
    setOpenProductId(null);
    setCurrentPage(Math.min(Math.max(page, 1), pageCount));
  }

  async function handleGenerateSellingPoints() {
    if (!openProduct) {
      return;
    }

    setGeneratingProductId(openProduct.id);
    setSellingPointsError("");

    try {
      const sellingPoints = await generateSellingPoints(
        toSellingPointsProductPayload(openProduct),
      );
      setSellingPointsByProductId((current) => ({
        ...current,
        [openProduct.id]: sellingPoints,
      }));
    } catch (error) {
      setSellingPointsError(
        formatError(error, "Selling points could not be generated."),
      );
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
      setWorkflowError(formatError(error, "Workflow action failed."));
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

  async function handleSubmitRiskReview(
    decisions: KRiskReviewDecision[],
    confirmNoRiskTerms: boolean,
  ) {
    if (!openProduct) {
      return;
    }
    const workflow = workflowByProductId[openProduct.id] ?? null;

    await runWorkflowAction("risk-review", async () => {
      const updated = await reviewWorkflowRiskTerms(openProduct.id, {
        confirm_no_risk_terms: confirmNoRiskTerms,
        decisions,
        execution_id: workflow?.id ?? null,
      });
      setWorkflowByProductId((current) => ({
        ...current,
        [openProduct.id]: updated,
      }));
      await loadWorkflowRuntime(openProduct.id);
    });
  }

  async function handleCreateMedia(url: string, variantSku: string) {
    if (!openProduct) {
      return;
    }

    await runWorkflowAction("media-create", async () => {
      await createMediaAsset({
        asset_role: "main",
        asset_type: "image",
        file_url_placeholder: url,
        filename: url.split("/").pop() || `${variantSku}.jpg`,
        metadata: { upload_mode: "url_placeholder" },
        mime_type: "image/jpeg",
        product_id: openProduct.id,
        source: "manual_upload_image",
        variant_sku: variantSku,
      });
      await loadWorkflowRuntime(openProduct.id);
    });
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

  async function handleExportWorkflow() {
    if (!openProduct) {
      return;
    }
    const workflow = workflowByProductId[openProduct.id] ?? null;

    await runWorkflowAction("export", async () => {
      const exported = await exportWorkflow(openProduct.id, workflow?.id);
      setWorkflowByProductId((current) => ({
        ...current,
        [openProduct.id]: exported.execution,
      }));
      setExportByProductId((current) => ({
        ...current,
        [openProduct.id]: exported,
      }));
    });
  }

  async function handleWorkflowControl(
    action: "pause" | "resume" | "retry" | "rollback",
    step?: string,
  ) {
    if (!openProduct) {
      return;
    }
    const workflow = workflowByProductId[openProduct.id] ?? null;

    await runWorkflowAction(action, async () => {
      const updated = await controlWorkflow(openProduct.id, action, {
        execution_id: workflow?.id ?? null,
        step: step ?? workflow?.current_step ?? null,
        workflow_payload:
          action === "retry"
            ? {
                target_market: workflow?.target_market ?? "US",
                target_region: workflow?.target_region ?? null,
              }
            : null,
      });
      setWorkflowByProductId((current) => ({
        ...current,
        [openProduct.id]: updated,
      }));
      await loadWorkflowRuntime(openProduct.id);
    });
  }

  return (
    <section className={styles.workspace} aria-label="Product Knowledge">
      <ProductForm
        error={createError}
        isSubmitting={isCreating}
        onCreate={handleCreate}
        onDismissError={() => setCreateError("")}
      />

      <div className={styles.contentGrid}>
        <section className={styles.listPanel} aria-labelledby="products-full-title">
          <div className={styles.panelHeading}>
            <div>
              <span className={styles.eyebrow}>Products</span>
              <h3 id="products-full-title">Product List</h3>
            </div>
            <button
              className="secondary-button"
              disabled={isLoading}
              onClick={() => void loadProducts()}
              type="button"
            >
              {isLoading ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <RotateCcw aria-hidden="true" size={16} />
              )}
              Refresh
            </button>
          </div>

          {products.length > 0 ? (
            <div className={styles.listMeta}>
              <span>
                Showing {pageStart}-{pageEnd} of {products.length}
              </span>
              <div className={styles.pagination}>
                <button
                  className="secondary-button"
                  disabled={currentPage <= 1}
                  onClick={() => goToPage(currentPage - 1)}
                  type="button"
                >
                  Previous
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
                  Next
                </button>
              </div>
            </div>
          ) : null}

          {isLoading ? (
            <div className={styles.state} aria-label="Loading products">
              <LoaderCircle aria-hidden="true" className="spin" size={22} />
              <span>Loading products</span>
            </div>
          ) : null}

          {!isLoading && loadError ? (
            <div className={styles.errorState} role="alert">
              <AlertTriangle aria-hidden="true" size={20} />
              <div>
                <strong>Product API request failed</strong>
                <span>{loadError}</span>
              </div>
            </div>
          ) : null}

          {!isLoading && !loadError && products.length === 0 ? (
            <div className={styles.state}>
              <PackageOpen aria-hidden="true" size={22} />
              <span>No products created yet.</span>
            </div>
          ) : null}

          {!isLoading && !loadError && pageItems.length > 0 ? (
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">Product</th>
                    <th scope="col">Internal</th>
                    <th scope="col">Brand</th>
                    <th scope="col">Review</th>
                    <th scope="col">Updated</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pageItems.map((product) => {
                    const isOpen = product.id === openProductId;

                    return (
                      <tr
                        aria-selected={isOpen}
                        className={isOpen ? styles.selectedRow : undefined}
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
                        <td>
                          <strong>
                            {product.product_name_en ||
                              displayProductKey(product.product_key)}
                          </strong>
                          <span>{displayProductKey(product.product_key)}</span>
                        </td>
                        <td>{product.parent_sku || product.sku || "Not set"}</td>
                        <td>{product.brand_name || "Not set"}</td>
                        <td>
                          <span className={styles.statusBadge}>
                            {product.review_status}
                          </span>
                        </td>
                        <td>{formatDate(product.updated_at)}</td>
                        <td>
                          <div className={styles.rowActions}>
                            <button className="secondary-button" type="button">
                              <ChevronDown aria-hidden="true" size={15} />
                              {isOpen ? "Close" : "Detail"}
                            </button>
                            <button
                              className={`secondary-button ${styles.dangerButton}`}
                              onClick={(event) => requestDelete(product, event)}
                              type="button"
                            >
                              <Trash2 aria-hidden="true" size={15} />
                              Delete
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

        <ProductDetail
          exportResult={openProduct ? exportByProductId[openProduct.id] ?? null : null}
          isGeneratingSellingPoints={
            openProduct ? generatingProductId === openProduct.id : false
          }
          isWorkflowBusy={workflowBusyAction !== null}
          mediaAssets={openProduct ? mediaByProductId[openProduct.id] ?? [] : []}
          onGenerateSellingPoints={handleGenerateSellingPoints}
          onBindImage={(assetId, variantSku) =>
            void handleBindImage(assetId, variantSku)
          }
          onBindISystemImage={(imageAssetId, variantSku) =>
            void handleBindISystemImage(imageAssetId, variantSku)
          }
          onCollapse={() => setOpenProductId(null)}
          onCreateMedia={(url, variantSku) => void handleCreateMedia(url, variantSku)}
          onExportWorkflow={() => void handleExportWorkflow()}
          onPauseWorkflow={() => void handleWorkflowControl("pause")}
          onRefreshWorkflow={() =>
            openProduct ? void loadWorkflowRuntime(openProduct.id) : undefined
          }
          onResumeWorkflow={() => void handleWorkflowControl("resume")}
          onRetryWorkflow={(step) => void handleWorkflowControl("retry", step)}
          onRollbackWorkflow={(step) => void handleWorkflowControl("rollback", step)}
          onStartWorkflow={(payload) => void handleStartWorkflow(payload)}
          onSubmitRiskReview={(decisions, confirmNoRiskTerms) =>
            void handleSubmitRiskReview(decisions, confirmNoRiskTerms)
          }
          product={openProduct}
          sellingPoints={
            openProduct ? sellingPointsByProductId[openProduct.id] ?? null : null
          }
          sellingPointsError={sellingPointsError}
          workflow={openProduct ? workflowByProductId[openProduct.id] ?? null : null}
          workflowError={workflowError}
        />
      </div>

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
                <span className={styles.eyebrow}>Delete Product</span>
                <h3 id="delete-product-title">Confirm Delete</h3>
              </div>
              <button
                aria-label="Cancel delete"
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
                <dt>Product name</dt>
                <dd>
                  {deleteCandidate.product_name_en ||
                    displayProductKey(deleteCandidate.product_key)}
                </dd>
              </div>
              <div>
                <dt>Product ID</dt>
                <dd>{deleteConfirmationKey}</dd>
              </div>
            </dl>

            <label className={styles.field}>
              <span>Type Product ID to confirm</span>
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
                Cancel
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
                Confirm Delete
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function toSellingPointsProductPayload(
  product: ProductKnowledgeListItem,
): Record<string, unknown> {
  return {
    id: product.id,
    product_id: product.id,
    product_key: product.product_key,
    sku: product.sku,
    title: product.product_name_en ?? product.product_key,
    product_name_en: product.product_name_en,
    product_type: product.product_type,
    brand_name: product.brand_name,
    raw_input: product.product_name_en ?? product.product_key,
    raw_input_text: product.product_name_en ?? product.product_key,
    parent_sku: product.parent_sku ?? product.sku,
    target_market: product.target_market ?? "US",
    market_tags: [product.target_market ?? "general"],
    variants: product.variants ?? [],
  };
}
