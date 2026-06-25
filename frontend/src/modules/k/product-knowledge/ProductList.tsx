"use client";

import { AlertTriangle, LoaderCircle, PackageOpen, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { generateSellingPoints } from "@/modules/k14/selling-points/api";
import type { ProductSellingPoints } from "@/modules/k14/selling-points/types";

import {
  bindProductImage,
  controlWorkflow,
  createMediaAsset,
  createProduct,
  enrichProductWithDeepSeek,
  exportWorkflow,
  getLatestWorkflow,
  getMediaAssets,
  getProducts,
  ProductKnowledgeApiError,
  reviewWorkflowRiskTerms,
  startWorkflow,
} from "./api";
import { ProductDetail } from "./ProductDetail";
import { ProductForm } from "./ProductForm";
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
  if (error instanceof ProductKnowledgeApiError || error instanceof Error) {
    return error.message;
  }

  return fallback;
}

function nextSelectedId(
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

  return response.items[0]?.id ?? null;
}

export function ProductList() {
  const [products, setProducts] = useState<ProductKnowledgeListItem[]>([]);
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);
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
  const [loadError, setLoadError] = useState("");
  const [createError, setCreateError] = useState("");
  const [sellingPointsError, setSellingPointsError] = useState("");
  const [workflowError, setWorkflowError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [generatingProductId, setGeneratingProductId] = useState<string | null>(
    null,
  );
  const [workflowBusyAction, setWorkflowBusyAction] = useState<string | null>(
    null,
  );

  const selectedProduct = useMemo(
    () => products.find((product) => product.id === selectedProductId) ?? null,
    [products, selectedProductId],
  );

  const loadProducts = useCallback(
    async (preferredSelectedId?: string) => {
      setIsLoading(true);
      setLoadError("");

      try {
        const response = await getProducts();
        setProducts(response.items);
        setSelectedProductId((currentId) =>
          nextSelectedId(response, currentId, preferredSelectedId),
        );
      } catch (error) {
        setProducts([]);
        setSelectedProductId(null);
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
    if (!selectedProductId) {
      return;
    }

    void loadWorkflowRuntime(selectedProductId);
  }, [loadWorkflowRuntime, selectedProductId]);

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
      setCreateError(
        formatError(error, "The product could not be created."),
      );
      throw error;
    } finally {
      setIsCreating(false);
    }
  }

  function selectProduct(productId: string) {
    setSelectedProductId(productId);
    setSellingPointsError("");
    setWorkflowError("");
  }

  async function handleGenerateSellingPoints() {
    if (!selectedProduct) {
      return;
    }

    setGeneratingProductId(selectedProduct.id);
    setSellingPointsError("");

    try {
      const sellingPoints = await generateSellingPoints(
        toSellingPointsProductPayload(selectedProduct),
      );
      setSellingPointsByProductId((current) => ({
        ...current,
        [selectedProduct.id]: sellingPoints,
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
    if (!selectedProduct) {
      return;
    }

    await runWorkflowAction("start", async () => {
      const workflow = await startWorkflow(selectedProduct.id, payload);
      setWorkflowByProductId((current) => ({
        ...current,
        [selectedProduct.id]: workflow,
      }));
    });
  }

  async function handleSubmitRiskReview(
    decisions: KRiskReviewDecision[],
    confirmNoRiskTerms: boolean,
  ) {
    if (!selectedProduct) {
      return;
    }
    const workflow = workflowByProductId[selectedProduct.id] ?? null;

    await runWorkflowAction("risk-review", async () => {
      const updated = await reviewWorkflowRiskTerms(selectedProduct.id, {
        confirm_no_risk_terms: confirmNoRiskTerms,
        decisions,
        execution_id: workflow?.id ?? null,
      });
      setWorkflowByProductId((current) => ({
        ...current,
        [selectedProduct.id]: updated,
      }));
      await loadWorkflowRuntime(selectedProduct.id);
    });
  }

  async function handleCreateMedia(url: string, variantSku: string) {
    if (!selectedProduct) {
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
        product_id: selectedProduct.id,
        source: "manual_upload_image",
        variant_sku: variantSku,
      });
      await loadWorkflowRuntime(selectedProduct.id);
    });
  }

  async function handleBindImage(assetId: string, variantSku: string) {
    if (!selectedProduct) {
      return;
    }

    await runWorkflowAction("image-bind", async () => {
      const workflow = await bindProductImage(selectedProduct.id, {
        asset_id: assetId,
        source_type: "manual_upload_image",
        variant_sku: variantSku,
      });
      setWorkflowByProductId((current) => ({
        ...current,
        [selectedProduct.id]: workflow,
      }));
      await loadWorkflowRuntime(selectedProduct.id);
    });
  }

  async function handleBindISystemImage(imageAssetId: string, variantSku: string) {
    if (!selectedProduct) {
      return;
    }

    await runWorkflowAction("i-system-image-bind", async () => {
      const workflow = await bindProductImage(selectedProduct.id, {
        i_system_image_asset_id: imageAssetId,
        source_type: "i_system_asset",
        variant_sku: variantSku,
      });
      setWorkflowByProductId((current) => ({
        ...current,
        [selectedProduct.id]: workflow,
      }));
      await loadWorkflowRuntime(selectedProduct.id);
    });
  }

  async function handleExportWorkflow() {
    if (!selectedProduct) {
      return;
    }
    const workflow = workflowByProductId[selectedProduct.id] ?? null;

    await runWorkflowAction("export", async () => {
      const exported = await exportWorkflow(selectedProduct.id, workflow?.id);
      setWorkflowByProductId((current) => ({
        ...current,
        [selectedProduct.id]: exported.execution,
      }));
      setExportByProductId((current) => ({
        ...current,
        [selectedProduct.id]: exported,
      }));
    });
  }

  async function handleWorkflowControl(
    action: "pause" | "resume" | "retry" | "rollback",
    step?: string,
  ) {
    if (!selectedProduct) {
      return;
    }
    const workflow = workflowByProductId[selectedProduct.id] ?? null;

    await runWorkflowAction(action, async () => {
      const updated = await controlWorkflow(selectedProduct.id, action, {
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
        [selectedProduct.id]: updated,
      }));
      await loadWorkflowRuntime(selectedProduct.id);
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
        <section className={styles.listPanel} aria-labelledby="k7-products-title">
          <div className={styles.panelHeading}>
            <div>
              <span className={styles.eyebrow}>Products</span>
              <h3 id="k7-products-title">Product List</h3>
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

          {!isLoading && !loadError && products.length > 0 ? (
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">Product</th>
                    <th scope="col">SKU</th>
                    <th scope="col">Brand</th>
                    <th scope="col">Review</th>
                    <th scope="col">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {products.map((product) => {
                    const isSelected = product.id === selectedProductId;

                    return (
                      <tr
                        aria-selected={isSelected}
                        className={isSelected ? styles.selectedRow : undefined}
                        key={product.id}
                        onClick={() => selectProduct(product.id)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            selectProduct(product.id);
                          }
                        }}
                        role="button"
                        tabIndex={0}
                      >
                        <td>
                          <strong>
                            {product.product_name_en || product.product_key}
                          </strong>
                          <span>{product.product_key}</span>
                        </td>
                        <td>{product.sku || "Not set"}</td>
                        <td>{product.brand_name || "Not set"}</td>
                        <td>
                          <span className={styles.statusBadge}>
                            {product.review_status}
                          </span>
                        </td>
                        <td>{formatDate(product.updated_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>

        <ProductDetail
          exportResult={
            selectedProduct ? exportByProductId[selectedProduct.id] ?? null : null
          }
          isGeneratingSellingPoints={
            selectedProduct ? generatingProductId === selectedProduct.id : false
          }
          isWorkflowBusy={workflowBusyAction !== null}
          mediaAssets={
            selectedProduct ? mediaByProductId[selectedProduct.id] ?? [] : []
          }
          onGenerateSellingPoints={handleGenerateSellingPoints}
          onBindImage={(assetId, variantSku) =>
            void handleBindImage(assetId, variantSku)
          }
          onBindISystemImage={(imageAssetId, variantSku) =>
            void handleBindISystemImage(imageAssetId, variantSku)
          }
          onCreateMedia={(url, variantSku) => void handleCreateMedia(url, variantSku)}
          onExportWorkflow={() => void handleExportWorkflow()}
          onPauseWorkflow={() => void handleWorkflowControl("pause")}
          onRefreshWorkflow={() =>
            selectedProduct ? void loadWorkflowRuntime(selectedProduct.id) : undefined
          }
          onResumeWorkflow={() => void handleWorkflowControl("resume")}
          onRetryWorkflow={(step) => void handleWorkflowControl("retry", step)}
          onRollbackWorkflow={(step) => void handleWorkflowControl("rollback", step)}
          onStartWorkflow={(payload) => void handleStartWorkflow(payload)}
          onSubmitRiskReview={(decisions, confirmNoRiskTerms) =>
            void handleSubmitRiskReview(decisions, confirmNoRiskTerms)
          }
          product={selectedProduct}
          sellingPoints={
            selectedProduct
              ? sellingPointsByProductId[selectedProduct.id] ?? null
              : null
          }
          sellingPointsError={sellingPointsError}
          workflow={selectedProduct ? workflowByProductId[selectedProduct.id] ?? null : null}
          workflowError={workflowError}
        />
      </div>
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
