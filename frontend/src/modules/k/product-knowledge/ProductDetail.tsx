"use client";

import { FileText } from "lucide-react";

import styles from "./ProductKnowledge.module.css";
import type { ProductKnowledgeListItem } from "./types";

type ProductDetailProps = {
  product: ProductKnowledgeListItem | null;
};

function displayValue(value: string | null | undefined) {
  return value && value.trim().length > 0 ? value : "Not set";
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function ProductDetail({ product }: ProductDetailProps) {
  if (!product) {
    return (
      <aside className={styles.detail} aria-label="Product detail">
        <div className={styles.emptyDetailIcon}>
          <FileText aria-hidden="true" size={22} />
        </div>
        <div>
          <h3>No Product Selected</h3>
          <p>Choose a product from the list to inspect its console state.</p>
        </div>
      </aside>
    );
  }

  return (
    <aside className={styles.detail} aria-label="Product detail">
      <div className={styles.detailHeading}>
        <div>
          <span className={styles.eyebrow}>Detail</span>
          <h3>{displayValue(product.product_name_en)}</h3>
        </div>
        <span className={styles.statusBadge}>{product.review_status}</span>
      </div>

      <dl className={styles.detailGrid}>
        <div>
          <dt>Product key</dt>
          <dd>{product.product_key}</dd>
        </div>
        <div>
          <dt>SKU</dt>
          <dd>{displayValue(product.sku)}</dd>
        </div>
        <div>
          <dt>Brand</dt>
          <dd>{displayValue(product.brand_name)}</dd>
        </div>
        <div>
          <dt>Type</dt>
          <dd>{displayValue(product.product_type)}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{product.product_status}</dd>
        </div>
        <div>
          <dt>Language</dt>
          <dd>{product.canonical_language}</dd>
        </div>
        <div>
          <dt>Workspace</dt>
          <dd>{product.workspace_key}</dd>
        </div>
        <div>
          <dt>Scope</dt>
          <dd>{product.scope_mode}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{formatDate(product.created_at)}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{formatDate(product.updated_at)}</dd>
        </div>
      </dl>
    </aside>
  );
}
