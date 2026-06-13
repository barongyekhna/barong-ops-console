export const reviewStatusFlow = [
  "draft",
  "ai_generated",
  "needs_review",
  "reviewed",
  "approved",
  "rejected",
] as const;

export type ReviewStatus = (typeof reviewStatusFlow)[number];

export const diffStatusFlow = [
  "unchanged",
  "changed",
  "added",
  "removed",
  "reordered",
  "overridden",
] as const;

export type DiffStatus = (typeof diffStatusFlow)[number];

export type ReviewStateSnapshot = {
  status: ReviewStatus;
  updated_at: string;
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
): ReviewStateSnapshot {
  return {
    status,
    updated_at: new Date().toISOString(),
  };
}

export function getReviewStatusIndex(status: ReviewStatus) {
  return reviewStatusFlow.indexOf(status);
}

export function getNextReviewStatus(status: ReviewStatus) {
  const nextStatus = reviewStatusFlow[getReviewStatusIndex(status) + 1];

  return nextStatus ?? null;
}

export function isReviewStatus(value: string): value is ReviewStatus {
  return reviewStatusFlow.includes(value as ReviewStatus);
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
