"use client";

import {
  CheckCircle2,
  Download,
  FileText,
  ImagePlus,
  LoaderCircle,
  Play,
  RotateCcw,
  Send,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import styles from "./ProductKnowledge.module.css";
import type {
  KMediaAsset,
  KRiskReviewDecision,
  KWorkflowExecution,
  KWorkflowExportResponse,
  KWorkflowStartPayload,
  ProductKnowledgeListItem,
} from "./types";
import type { ProductSellingPoints } from "@/modules/k14/selling-points/types";

const TARGET_ORGANIZATION = "涌龙麟（深圳）国际贸易有限公司";
const WORKFLOW_STEPS = [
  "product_ingestion",
  "deepseek_enrichment",
  "serp_keyword_fetch",
  "ai_filter_chatgpt",
  "ai_filter_claude_opus",
  "risk_term_manual_review",
  "keyword_optimization_ai",
  "unit_conversion_normalization",
  "image_binding",
  "export_p_series",
  "export_gmc",
  "export_seo",
];
const WORKFLOW_STEP_ALIASES: Record<string, string[]> = {
  export_p_series: ["export_p_series", "export_p_gmc_seo"],
  image_binding: ["image_binding", "image_handling"],
  risk_term_manual_review: ["risk_term_manual_review", "risk_term_review_manual"],
};

type RiskDecisionValue = "approve" | "reject";

type ProductDetailProps = {
  exportResult?: KWorkflowExportResponse | null;
  isGeneratingSellingPoints?: boolean;
  isWorkflowBusy?: boolean;
  mediaAssets?: KMediaAsset[];
  onBindImage?: (assetId: string, variantSku: string) => void;
  onBindISystemImage?: (imageAssetId: string, variantSku: string) => void;
  onCreateMedia?: (url: string, variantSku: string) => void;
  onExportWorkflow?: () => void;
  onGenerateSellingPoints?: () => void;
  onPauseWorkflow?: () => void;
  onRefreshWorkflow?: () => void;
  onResumeWorkflow?: () => void;
  onRetryWorkflow?: (step: string) => void;
  onRollbackWorkflow?: (step: string) => void;
  onStartWorkflow?: (payload: KWorkflowStartPayload) => void;
  onSubmitRiskReview?: (
    decisions: KRiskReviewDecision[],
    confirmNoRiskTerms: boolean,
  ) => void;
  product: ProductKnowledgeListItem | null;
  sellingPoints?: ProductSellingPoints | null;
  sellingPointsError?: string;
  workflow?: KWorkflowExecution | null;
  workflowError?: string;
};

function displayValue(value: string | null | undefined) {
  return value && value.trim().length > 0 ? value : "Not set";
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "Not set";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function workflowStepStatus(workflow: KWorkflowExecution | null, step: string) {
  if (!workflow) {
    return "pending";
  }
  const aliases = new Set(WORKFLOW_STEP_ALIASES[step] ?? [step]);
  const latest = [...workflow.trace_json]
    .reverse()
    .find((item) => aliases.has(item.step));

  return latest?.status ?? (aliases.has(workflow.current_step) ? workflow.status : "pending");
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

export function ProductDetail({
  exportResult = null,
  isGeneratingSellingPoints = false,
  isWorkflowBusy = false,
  mediaAssets = [],
  onBindImage,
  onBindISystemImage,
  onCreateMedia,
  onExportWorkflow,
  onGenerateSellingPoints,
  onPauseWorkflow,
  onRefreshWorkflow,
  onResumeWorkflow,
  onRetryWorkflow,
  onRollbackWorkflow,
  onStartWorkflow,
  onSubmitRiskReview,
  product,
  sellingPoints = null,
  sellingPointsError = "",
  workflow = null,
  workflowError = "",
}: ProductDetailProps) {
  const [targetMarket, setTargetMarket] = useState("US");
  const [serpQuery, setSerpQuery] = useState("");
  const [mediaUrl, setMediaUrl] = useState("");
  const [selectedVariantSku, setSelectedVariantSku] = useState("");
  const [iSystemImageAssetId, setISystemImageAssetId] = useState("");
  const [riskDecisions, setRiskDecisions] = useState<Record<string, RiskDecisionValue>>(
    {},
  );
  const [riskDecisionError, setRiskDecisionError] = useState("");

  const riskKeywords = useMemo(() => normalizeRiskKeywords(workflow), [workflow]);
  const canExport = workflow?.status === "ready_for_export" || workflow?.status === "exported";
  const selectedVariant = useMemo(
    () =>
      (product?.variants ?? []).find(
        (variant) => variant.variant_sku === selectedVariantSku,
      ) ?? null,
    [product?.variants, selectedVariantSku],
  );

  useEffect(() => {
    setRiskDecisions({});
    setRiskDecisionError("");
  }, [workflow?.id]);

  useEffect(() => {
    const firstVariantSku = product?.variants?.[0]?.variant_sku ?? "";
    setSelectedVariantSku(firstVariantSku);
  }, [product?.id, product?.variants]);

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

  function submitWorkflowStart() {
    onStartWorkflow?.({
      seed_keywords: [],
      serp_query: serpQuery.trim() || null,
      target_market: targetMarket,
    });
  }

  function submitRiskReview() {
    if (riskKeywords.length === 0) {
      onSubmitRiskReview?.([], true);
      return;
    }

    const missing = riskKeywords.filter((item) => !riskDecisions[item.term]);
    if (missing.length > 0) {
      setRiskDecisionError("Every risk keyword needs a manual approve or reject decision.");
      return;
    }

    setRiskDecisionError("");
    onSubmitRiskReview?.(
      riskKeywords.map((item) => {
        const decision = riskDecisions[item.term] as RiskDecisionValue;

        return {
          decision,
          reason: decision === "reject" ? "Rejected in manual review" : null,
          term: item.term,
        };
      }),
      false,
    );
  }

  function createMedia() {
    const value = mediaUrl.trim();
    if (!value) {
      return;
    }
    if (!selectedVariantSku) {
      return;
    }
    onCreateMedia?.(value, selectedVariantSku);
    setMediaUrl("");
  }

  function bindISystemImage() {
    const value = iSystemImageAssetId.trim();
    if (!value) {
      return;
    }
    if (!selectedVariantSku) {
      return;
    }
    onBindISystemImage?.(value, selectedVariantSku);
    setISystemImageAssetId("");
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
          <dt>Organization</dt>
          <dd>{product.organization_name || TARGET_ORGANIZATION}</dd>
        </div>
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
          <dt>Workspace</dt>
          <dd>{product.workspace_key}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{formatDate(product.updated_at)}</dd>
        </div>
      </dl>

      <section className={styles.workflowSection} aria-labelledby="k-workflow-title">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>K Workflow</span>
            <h4 id="k-workflow-title">Product Knowledge Pipeline</h4>
          </div>
          <button
            className="secondary-button"
            disabled={isWorkflowBusy}
            onClick={onRefreshWorkflow}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={16} />
            Refresh
          </button>
        </div>

        {workflowError ? (
          <p className={styles.sellingPointsError}>{workflowError}</p>
        ) : null}

        <dl className={styles.workflowMetrics}>
          <div>
            <dt>Status</dt>
            <dd>{workflow?.status ?? "not_started"}</dd>
          </div>
          <div>
            <dt>Current step</dt>
            <dd>{workflow?.current_step ?? "product_ingestion"}</dd>
          </div>
        </dl>

        <div className={styles.workflowStartGrid}>
          <label className={styles.field}>
            <span>Target market</span>
            <select
              onChange={(event) => setTargetMarket(event.target.value)}
              value={targetMarket}
            >
              <option value="US">US</option>
              <option value="UK">UK</option>
              <option value="EU">EU</option>
              <option value="CN">CN</option>
              <option value="JP">JP</option>
              <option value="KR">KR</option>
              <option value="RU">RU</option>
              <option value="GCC">Middle East</option>
              <option value="LATAM">LATAM</option>
            </select>
          </label>
          <label className={styles.field}>
            <span>SERP query</span>
            <input
              onChange={(event) => setSerpQuery(event.target.value)}
              placeholder={product.product_name_en || product.product_key}
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
            Start
          </button>
        </div>

        <div className={styles.workflowStartGrid}>
          <button
            className="secondary-button"
            disabled={!workflow || isWorkflowBusy || workflow.status === "exported"}
            onClick={onPauseWorkflow}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={16} />
            Pause
          </button>
          <button
            className="secondary-button"
            disabled={!workflow || isWorkflowBusy || workflow.status === "exported"}
            onClick={onResumeWorkflow}
            type="button"
          >
            <Play aria-hidden="true" size={16} />
            Resume
          </button>
          <button
            className="secondary-button"
            disabled={!workflow || isWorkflowBusy || workflow.status === "exported"}
            onClick={() => workflow && onRetryWorkflow?.(workflow.current_step)}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={16} />
            Retry
          </button>
          <button
            className="secondary-button"
            disabled={!workflow || isWorkflowBusy || workflow.status === "exported"}
            onClick={() => workflow && onRollbackWorkflow?.(workflow.current_step)}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={16} />
            Rollback
          </button>
        </div>

        <ol className={styles.workflowSteps}>
          {WORKFLOW_STEPS.map((step) => (
            <li key={step}>
              <span>{step}</span>
              <strong>{workflowStepStatus(workflow, step)}</strong>
            </li>
          ))}
        </ol>
      </section>

      <section className={styles.workflowSection} aria-labelledby="k-risk-review">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>Manual Gate</span>
            <h4 id="k-risk-review">Risk Keyword Review</h4>
          </div>
          <button
            className="secondary-button"
            disabled={!workflow || isWorkflowBusy}
            onClick={submitRiskReview}
            type="button"
          >
            <ShieldCheck aria-hidden="true" size={16} />
            Submit Review
          </button>
        </div>

        {riskDecisionError ? (
          <p className={styles.sellingPointsError}>{riskDecisionError}</p>
        ) : null}

        {riskKeywords.length === 0 ? (
          <p className={styles.sellingPointsEmpty}>
            No risk keywords returned yet. Manual confirmation is still required after
            the dual AI filter completes.
          </p>
        ) : (
          <ul className={styles.riskDecisionList}>
            {riskKeywords.map((item) => (
              <li key={item.term}>
                <div>
                  <strong>{item.term}</strong>
                  {item.reason ? <span>{item.reason}</span> : null}
                </div>
                <div>
                  <button
                    aria-pressed={riskDecisions[item.term] === "approve"}
                    className="secondary-button"
                    onClick={() =>
                      setRiskDecisions((current) => ({
                        ...current,
                        [item.term]: "approve",
                      }))
                    }
                    type="button"
                  >
                    <CheckCircle2 aria-hidden="true" size={15} />
                    Approve
                  </button>
                  <button
                    aria-pressed={riskDecisions[item.term] === "reject"}
                    className="secondary-button"
                    onClick={() =>
                      setRiskDecisions((current) => ({
                        ...current,
                        [item.term]: "reject",
                      }))
                    }
                    type="button"
                  >
                    <XCircle aria-hidden="true" size={15} />
                    Reject
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.workflowSection} aria-labelledby="k-image-system">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>Image Handling</span>
            <h4 id="k-image-system">Variant Images</h4>
          </div>
        </div>

        <label className={styles.field}>
          <span>Variant SKU</span>
          <select
            onChange={(event) => setSelectedVariantSku(event.target.value)}
            value={selectedVariantSku}
          >
            {(product.variants ?? []).map((variant) => (
              <option key={variant.variant_sku} value={variant.variant_sku}>
                {variant.variant_sku}
              </option>
            ))}
          </select>
        </label>

        {selectedVariant ? (
          <div className={styles.variantImageFolder}>
            <strong>Variant image folder</strong>
            <span>{selectedVariant.image_folder}</span>
          </div>
        ) : null}

        <div className={styles.mediaCreateRow}>
          <label className={styles.field}>
            <span>Manual image URL</span>
            <input
              onChange={(event) => setMediaUrl(event.target.value)}
              placeholder="https://example.com/image.jpg"
              value={mediaUrl}
            />
          </label>
          <button
            className="secondary-button"
            disabled={isWorkflowBusy || !mediaUrl.trim() || !selectedVariantSku}
            onClick={createMedia}
            type="button"
          >
            <ImagePlus aria-hidden="true" size={16} />
            Upload
          </button>
        </div>

        <div className={styles.mediaCreateRow}>
          <label className={styles.field}>
            <span>I-system image_asset_id</span>
            <input
              onChange={(event) => setISystemImageAssetId(event.target.value)}
              placeholder="img_asset_..."
              value={iSystemImageAssetId}
            />
          </label>
          <button
            className="secondary-button"
            disabled={
              isWorkflowBusy || !iSystemImageAssetId.trim() || !selectedVariantSku
            }
            onClick={bindISystemImage}
            type="button"
          >
            <Send aria-hidden="true" size={16} />
            Bind
          </button>
        </div>

        <ul className={styles.mediaList}>
          {mediaAssets.map((asset) => (
            <li key={asset.id}>
              <div>
                <strong>{asset.object_key || asset.id}</strong>
                <span>
                  {asset.variant_sku || "no variant"} /{" "}
                  {asset.source || "manual_upload_image"} / {asset.status}
                </span>
              </div>
              <div>
                {asset.file_url_placeholder ? (
                  <a
                    className="secondary-button"
                    href={asset.file_url_placeholder}
                    rel="noreferrer"
                    target="_blank"
                  >
                    <Download aria-hidden="true" size={15} />
                    Download
                  </a>
                ) : null}
                <button
                  className="secondary-button"
                  disabled={
                    isWorkflowBusy ||
                    asset.source === "i_system_asset" ||
                    !asset.variant_sku
                  }
                  onClick={() =>
                    asset.variant_sku
                      ? onBindImage?.(asset.id, asset.variant_sku)
                      : undefined
                  }
                  type="button"
                >
                  <Send aria-hidden="true" size={15} />
                  Bind
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.workflowSection} aria-labelledby="k-export-gate">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>Export Gate</span>
            <h4 id="k-export-gate">P / GMC / SEO</h4>
          </div>
          <button
            className="primary-button"
            disabled={!canExport || isWorkflowBusy}
            onClick={onExportWorkflow}
            type="button"
          >
            <Send aria-hidden="true" size={16} />
            Export
          </button>
        </div>

        {!canExport ? (
          <p className={styles.sellingPointsEmpty}>
            Export unlocks only after dual AI filters, manual risk approval,
            finalized keywords, and manual or I-system image binding.
          </p>
        ) : null}

        {exportResult?.report.export_payloads ? (
          <div className={styles.exportSummary}>
            <strong>Generated payloads</strong>
            <span>{Object.keys(exportResult.report.export_payloads).join(", ")}</span>
          </div>
        ) : null}
      </section>

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
            Generate
          </button>
        </div>

        {sellingPointsError ? (
          <p className={styles.sellingPointsError}>{sellingPointsError}</p>
        ) : null}

        {sellingPoints ? (
          <SellingPointsResult sellingPoints={sellingPoints} />
        ) : (
          <p className={styles.sellingPointsEmpty}>
            Selling points are available as an auxiliary K14 output.
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
