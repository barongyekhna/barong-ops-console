"use client";

import {
  CheckCircle2,
  ChevronUp,
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
import {
  displayProductKey,
  formatVariantDisplayName,
  mediaVariantDisplayName,
} from "./display";
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
const WORKFLOW_STAGES = [
  {
    key: "product",
    label: "产品 / Product",
    steps: ["product_ingestion", "deepseek_enrichment"],
  },
  {
    key: "serp",
    label: "关键词 / SERP",
    steps: ["serp_keyword_fetch"],
  },
  {
    key: "ai",
    label: "AI 筛选 / AI",
    steps: ["ai_filter_chatgpt", "ai_filter_claude_opus", "keyword_optimization_ai"],
  },
  {
    key: "risk",
    label: "风险 / Risk",
    steps: ["risk_term_manual_review"],
  },
  {
    key: "export",
    label: "导出 / Export",
    steps: [
      "unit_conversion_normalization",
      "image_binding",
      "export_p_series",
      "export_gmc",
      "export_seo",
    ],
  },
] as const;
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
  onCollapse?: () => void;
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
  return value && value.trim().length > 0 ? value : "未设置 / Not set";
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "未设置 / Not set";
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

function isCompleteStatus(status: string) {
  return ["completed", "succeeded", "ready_for_export", "exported"].includes(
    status,
  );
}

function isActiveStatus(status: string) {
  return ["created", "queued", "running", "in_progress"].includes(status);
}

function workflowStageStatus(
  workflow: KWorkflowExecution | null,
  stage: (typeof WORKFLOW_STAGES)[number],
) {
  if (!workflow) {
    return "pending";
  }

  const statuses = stage.steps.map((step) => workflowStepStatus(workflow, step));
  if (statuses.some((status) => status === "failed")) {
    return "failed";
  }
  if (statuses.some((status) => status === "blocked")) {
    return "blocked";
  }
  if (statuses.every((status) => isCompleteStatus(status))) {
    return "completed";
  }
  if (
    statuses.some((status) => isActiveStatus(status)) ||
    stage.steps.some((step) =>
      new Set(WORKFLOW_STEP_ALIASES[step] ?? [step]).has(workflow.current_step),
    )
  ) {
    return "running";
  }
  if (statuses.some((status) => isCompleteStatus(status))) {
    return "running";
  }
  return "pending";
}

function workflowStatusLabel(status: string) {
  if (status === "completed" || status === "succeeded" || status === "exported") {
    return "已完成 / Done";
  }
  if (status === "running" || status === "created" || status === "in_progress") {
    return "进行中 / Active";
  }
  if (status === "failed") {
    return "失败 / Failed";
  }
  if (status === "blocked") {
    return "阻塞 / Blocked";
  }
  return "等待 / Pending";
}

function workflowProgressPercent(workflow: KWorkflowExecution | null) {
  if (!workflow) {
    return 0;
  }
  if (workflow.status === "exported") {
    return 100;
  }

  const stageStatuses = WORKFLOW_STAGES.map((stage) =>
    workflowStageStatus(workflow, stage),
  );
  const completedCount = stageStatuses.filter((status) => status === "completed")
    .length;
  const activeCount = stageStatuses.some((status) => status === "running") ? 0.5 : 0;
  return Math.min(
    100,
    Math.max(8, Math.round(((completedCount + activeCount) / WORKFLOW_STAGES.length) * 100)),
  );
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
  onCollapse,
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
  const workflowProgress = useMemo(
    () => workflowProgressPercent(workflow),
    [workflow],
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
          <span className={styles.eyebrow}>详情 / Detail</span>
          <h3>{displayValue(product.product_name_en)}</h3>
        </div>
        <div className={styles.detailActions}>
          <span className={styles.statusBadge}>{product.review_status}</span>
          <button
            className="secondary-button"
            onClick={onCollapse}
            type="button"
          >
            <ChevronUp aria-hidden="true" size={16} />
            收起 / Collapse
          </button>
        </div>
      </div>

      <dl className={styles.detailGrid}>
        <div>
          <dt>组织 / Organization</dt>
          <dd>{product.organization_name || TARGET_ORGANIZATION}</dd>
        </div>
        <div>
          <dt>产品编号 / Product ID</dt>
          <dd>{displayProductKey(product.product_key)}</dd>
        </div>
        <div>
          <dt>父级 SKU / Parent SKU</dt>
          <dd>{displayValue(product.parent_sku ?? product.sku)}</dd>
        </div>
        <div>
          <dt>品牌 / Brand</dt>
          <dd>{displayValue(product.brand_name)}</dd>
        </div>
        <div>
          <dt>类型 / Type</dt>
          <dd>{displayValue(product.product_type)}</dd>
        </div>
        <div>
          <dt>变体 / Variants</dt>
          <dd>{product.variant_count ?? product.variants?.length ?? 0}</dd>
        </div>
        <div>
          <dt>更新 / Updated</dt>
          <dd>{formatDate(product.updated_at)}</dd>
        </div>
      </dl>

      <section className={styles.workflowSection} aria-labelledby="k-workflow-title">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>K</span>
            <h4 id="k-workflow-title">产品流程 / Workflow</h4>
          </div>
          <button
            className="secondary-button"
            disabled={isWorkflowBusy}
            onClick={onRefreshWorkflow}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={16} />
            刷新 / Refresh
          </button>
        </div>

        {workflowError ? (
          <p className={styles.sellingPointsError}>{workflowError}</p>
        ) : null}

        <dl className={styles.workflowMetrics}>
          <div>
            <dt>状态 / Status</dt>
            <dd>{workflow?.status ?? "not_started"}</dd>
          </div>
          <div>
            <dt>进度 / Progress</dt>
            <dd>{workflowProgress}%</dd>
          </div>
        </dl>

        <div
          aria-label="Workflow progress"
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={workflowProgress}
          className={styles.workflowProgress}
          role="progressbar"
        >
          <span style={{ width: `${workflowProgress}%` }} />
        </div>

        <ol className={styles.workflowStages}>
          {WORKFLOW_STAGES.map((stage) => {
            const status = workflowStageStatus(workflow, stage);

            return (
              <li data-status={status} key={stage.key}>
                <span>{stage.label}</span>
                <strong>{workflowStatusLabel(status)}</strong>
              </li>
            );
          })}
        </ol>

        <div className={styles.workflowStartGrid}>
          <label className={styles.field}>
            <span>目标市场 / Target Market</span>
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
            <span>关键词查询 / SERP Query</span>
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
            Start Keyword Research
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
            暂停 / Pause
          </button>
          <button
            className="secondary-button"
            disabled={!workflow || isWorkflowBusy || workflow.status === "exported"}
            onClick={onResumeWorkflow}
            type="button"
          >
            <Play aria-hidden="true" size={16} />
            继续 / Resume
          </button>
          <button
            className="secondary-button"
            disabled={!workflow || isWorkflowBusy || workflow.status === "exported"}
            onClick={() => workflow && onRetryWorkflow?.(workflow.current_step)}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={16} />
            重试 / Retry
          </button>
          <button
            className="secondary-button"
            disabled={!workflow || isWorkflowBusy || workflow.status === "exported"}
            onClick={() => workflow && onRollbackWorkflow?.(workflow.current_step)}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={16} />
            回退 / Rollback
          </button>
        </div>
      </section>

      <section className={styles.workflowSection} aria-labelledby="k-risk-review">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>人工审核 / Manual Gate</span>
            <h4 id="k-risk-review">风险词审核 / Risk Review</h4>
          </div>
          <button
            className="secondary-button"
            disabled={!workflow || isWorkflowBusy}
            onClick={submitRiskReview}
            type="button"
          >
            <ShieldCheck aria-hidden="true" size={16} />
            提交审核 / Submit
          </button>
        </div>

        {riskDecisionError ? (
          <p className={styles.sellingPointsError}>{riskDecisionError}</p>
        ) : null}

        {riskKeywords.length === 0 ? (
          <p className={styles.sellingPointsEmpty}>
            暂无风险词。双 AI 筛选完成后仍需人工确认。
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
                    通过 / Approve
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
                    拒绝 / Reject
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
            <span className={styles.eyebrow}>图片 / Images</span>
            <h4 id="k-image-system">变体图片 / Variant Images</h4>
          </div>
        </div>

        <label className={styles.field}>
          <span>变体 / Variant</span>
          <select
            onChange={(event) => setSelectedVariantSku(event.target.value)}
            value={selectedVariantSku}
          >
            {(product.variants ?? []).map((variant) => (
              <option key={variant.variant_sku} value={variant.variant_sku}>
                {formatVariantDisplayName(variant)}
              </option>
            ))}
          </select>
        </label>

        {selectedVariant ? (
          <div className={styles.variantImageFolder}>
            <strong>图片绑定目标 / Image Target</strong>
            <span>{formatVariantDisplayName(selectedVariant)}</span>
          </div>
        ) : null}

        <div className={styles.mediaCreateRow}>
          <label className={styles.field}>
            <span>图片 URL / Manual Image URL</span>
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
            上传 / Upload
          </button>
        </div>

        <div className={styles.mediaCreateRow}>
          <label className={styles.field}>
            <span>I-system 图片 ID / image_asset_id</span>
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
            绑定 / Bind
          </button>
        </div>

        <ul className={styles.mediaList}>
          {mediaAssets.map((asset) => (
            <li key={asset.id}>
              <div>
                <strong>{asset.object_key || asset.id}</strong>
                <span>
                  {mediaVariantDisplayName(product.variants, asset.variant_sku)} /{" "}
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
                  绑定 / Bind
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.workflowSection} aria-labelledby="k-export-gate">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>导出 / Export</span>
            <h4 id="k-export-gate">P / GMC / SEO</h4>
          </div>
          <button
            className="primary-button"
            disabled={!canExport || isWorkflowBusy}
            onClick={onExportWorkflow}
            type="button"
          >
            <Send aria-hidden="true" size={16} />
            导出 / Export
          </button>
        </div>

        {!canExport ? (
          <p className={styles.sellingPointsEmpty}>
            双 AI 筛选、风险审核、关键词确认和图片绑定完成后可导出。
          </p>
        ) : null}

        {exportResult?.report.export_payloads ? (
          <div className={styles.exportSummary}>
            <strong>已生成载荷 / Generated Payloads</strong>
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
            <span className={styles.eyebrow}>卖点 / Selling Points</span>
            <h4 id="k7-selling-points">生成卖点 / Generated</h4>
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
            生成 / Generate
          </button>
        </div>

        {sellingPointsError ? (
          <p className={styles.sellingPointsError}>{sellingPointsError}</p>
        ) : null}

        {sellingPoints ? (
          <SellingPointsResult sellingPoints={sellingPoints} />
        ) : (
          <p className={styles.sellingPointsEmpty}>
            点击生成后显示产品卖点。
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
          <dt>置信度 / Confidence</dt>
          <dd>{Math.round(sellingPoints.confidence_score * 100)}%</dd>
        </div>
        <div>
          <dt>来源 / Source</dt>
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

      <TagGroup label="SEO 关键词 / SEO Keywords" values={sellingPoints.seo_keywords} />
      <TagGroup label="市场标签 / Market Tags" values={sellingPoints.market_tags} />
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
