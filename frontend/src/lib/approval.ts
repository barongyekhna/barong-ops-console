import { apiRequest } from "@/lib/api";

export const APPROVAL_LIST_DEFAULT_LIMIT = 10;
export const APPROVAL_LIST_MAX_LIMIT = 100;
export const APPROVAL_LIST_TIMEOUT_MS = 12_000;

export type ApprovalCategory = "control_plane" | "feature";
export type ApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "auto_approved";
export type ApprovalListAvailability = "ok" | "degraded";

export type ApprovalDisplayInfo = {
  title: string;
  category_label: string;
  module_label: string;
  action_label: string;
  status_label: string;
  risk_label: string;
  summary: string;
};

export type ApprovalListItem = {
  approval_id: string;
  request_time: string;
  status: ApprovalStatus;
  category: ApprovalCategory;
  display: ApprovalDisplayInfo;
};

export type ApprovalListResponse = {
  count: number;
  cursor: string | null;
  degraded: boolean;
  items: ApprovalListItem[];
  limit: number;
  message: string;
  next_cursor: string | null;
  offset: number;
  source: string;
  status: ApprovalListAvailability;
};

export type ApprovalDecisionRecord = {
  status: ApprovalStatus;
  reason: string;
  actor_id: number | null;
  decision_time: string;
};

export type ApprovalDetail = {
  approval: {
    approval_id: string;
    request_time: string;
    status: ApprovalStatus;
    category: ApprovalCategory;
  };
  decisions: ApprovalDecisionRecord[];
  display: ApprovalDisplayInfo;
  permission_boundary: {
    allowed_actions: string[];
  };
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function numberValue(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function normalizeCategory(value: unknown): ApprovalCategory {
  return value === "control_plane" ? "control_plane" : "feature";
}

function normalizeStatus(value: unknown): ApprovalStatus {
  if (
    value === "approved" ||
    value === "rejected" ||
    value === "auto_approved"
  ) {
    return value;
  }
  return "pending";
}

function normalizeDisplay(value: unknown): ApprovalDisplayInfo {
  const record = isRecord(value) ? value : {};
  const categoryLabel = stringValue(record.category_label, "功能审批");
  const moduleLabel = stringValue(record.module_label, "业务");
  const title = stringValue(record.title, "提交业务模块审批");

  return {
    action_label: stringValue(record.action_label, title),
    category_label: categoryLabel,
    module_label: moduleLabel,
    risk_label: stringValue(record.risk_label, "标准风险"),
    status_label: stringValue(record.status_label, "待审批"),
    summary: stringValue(
      record.summary,
      `${moduleLabel}模块已完成草稿，即将提交审批`,
    ),
    title,
  };
}

function normalizeListItem(value: unknown): ApprovalListItem | null {
  if (!isRecord(value)) {
    return null;
  }

  const approvalId = stringValue(value.approval_id);
  if (!approvalId) {
    return null;
  }

  return {
    approval_id: approvalId,
    category: normalizeCategory(value.category),
    display: normalizeDisplay(value.display),
    request_time: stringValue(value.request_time),
    status: normalizeStatus(value.status),
  };
}

function normalizeListResponse(value: unknown): ApprovalListResponse {
  const record = isRecord(value) ? value : {};
  const rawItems = Array.isArray(record.items)
    ? record.items
    : Array.isArray(record.data)
      ? record.data
      : [];
  const items = rawItems
    .map(normalizeListItem)
    .filter((item): item is ApprovalListItem => item !== null);
  const degraded =
    record.status === "degraded" || booleanValue(record.degraded, false);
  const error = isRecord(record.error) ? record.error : {};
  const message =
    stringValue(record.message) ||
    (stringValue(error.message) ? "暂无待审批内容。" : "") ||
    (degraded ? "暂无待审批内容。" : "");

  return {
    count: numberValue(record.count, items.length),
    cursor: typeof record.cursor === "string" ? record.cursor : null,
    degraded,
    items,
    limit: numberValue(record.limit, items.length || APPROVAL_LIST_DEFAULT_LIMIT),
    message,
    next_cursor:
      typeof record.next_cursor === "string" ? record.next_cursor : null,
    offset: numberValue(record.offset, 0),
    source: stringValue(record.source, degraded ? "degraded" : "live"),
    status: degraded ? "degraded" : "ok",
  };
}

function normalizeListLimit(limit: number | undefined) {
  if (typeof limit !== "number" || !Number.isFinite(limit)) {
    return APPROVAL_LIST_DEFAULT_LIMIT;
  }
  return Math.max(1, Math.min(APPROVAL_LIST_MAX_LIMIT, Math.floor(limit)));
}

function appendCursor(params: URLSearchParams, cursor: string | undefined) {
  if (typeof cursor === "string" && cursor.trim()) {
    params.set("cursor", cursor.trim());
  }
}

function normalizeDecision(value: unknown): ApprovalDecisionRecord | null {
  if (!isRecord(value)) {
    return null;
  }

  return {
    actor_id: typeof value.actor_id === "number" ? value.actor_id : null,
    decision_time: stringValue(value.decision_time),
    reason: stringValue(value.reason),
    status: normalizeStatus(value.status),
  };
}

export function normalizeApprovalDetail(value: unknown): ApprovalDetail {
  const record = isRecord(value) ? value : {};
  const approval = isRecord(record.approval) ? record.approval : {};
  const boundary = isRecord(record.permission_boundary)
    ? record.permission_boundary
    : {};

  return {
    approval: {
      approval_id: stringValue(approval.approval_id),
      category: normalizeCategory(approval.category),
      request_time: stringValue(approval.request_time),
      status: normalizeStatus(approval.status),
    },
    decisions: Array.isArray(record.decisions)
      ? record.decisions
          .map(normalizeDecision)
          .filter((item): item is ApprovalDecisionRecord => item !== null)
      : [],
    display: normalizeDisplay(record.display),
    permission_boundary: {
      allowed_actions: Array.isArray(boundary.allowed_actions)
        ? boundary.allowed_actions.filter(
            (item): item is string => typeof item === "string",
          )
        : [],
    },
  };
}

export async function listApprovals({
  category,
  limit,
  cursor,
  offset = 0,
  signal,
}: {
  category?: ApprovalCategory;
  cursor?: string;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}) {
  const params = new URLSearchParams({
    limit: String(normalizeListLimit(limit)),
    offset: String(offset),
  });
  if (category) {
    params.set("category", category);
  }
  appendCursor(params, cursor);
  return normalizeListResponse(
    await apiRequest<unknown>(`/approval/list?${params.toString()}`, {
      method: "GET",
      retryLimit: 0,
      signal,
      timeoutMs: APPROVAL_LIST_TIMEOUT_MS,
    }),
  );
}

export async function getApprovalDetail(approvalId: string) {
  return normalizeApprovalDetail(
    await apiRequest<unknown>(`/approval/${encodeURIComponent(approvalId)}`, {
      method: "GET",
    }),
  );
}

export async function approveApproval(approvalId: string) {
  return normalizeApprovalDetail(
    await apiRequest<unknown>(
      `/approval/${encodeURIComponent(approvalId)}/approve`,
      {
        body: {},
        method: "POST",
      },
    ),
  );
}

export async function rejectApproval(approvalId: string, reason: string) {
  return normalizeApprovalDetail(
    await apiRequest<unknown>(
      `/approval/${encodeURIComponent(approvalId)}/reject`,
      {
        body: { reason },
        method: "POST",
      },
    ),
  );
}
