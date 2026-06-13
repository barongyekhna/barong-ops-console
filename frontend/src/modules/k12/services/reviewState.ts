export const reviewStatusFlow = [
  "draft",
  "ai_generated",
  "needs_review",
  "reviewed",
  "approved",
  "rejected",
] as const;

export type ReviewStatus = (typeof reviewStatusFlow)[number];

export const reviewStatusTransitions: Record<
  ReviewStatus,
  readonly ReviewStatus[]
> = {
  draft: ["ai_generated"],
  ai_generated: ["needs_review"],
  needs_review: ["reviewed"],
  reviewed: ["approved", "rejected"],
  approved: [],
  rejected: [],
};

export const diffStatusFlow = [
  "unchanged",
  "changed",
  "added",
  "removed",
  "reordered",
  "overridden",
] as const;

export type DiffStatus = (typeof diffStatusFlow)[number];

export type ReviewStateLog = {
  product_id: string;
  from: ReviewStatus;
  to: ReviewStatus;
  user: string;
  timestamp: string;
};

export type ReviewStateSnapshot = {
  product_id: string;
  status: ReviewStatus;
  updated_at: string;
  state_log: ReviewStateLog[];
};

export const reviewStatusLabels: Record<ReviewStatus, string> = {
  draft: "Draft",
  ai_generated: "AI Generated",
  needs_review: "Needs Review",
  reviewed: "Reviewed",
  approved: "Approved",
  rejected: "Rejected",
};

export const diffStatusLabels: Record<DiffStatus, string> = {
  unchanged: "Same",
  changed: "Changed",
  added: "Added",
  removed: "Removed",
  reordered: "Reordered",
  overridden: "Overridden",
};

export function createReviewState(
  status: ReviewStatus = "draft",
  product_id = "unknown",
): ReviewStateSnapshot {
  return {
    product_id,
    status,
    updated_at: new Date().toISOString(),
    state_log: [],
  };
}

export function getReviewStatusIndex(status: ReviewStatus) {
  return reviewStatusFlow.indexOf(status);
}

export function getNextReviewStatus(status: ReviewStatus) {
  const nextStatus = reviewStatusTransitions[status][0];

  return nextStatus ?? null;
}

export function isReviewStatus(value: string): value is ReviewStatus {
  return reviewStatusFlow.includes(value as ReviewStatus);
}

export function canTransition(from: ReviewStatus, to: ReviewStatus) {
  if (!isReviewStatus(from) || !isReviewStatus(to)) {
    return false;
  }

  return reviewStatusTransitions[from].includes(to);
}

export function transitionState(
  from: ReviewStateSnapshot | ReviewStatus,
  to: ReviewStatus,
  user: string,
): ReviewStateSnapshot {
  const currentState =
    typeof from === "string" ? createReviewState(from) : from;

  if (!canTransition(currentState.status, to)) {
    throw new Error(
      `Invalid review status transition: ${currentState.status} -> ${to}`,
    );
  }

  const timestamp = new Date().toISOString();
  const log: ReviewStateLog = {
    product_id: currentState.product_id,
    from: currentState.status,
    to,
    user,
    timestamp,
  };

  return {
    ...currentState,
    status: to,
    updated_at: timestamp,
    state_log: [...currentState.state_log, log],
  };
}

export function isOverrideDiffStatus(status: DiffStatus) {
  return status !== "unchanged";
}

export function getDiffSummaryStatus(
  statuses: readonly DiffStatus[],
): DiffStatus {
  return statuses.some(isOverrideDiffStatus) ? "overridden" : "unchanged";
}

export function isDiffStatus(value: string): value is DiffStatus {
  return diffStatusFlow.includes(value as DiffStatus);
}
