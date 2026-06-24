"use client";

import { FileText, LoaderCircle, Sparkles } from "lucide-react";

import styles from "./ProductKnowledge.module.css";
import type { ProductKnowledgeListItem } from "./types";
import type { ProductSellingPoints } from "@/modules/k14/selling-points/types";

type ProductDetailProps = {
  isGeneratingSellingPoints?: boolean;
  onGenerateSellingPoints?: () => void;
  product: ProductKnowledgeListItem | null;
  sellingPoints?: ProductSellingPoints | null;
  sellingPointsError?: string;
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

export function ProductDetail({
  isGeneratingSellingPoints = false,
  onGenerateSellingPoints,
  product,
  sellingPoints = null,
  sellingPointsError = "",
}: ProductDetailProps) {
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

      <section
        aria-labelledby="k7-selling-points"
        className={styles.sellingPointsSection}
      >
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>K14 Selling Points</span>
            <h4 id="k7-selling-points">Generated Selling Points</h4>
          </div>
          <button
            className="secondary-button"
            disabled={isGeneratingSellingPoints}
            onClick={onGenerateSellingPoints}
            type="button"
          >
            {isGeneratingSellingPoints ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <Sparkles aria-hidden="true" size={16} />
            )}
            Generate Selling Points
          </button>
        </div>

        {sellingPointsError ? (
          <p className={styles.sellingPointsError}>{sellingPointsError}</p>
        ) : null}

        {sellingPoints ? (
          <SellingPointsResult sellingPoints={sellingPoints} />
        ) : (
          <p className={styles.sellingPointsEmpty}>
            Select Generate Selling Points to load the K14 structured output.
          </p>
        )}
      </section>
    </aside>
  );
}

function SellingPointsResult({
  sellingPoints,
}: {
  sellingPoints: ProductSellingPoints;
}) {
  return (
    <div className={styles.sellingPointsResult}>
      <dl className={styles.sellingPointsMetrics}>
        <div>
          <dt>Confidence</dt>
          <dd>{Math.round(sellingPoints.confidence_score * 100)}%</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>{sellingPoints.source}</dd>
        </div>
      </dl>

      <ul className={styles.sellingPointBullets}>
        {sellingPoints.bullets.map((bullet, index) => (
          <li key={`${bullet.category}-${index}-${bullet.text}`}>
            <span>{bullet.category}</span>
            <strong>{bullet.text}</strong>
            <em>{bullet.importance_score}</em>
          </li>
        ))}
      </ul>

      <TagGroup label="SEO Keywords" values={sellingPoints.seo_keywords} />
      <TagGroup label="Market Tags" values={sellingPoints.market_tags} />
    </div>
  );
}

function TagGroup({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) {
    return null;
  }

  return (
    <div className={styles.sellingPointTagGroup}>
      <span>{label}</span>
      <div>
        {values.map((value) => (
          <strong key={value}>{value}</strong>
        ))}
      </div>
    </div>
  );
}
