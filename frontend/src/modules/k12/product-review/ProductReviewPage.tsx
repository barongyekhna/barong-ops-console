"use client";

import {
  CheckCircle2,
  FileCheck2,
  Loader2,
  PencilLine,
  Save,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";

import styles from "./ProductReviewPage.module.css";
import { CanonicalPanel } from "../components/CanonicalPanel";
import { FieldDiffViewer } from "../components/FieldDiffViewer";
import { HumanEditPanel } from "../components/HumanEditPanel";
import { RawInputPanel } from "../components/RawInputPanel";
import {
  approve,
  getProductReview,
  markAiGenerated,
  markReviewed,
  productReviewFieldLabels,
  productReviewFields,
  reject,
  requestReview,
  saveDraft,
  type ProductHumanEditFields,
  type ProductReviewRecord,
  type ReviewItem,
} from "../services/k12Api";
import {
  canTransition,
  canTransitionReviewItemStatus,
  getReviewItemStatusIndex,
  getReviewStatusIndex,
  reviewItemStatusFlow,
  reviewItemStatusLabels,
  reviewStatusFlow,
  reviewStatusLabels,
  type ReviewItemStatus,
  type ReviewStatus,
  type VersionRecord,
} from "../services/reviewState";

type TransitionReviewAction =
  | "aiGenerated"
  | "needsReview"
  | "reviewed"
  | "approve"
  | "reject";
type ReviewAction = "save" | TransitionReviewAction;

const actionLabels: Record<ReviewAction, string> = {
  save: "Save Draft",
  aiGenerated: "Generate AI",
  needsReview: "Send to Review",
  reviewed: "Mark as Reviewed",
  approve: "Approve",
  reject: "Reject",
};

const transitionActionTargetStatus: Record<
  TransitionReviewAction,
  ReviewStatus
> = {
  aiGenerated: "ai_generated",
  needsReview: "needs_review",
  reviewed: "reviewed",
  approve: "approved",
  reject: "rejected",
};

const approvalActionLabels: Record<ReviewItemStatus, string> = {
  draft: "Edit Canonical",
  pending_review: "Save Edit",
  approved: "Approve Canonical",
  rejected: "Reject Canonical",
};

export default function ProductReviewPage() {
  const [review, setReview] = useState<ProductReviewRecord | null>(null);
  const [humanEdit, setHumanEdit] = useState<ProductHumanEditFields | null>(
    null,
  );
  const [reviewItem, setReviewItem] = useState<ReviewItem | null>(null);
  const [isEditingCanonical, setIsEditingCanonical] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState<ReviewAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadReview() {
      try {
        const nextReview = await getProductReview();

        if (!isMounted) {
          return;
        }

        setReview(nextReview);
        setHumanEdit(nextReview.human_edit);
        setReviewItem(nextReview.review_item);
      } catch {
        if (isMounted) {
          setError("Unable to load mock product review.");
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    void loadReview();

    return () => {
      isMounted = false;
    };
  }, []);

  async function runAction(
    action: ReviewAction,
    handler: (
      fields: ProductHumanEditFields,
    ) => Promise<ProductReviewRecord>,
  ) {
    if (!humanEdit) {
      return;
    }

    setPendingAction(action);
    setError(null);

    try {
      const nextReview = await handler(humanEdit);
      setReview(nextReview);
      setHumanEdit(nextReview.human_edit);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : `${actionLabels[action]} failed in local mock mode.`,
      );
    } finally {
      setPendingAction(null);
    }
  }

  function updateCanonicalPlaceholder(value: string) {
    setReviewItem((currentItem) =>
      currentItem
        ? {
            ...currentItem,
            canonical: value,
            status: "draft",
          }
        : currentItem,
    );
  }

  function setReviewItemStatus(nextStatus: ReviewItemStatus) {
    setReviewItem((currentItem) =>
      currentItem
        ? {
            ...currentItem,
            status: nextStatus,
          }
        : currentItem,
    );
  }

  function handleEditCanonical() {
    if (!reviewItem) {
      return;
    }

    if (isEditingCanonical) {
      if (canTransitionReviewItemStatus(reviewItem.status, "pending_review")) {
        setReviewItemStatus("pending_review");
      }
      setIsEditingCanonical(false);
      return;
    }

    if (canTransitionReviewItemStatus(reviewItem.status, "draft")) {
      setReviewItemStatus("draft");
      setIsEditingCanonical(true);
    }
  }

  function handleApprovalDecision(nextStatus: "approved" | "rejected") {
    if (!reviewItem) {
      return;
    }

    if (canTransitionReviewItemStatus(reviewItem.status, nextStatus)) {
      setReviewItemStatus(nextStatus);
      setIsEditingCanonical(false);
    }
  }

  if (isLoading) {
    return (
      <div className="list-state">
        <Loader2 aria-hidden="true" className="spin" size={18} />
        Loading K12 product review mock
      </div>
    );
  }

  if (!review || !humanEdit || !reviewItem) {
    return (
      <div className="list-state list-error">
        <div>
          <h2>K12 review unavailable</h2>
          <p>{error ?? "No mock review record was returned."}</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`${styles.scope} k12-review-workspace`}>
      <header className="k12-review-header">
        <div>
          <span className="eyebrow">K12 Product Knowledge</span>
          <h2>Human-in-the-loop Review</h2>
        </div>

        <div className="k12-review-actions" aria-label="Review actions">
          <button
            className="secondary-button"
            disabled={isReviewActionDisabled(
              "save",
              review.status,
              pendingAction,
            )}
            onClick={() => void runAction("save", saveDraft)}
            type="button"
          >
            {pendingAction === "save" ? (
              <Loader2 aria-hidden="true" className="spin" size={16} />
            ) : (
              <Save aria-hidden="true" size={16} />
            )}
            Save Draft
          </button>
          <button
            className="secondary-button"
            disabled={isReviewActionDisabled(
              "aiGenerated",
              review.status,
              pendingAction,
            )}
            onClick={() => void runAction("aiGenerated", markAiGenerated)}
            type="button"
          >
            {pendingAction === "aiGenerated" ? (
              <Loader2 aria-hidden="true" className="spin" size={16} />
            ) : (
              <FileCheck2 aria-hidden="true" size={16} />
            )}
            Generate AI
          </button>
          <button
            className="secondary-button"
            disabled={isReviewActionDisabled(
              "needsReview",
              review.status,
              pendingAction,
            )}
            onClick={() => void runAction("needsReview", requestReview)}
            type="button"
          >
            {pendingAction === "needsReview" ? (
              <Loader2 aria-hidden="true" className="spin" size={16} />
            ) : (
              <FileCheck2 aria-hidden="true" size={16} />
            )}
            Send to Review
          </button>
          <button
            className="secondary-button"
            disabled={isReviewActionDisabled(
              "reviewed",
              review.status,
              pendingAction,
            )}
            onClick={() => void runAction("reviewed", markReviewed)}
            type="button"
          >
            {pendingAction === "reviewed" ? (
              <Loader2 aria-hidden="true" className="spin" size={16} />
            ) : (
              <FileCheck2 aria-hidden="true" size={16} />
            )}
            Mark as Reviewed
          </button>
          <button
            className="primary-button"
            disabled={isReviewActionDisabled(
              "approve",
              review.status,
              pendingAction,
            )}
            onClick={() => void runAction("approve", approve)}
            type="button"
          >
            {pendingAction === "approve" ? (
              <Loader2 aria-hidden="true" className="spin" size={16} />
            ) : (
              <CheckCircle2 aria-hidden="true" size={16} />
            )}
            Approve
          </button>
          <button
            className="danger-button"
            disabled={isReviewActionDisabled(
              "reject",
              review.status,
              pendingAction,
            )}
            onClick={() => void runAction("reject", reject)}
            type="button"
          >
            {pendingAction === "reject" ? (
              <Loader2 aria-hidden="true" className="spin" size={16} />
            ) : (
              <XCircle aria-hidden="true" size={16} />
            )}
            Reject
          </button>
        </div>
      </header>

      <section className="k12-review-meta" aria-label="Review metadata">
        <strong className="k12-review-status-badge">
          {reviewStatusLabels[review.status]}
        </strong>
        <span>{review.review_id}</span>
        <span>{review.product_id}</span>
        <span>{new Date(review.updated_at).toLocaleString()}</span>
      </section>

      <section
        className="k12-review-approval-panel"
        aria-labelledby="k12-approval-layer"
      >
        <div className="k12-review-approval-heading">
          <div>
            <span className="eyebrow">Canonical Approval</span>
            <h3 id="k12-approval-layer">Review Item State</h3>
          </div>
          <strong className="k12-review-status-badge">
            {reviewItemStatusLabels[reviewItem.status]}
          </strong>
        </div>

        <dl className="k12-review-item-summary">
          <div>
            <dt>Review item</dt>
            <dd>{reviewItem.id}</dd>
          </div>
          <div>
            <dt>Raw input</dt>
            <dd>{reviewItem.raw}</dd>
          </div>
          <div>
            <dt>Canonical placeholder</dt>
            <dd>{reviewItem.canonical}</dd>
          </div>
          <div>
            <dt>K13 hook</dt>
            <dd>{reviewItem.ai_suggestion}</dd>
          </div>
        </dl>

        <ol
          className="k12-review-status-rail k12-review-approval-rail"
          aria-label="Canonical approval state flow"
        >
          {reviewItemStatusFlow.map((status) => (
            <li
              className={getReviewItemStepClass(status, reviewItem.status)}
              key={status}
            >
              {reviewItemStatusLabels[status]}
            </li>
          ))}
        </ol>

        <div className="k12-review-actions" aria-label="Canonical actions">
          <button
            className="secondary-button"
            disabled={
              reviewItem.status === "approved" ||
              reviewItem.status === "rejected"
            }
            onClick={handleEditCanonical}
            type="button"
          >
            {isEditingCanonical ? (
              <Save aria-hidden="true" size={16} />
            ) : (
              <PencilLine aria-hidden="true" size={16} />
            )}
            {isEditingCanonical
              ? approvalActionLabels.pending_review
              : approvalActionLabels.draft}
          </button>
          <button
            className="primary-button"
            disabled={
              !canTransitionReviewItemStatus(reviewItem.status, "approved")
            }
            onClick={() => handleApprovalDecision("approved")}
            type="button"
          >
            <CheckCircle2 aria-hidden="true" size={16} />
            {approvalActionLabels.approved}
          </button>
          <button
            className="danger-button"
            disabled={
              !canTransitionReviewItemStatus(reviewItem.status, "rejected")
            }
            onClick={() => handleApprovalDecision("rejected")}
            type="button"
          >
            <XCircle aria-hidden="true" size={16} />
            {approvalActionLabels.rejected}
          </button>
        </div>
      </section>

      {review.state_log.length > 0 ? (
        <section className="k12-review-meta" aria-label="Review state log">
          <strong className="k12-review-status-badge">State Log</strong>
          {review.state_log.map((log) => (
            <span key={`${log.product_id}-${log.timestamp}-${log.to}`}>
              {reviewStatusLabels[log.from]} {" -> "}
              {reviewStatusLabels[log.to]} by {log.user} at{" "}
              {new Date(log.timestamp).toLocaleString()}
            </span>
          ))}
        </section>
      ) : null}

      {review.version_record.length > 0 ? (
        <section
          className="k12-review-panel"
          aria-labelledby="k12-version-record"
        >
          <header className="k12-review-panel-heading">
            <span className="eyebrow">Version Record</span>
            <h3 id="k12-version-record">Audit History</h3>
          </header>

          <div className="k12-review-diff-stack">
            {[...review.version_record].reverse().map((version, index) => (
              <VersionRecordCard
                key={version.version_id}
                version={version}
                versionNumber={review.version_record.length - index}
              />
            ))}
          </div>
        </section>
      ) : null}

      <ol className="k12-review-status-rail" aria-label="Review state flow">
        {reviewStatusFlow.map((status) => (
          <li
            className={getStatusStepClass(status, review.status)}
            key={status}
          >
            {reviewStatusLabels[status]}
          </li>
        ))}
      </ol>

      {error ? <p className="form-message">{error}</p> : null}

      <section
        className="k12-review-panel k12-review-raw-canonical-diff"
        aria-labelledby="k12-raw-canonical-diff"
      >
        <header className="k12-review-panel-heading">
          <span className="eyebrow">Diff Enhancement</span>
          <h3 id="k12-raw-canonical-diff">Raw vs Canonical</h3>
        </header>
        <FieldDiffViewer
          aiValue={reviewItem.raw}
          field="raw_vs_canonical"
          humanValue={reviewItem.canonical}
          label="Raw vs Canonical"
          leftLabel="Raw Input"
          overlayLabel="Mock AI Diff Overlay"
          overlayValue={reviewItem.ai_suggestion}
          rightLabel="Canonical Placeholder"
        />
      </section>

      <div className="k12-review-columns">
        <RawInputPanel rawInput={review.raw_input} />
        <CanonicalPanel
          canonical={review.ai_canonical}
          isEditingCanonical={isEditingCanonical}
          onCanonicalChange={updateCanonicalPlaceholder}
          rawInput={review.raw_input}
          reviewItem={reviewItem}
        />

        <section
          className="k12-review-panel k12-review-human-column"
          aria-labelledby="k12-human-edit"
        >
          <header className="k12-review-panel-heading">
            <span className="eyebrow">Human Edit</span>
            <h3 id="k12-human-edit">Reviewer Override</h3>
          </header>

          <HumanEditPanel onChange={setHumanEdit} value={humanEdit} />

          <div className="k12-review-diff-stack">
            <header className="k12-review-panel-heading">
              <span className="eyebrow">Diff</span>
              <h3>AI Value vs Human Value</h3>
            </header>

            {productReviewFields.map((field) => (
              <FieldDiffViewer
                aiValue={review.ai_canonical[field]}
                humanValue={humanEdit[field]}
                key={field}
                label={productReviewFieldLabels[field]}
              />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function VersionRecordCard({
  version,
  versionNumber,
}: {
  version: VersionRecord;
  versionNumber: number;
}) {
  return (
    <section
      aria-label={`Version ${versionNumber} audit record`}
      className="k12-review-diff k12-review-diff-changed"
    >
      <header className="k12-review-diff-header">
        <strong>Version {versionNumber}</strong>
        <span>{version.changed_fields.length} fields</span>
      </header>

      <div className="k12-review-diff-grid">
        <div>
          <span>Version ID</span>
          <pre>{version.version_id}</pre>
        </div>
        <div>
          <span>User / Time</span>
          <pre>
            {version.user}
            {"\n"}
            {new Date(version.timestamp).toLocaleString()}
          </pre>
        </div>
        <div style={{ gridColumn: "1 / -1" }}>
          <span>Changed Fields</span>
          <pre>{formatVersionJson(version.changed_fields)}</pre>
        </div>
        <div>
          <span>Before State</span>
          <pre>{formatVersionJson(version.before_state)}</pre>
        </div>
        <div>
          <span>After State</span>
          <pre>{formatVersionJson(version.after_state)}</pre>
        </div>
        <div style={{ gridColumn: "1 / -1" }}>
          <span>State Snapshot</span>
          <pre>{formatVersionJson(version.state_snapshot)}</pre>
        </div>
      </div>
    </section>
  );
}

function formatVersionJson(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function isReviewActionDisabled(
  action: ReviewAction,
  currentStatus: ReviewStatus,
  pendingAction: ReviewAction | null,
) {
  if (pendingAction) {
    return true;
  }

  if (action === "save") {
    return currentStatus !== "draft";
  }

  return !canTransition(currentStatus, transitionActionTargetStatus[action]);
}

function getStatusStepClass(status: ReviewStatus, currentStatus: ReviewStatus) {
  const baseClass = "k12-review-status-step";

  const statusIndex = getReviewStatusIndex(status);
  const currentIndex = getReviewStatusIndex(currentStatus);

  if (status === currentStatus) {
    return `${baseClass} k12-review-status-step-active`;
  }

  if (
    (currentStatus === "approved" && status === "rejected") ||
    (currentStatus === "rejected" && status === "approved")
  ) {
    return baseClass;
  }

  if (statusIndex < currentIndex) {
    return `${baseClass} k12-review-status-step-complete`;
  }

  return baseClass;
}

function getReviewItemStepClass(
  status: ReviewItemStatus,
  currentStatus: ReviewItemStatus,
) {
  const baseClass = "k12-review-status-step";

  if (status === currentStatus) {
    return `${baseClass} k12-review-status-step-active`;
  }

  const statusIndex = getReviewItemStatusIndex(status);
  const currentIndex = getReviewItemStatusIndex(currentStatus);

  if (
    (currentStatus === "approved" && status === "rejected") ||
    (currentStatus === "rejected" && status === "approved")
  ) {
    return baseClass;
  }

  if (statusIndex < currentIndex) {
    return `${baseClass} k12-review-status-step-complete`;
  }

  return baseClass;
}
