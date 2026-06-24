"use client";

import { AlertTriangle, LoaderCircle, PackageOpen, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { generateSellingPoints } from "@/modules/k14/selling-points/api";
import type { ProductSellingPoints } from "@/modules/k14/selling-points/types";

import { createProduct, getProducts, ProductKnowledgeApiError } from "./api";
import { ProductDetail } from "./ProductDetail";
import { ProductForm } from "./ProductForm";
import styles from "./ProductKnowledge.module.css";
import type {
  ProductKnowledgeCreatePayload,
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
  const [loadError, setLoadError] = useState("");
  const [createError, setCreateError] = useState("");
  const [sellingPointsError, setSellingPointsError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [generatingProductId, setGeneratingProductId] = useState<string | null>(
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

  async function handleCreate(payload: ProductKnowledgeCreatePayload) {
    setIsCreating(true);
    setCreateError("");

    try {
      const createdProduct = await createProduct(payload);
      await loadProducts(createdProduct.id);
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
          isGeneratingSellingPoints={
            selectedProduct ? generatingProductId === selectedProduct.id : false
          }
          onGenerateSellingPoints={handleGenerateSellingPoints}
          product={selectedProduct}
          sellingPoints={
            selectedProduct
              ? sellingPointsByProductId[selectedProduct.id] ?? null
              : null
          }
          sellingPointsError={sellingPointsError}
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
    language: product.canonical_language,
    canonical_language: product.canonical_language,
    market_tags: ["general"],
  };
}
