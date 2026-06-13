"use client";

import {
  CheckCircle2,
  FileCheck2,
  Loader2,
  Save,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";

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
} from "../services/k12Api";
import {
  canTransition,
  getReviewStatusIndex,
  reviewStatusFlow,
  reviewStatusLabels,
  type ReviewStatus,
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

export default function ProductReviewPage() {
  const [review, setReview] = useState<ProductReviewRecord | null>(null);
  const [humanEdit, setHumanEdit] = useState<ProductHumanEditFields | null>(
    null,
  );
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

  if (isLoading) {
    return (
      <div className="list-state">
        <Loader2 aria-hidden="true" className="spin" size={18} />
        Loading K12 product review mock
      </div>
    );
  }

  if (!review || !humanEdit) {
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
    <div className="k12-review-workspace">
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

      <div className="k12-review-columns">
        <RawInputPanel rawInput={review.raw_input} />
        <CanonicalPanel canonical={review.ai_canonical} />

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
