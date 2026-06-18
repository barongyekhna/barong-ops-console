import type { FrontendPermissions } from "./permissions";

export const HIGH_RISK_CONFIRMATION_TEXT =
  "CONFIRM_HIGH_RISK_PERMISSION";
export const OWNER_FULL_ACCESS_NOTICE =
  "Owner has full workspace access and does not need separate assignments.";
export const ROLE_DEFAULT_PERMISSIONS_NOTICE =
  "Manage explicit permission assignments for this user.";
export const EMPTY_ASSIGNMENTS_NOTICE = "No explicit assignments yet.";

const GLOBAL_PERMISSION_WILDCARD = "*";
const HIGH_RISK_PERMISSION_KEYS = new Set([
  "users.manage",
  "permissions.manage",
  "system.settings.manage",
  "settings.manage",
  "system.admin",
  "secrets.manage",
  "release.manage",
  "production.release",
  "production.manage",
  "billing.manage",
]);
const HIGH_RISK_KEY_MARKERS = [
  "admin",
  "system",
  "release",
  "secret",
  "secrets",
  "production",
  "billing",
];
const HIGH_RISK_ADMIN_ACTIONS = new Set([
  "manage",
  "admin",
  "release",
]);
const HIGH_RISK_MODULES = new Set([
  "admin",
  "system",
  "release",
  "secrets",
  "production",
  "billing",
]);

export type PermissionAssignment = {
  id: string;
  user_id: number;
  permission_key: string;
  permission_name: string | null;
  description: string | null;
  scope_type: string;
  scope_id: string;
  scope_key: string;
  enabled: boolean;
  is_enabled: boolean;
  expires_at: string | null;
  granted_by_user_id: number | null;
  created_at: string | null;
  updated_at: string | null;
  reason: string | null;
  risk_level: string | null;
  high_risk: boolean;
  effective: boolean;
};

export type PermissionAssignmentListResponse = {
  user_id: number;
  username: string;
  role: string;
  is_owner_full_access: boolean;
  owner_full_access_note: string | null;
  assignments: PermissionAssignment[];
};

export type PermissionAssignmentCreateInput = {
  permission_key: string;
  scope_type?: string;
  scope_id?: string | null;
  scope_key?: string | null;
  reason?: string | null;
  expires_at?: string | null;
  enabled?: boolean;
  confirm_high_risk?: boolean;
  confirmation_text?: string | null;
};

export type PermissionAssignmentUpdateInput = {
  enabled?: boolean;
  is_enabled?: boolean;
  scope_type?: string;
  scope_id?: string | null;
  scope_key?: string | null;
  reason?: string | null;
  expires_at?: string | null;
  confirm_high_risk?: boolean;
  confirmation_text?: string | null;
};

export type PermissionAssignmentRevokeInput = {
  reason?: string | null;
};

export type PermissionAssignmentActionResponse = {
  assignment: PermissionAssignment | null;
  operation_id: string | null;
};

export type PermissionRegistryItem = {
  id: string;
  permission_key: string;
  module_key: string;
  category: string;
  action: string;
  label: string;
  description: string | null;
  risk_level: string;
  menu_policy: string;
  is_system: boolean;
  is_enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type PermissionGrantFormInput = {
  permission_key: string;
  scope_type: string;
  scope_id: string;
  expires_at: string;
  reason: string;
  enabled: boolean;
  confirm_high_risk: boolean;
  confirmation_text: string;
  permission: PermissionRiskSource | null;
};

export type PermissionUpdateFormInput = {
  enabled: boolean;
  scope_type: string;
  scope_id: string;
  expires_at: string;
  reason: string;
  confirm_high_risk: boolean;
  confirmation_text: string;
};

export type ValidationResult<T> =
  | { ok: true; payload: T }
  | { ok: false; message: string };

export type PermissionRiskSource = {
  permission_key?: string | null;
  module_key?: string | null;
  category?: string | null;
  action?: string | null;
  risk_level?: string | null;
  high_risk?: boolean | null;
};

type ApiErrorLike = {
  status: number;
  message?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isApiErrorLike(value: unknown): value is ApiErrorLike {
  return (
    isRecord(value) &&
    typeof value.status === "number" &&
    Number.isFinite(value.status)
  );
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function numberValue(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : fallback;
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function normalizeReason(value: string | null | undefined) {
  const trimmed = value?.trim() ?? "";
  return trimmed ? trimmed : null;
}

function normalizeScopeId(
  scopeType: string,
  scopeId: string | null | undefined,
) {
  if (scopeType === "global") {
    return GLOBAL_PERMISSION_WILDCARD;
  }

  const trimmed = scopeId?.trim() ?? "";
  return trimmed || GLOBAL_PERMISSION_WILDCARD;
}

function normalizeDateTime(value: string | null | undefined) {
  const trimmed = value?.trim() ?? "";
  return trimmed ? trimmed : null;
}

export function getUserPermissionAssignmentsPath(userId: number | string) {
  return `/permissions/users/${encodeURIComponent(String(userId))}/assignments`;
}

export function getUserPermissionAssignmentPath(
  userId: number | string,
  assignmentId: number | string,
) {
  return `${getUserPermissionAssignmentsPath(userId)}/${encodeURIComponent(
    String(assignmentId),
  )}`;
}

export function getPermissionRegistryPath(limit = 100, offset = 0) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return `/permissions/registry?${params.toString()}`;
}

export function normalizePermissionAssignment(
  value: unknown,
  fallbackUserId = 0,
): PermissionAssignment {
  const record = isRecord(value) ? value : {};
  const enabled = booleanValue(
    record.enabled,
    booleanValue(record.is_enabled, false),
  );
  const scopeId =
    optionalString(record.scope_id) ?? optionalString(record.scope_key) ?? "";

  return {
    created_at: optionalString(record.created_at),
    description: optionalString(record.description),
    effective: booleanValue(record.effective, false),
    enabled,
    expires_at: optionalString(record.expires_at),
    granted_by_user_id:
      typeof record.granted_by_user_id === "number"
        ? record.granted_by_user_id
        : null,
    high_risk: booleanValue(record.high_risk, false),
    id: stringValue(record.id),
    is_enabled: booleanValue(record.is_enabled, enabled),
    permission_key: stringValue(record.permission_key),
    permission_name: optionalString(record.permission_name),
    reason: optionalString(record.reason),
    risk_level: optionalString(record.risk_level),
    scope_id: scopeId,
    scope_key: optionalString(record.scope_key) ?? scopeId,
    scope_type: stringValue(record.scope_type, "global"),
    updated_at: optionalString(record.updated_at),
    user_id: numberValue(record.user_id, fallbackUserId),
  };
}

export function normalizePermissionAssignmentListResponse(
  value: unknown,
  fallbackUserId = 0,
): PermissionAssignmentListResponse {
  const record = isRecord(value) ? value : {};
  const userId = numberValue(record.user_id, fallbackUserId);

  return {
    assignments: Array.isArray(record.assignments)
      ? record.assignments.map((entry) =>
          normalizePermissionAssignment(entry, userId),
        )
      : [],
    is_owner_full_access: booleanValue(
      record.is_owner_full_access,
      false,
    ),
    owner_full_access_note: optionalString(record.owner_full_access_note),
    role: stringValue(record.role),
    user_id: userId,
    username: stringValue(record.username),
  };
}

export function normalizePermissionRegistryItem(
  value: unknown,
): PermissionRegistryItem {
  const record = isRecord(value) ? value : {};

  return {
    action: stringValue(record.action),
    category: stringValue(record.category),
    created_at: optionalString(record.created_at),
    description: optionalString(record.description),
    id: stringValue(record.id),
    is_enabled: booleanValue(record.is_enabled, true),
    is_system: booleanValue(record.is_system, false),
    label: stringValue(record.label, stringValue(record.permission_key)),
    menu_policy: stringValue(record.menu_policy),
    module_key: stringValue(record.module_key),
    permission_key: stringValue(record.permission_key),
    risk_level: stringValue(record.risk_level, "low"),
    updated_at: optionalString(record.updated_at),
  };
}

export function normalizePermissionRegistryResponse(
  value: unknown,
): PermissionRegistryItem[] {
  const items = Array.isArray(value)
    ? value
    : isRecord(value) && Array.isArray(value.items)
      ? value.items
      : [];

  return items.map(normalizePermissionRegistryItem);
}

export function isWildcardPermissionKey(permissionKey: string | null | undefined) {
  return permissionKey?.trim() === GLOBAL_PERMISSION_WILDCARD;
}

export function detectHighRiskPermission(permission: PermissionRiskSource | null) {
  if (!permission) {
    return false;
  }

  if (permission.high_risk === true) {
    return true;
  }

  const riskLevel = permission.risk_level?.toLowerCase() ?? "";
  if (riskLevel === "high" || riskLevel === "critical") {
    return true;
  }

  const permissionKey = permission.permission_key?.toLowerCase() ?? "";
  if (HIGH_RISK_PERMISSION_KEYS.has(permissionKey)) {
    return true;
  }

  const keyParts = new Set(permissionKey.split(".").filter(Boolean));
  if (HIGH_RISK_KEY_MARKERS.some((marker) => keyParts.has(marker))) {
    return true;
  }

  if (HIGH_RISK_KEY_MARKERS.some((marker) => permissionKey.includes(marker))) {
    return true;
  }

  const category = permission.category?.toLowerCase() ?? "";
  const action = permission.action?.toLowerCase() ?? "";
  if (
    (category === "admin" || category === "system") &&
    HIGH_RISK_ADMIN_ACTIONS.has(action)
  ) {
    return true;
  }

  const moduleKey = permission.module_key?.toLowerCase() ?? "";
  return HIGH_RISK_MODULES.has(moduleKey);
}

export function filterGrantablePermissionRegistry(
  registry: PermissionRegistryItem[],
) {
  return registry.filter(
    (permission) =>
      permission.is_enabled !== false &&
      !isWildcardPermissionKey(permission.permission_key),
  );
}

export function matchesPermissionRegistrySearch(
  permission: PermissionRegistryItem,
  query: string,
) {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return true;
  }

  return [
    permission.permission_key,
    permission.label,
    permission.description ?? "",
    permission.module_key,
    permission.category,
    permission.action,
    permission.risk_level,
  ].some((value) => value.toLowerCase().includes(normalizedQuery));
}

export function canShowPermissionManagementEntry(
  permissions: FrontendPermissions | null | undefined,
) {
  return permissions?.is_owner_full_access === true;
}

export function getPermissionTargetMode(
  target: { role?: string | null } | null | undefined,
  response?: PermissionAssignmentListResponse | null,
) {
  if (target?.role === "owner" || response?.is_owner_full_access === true) {
    return "owner_full_access";
  }

  return "assignments";
}

export function getAssignmentEmptyStateText(
  response: PermissionAssignmentListResponse | null | undefined,
) {
  return response && response.assignments.length === 0
    ? EMPTY_ASSIGNMENTS_NOTICE
    : "";
}

export function validatePermissionGrantInput(
  input: PermissionGrantFormInput,
): ValidationResult<PermissionAssignmentCreateInput> {
  const permissionKey = input.permission_key.trim();
  if (!permissionKey) {
    return { ok: false, message: "Choose a permission before granting access." };
  }
  if (isWildcardPermissionKey(permissionKey)) {
    return {
      ok: false,
      message: "Wildcard grants are not available here.",
    };
  }

  const highRisk = detectHighRiskPermission(input.permission);
  const reason = normalizeReason(input.reason);
  if (highRisk && !reason) {
    return {
      ok: false,
      message: "High-risk permissions require a reason.",
    };
  }
  if (
    highRisk &&
    (!input.confirm_high_risk ||
      input.confirmation_text.trim() !== HIGH_RISK_CONFIRMATION_TEXT)
  ) {
    return {
      ok: false,
      message:
        "High-risk permissions require confirmation text.",
    };
  }

  const scopeType = input.scope_type || "global";

  return {
    ok: true,
    payload: {
      confirm_high_risk: highRisk ? input.confirm_high_risk : false,
      confirmation_text: highRisk
        ? input.confirmation_text.trim()
        : null,
      enabled: input.enabled,
      expires_at: normalizeDateTime(input.expires_at),
      permission_key: permissionKey,
      reason,
      scope_id: normalizeScopeId(scopeType, input.scope_id),
      scope_type: scopeType,
    },
  };
}

export function requiresHighRiskUpdateConfirmation(
  assignment: PermissionAssignment,
  input: PermissionUpdateFormInput,
) {
  if (!detectHighRiskPermission(assignment)) {
    return false;
  }

  const reEnabling = !assignment.enabled && input.enabled;
  const nextScopeType = input.scope_type || assignment.scope_type;
  const nextScopeId = normalizeScopeId(nextScopeType, input.scope_id);
  const currentScopeId = assignment.scope_id || assignment.scope_key;
  const scopeChanged =
    nextScopeType !== assignment.scope_type || nextScopeId !== currentScopeId;

  return reEnabling || scopeChanged;
}

export function validatePermissionUpdateInput(
  assignment: PermissionAssignment,
  input: PermissionUpdateFormInput,
): ValidationResult<PermissionAssignmentUpdateInput> {
  if (!assignment.id) {
    return {
      ok: false,
      message: "Assignment 缺少 ID，无法更新。",
    };
  }

  const highRisk = detectHighRiskPermission(assignment);
  const reason = normalizeReason(input.reason);
  if (highRisk && !reason) {
    return {
      ok: false,
      message: "High-risk permission updates require a reason.",
    };
  }

  const needsConfirmation = requiresHighRiskUpdateConfirmation(
    assignment,
    input,
  );
  if (
    needsConfirmation &&
    (!input.confirm_high_risk ||
      input.confirmation_text.trim() !== HIGH_RISK_CONFIRMATION_TEXT)
  ) {
    return {
      ok: false,
      message:
        "High-risk permission changes require confirmation text.",
    };
  }

  const scopeType = input.scope_type || assignment.scope_type;

  return {
    ok: true,
    payload: {
      confirm_high_risk: needsConfirmation
        ? input.confirm_high_risk
        : false,
      confirmation_text: needsConfirmation
        ? input.confirmation_text.trim()
        : null,
      enabled: input.enabled,
      expires_at: normalizeDateTime(input.expires_at),
      reason,
      scope_id: normalizeScopeId(scopeType, input.scope_id),
      scope_type: scopeType,
    },
  };
}

export function validatePermissionRevokeInput(
  assignment: PermissionAssignment,
  reasonInput: string,
): ValidationResult<PermissionAssignmentRevokeInput> {
  if (!assignment.id) {
    return {
      ok: false,
      message: "Assignment 缺少 ID，无法撤销。",
    };
  }

  const reason = normalizeReason(reasonInput);
  if (detectHighRiskPermission(assignment) && !reason) {
    return {
      ok: false,
      message: "Revoking a high-risk permission requires a reason.",
    };
  }

  return {
    ok: true,
    payload: {
      reason,
    },
  };
}

export function shouldRefreshAssignmentsAfterMutation(
  action: "grant" | "update" | "revoke",
) {
  return action === "grant" || action === "update" || action === "revoke";
}

export function createGrantRequestBody(
  payload: PermissionAssignmentCreateInput,
) {
  const { enabled: _enabled, ...requestPayload } = payload;
  return requestPayload;
}

export function normalizeActionResponse(
  value: unknown,
): PermissionAssignmentActionResponse {
  const record = isRecord(value) ? value : {};

  return {
    assignment: record.assignment
      ? normalizePermissionAssignment(record.assignment)
      : null,
    operation_id: optionalString(record.operation_id),
  };
}

function safeApiDetail(message: string) {
  return message
    .replace(/Bearer\s+[A-Za-z0-9._-]+/gi, "Bearer [redacted]")
    .replace(
      /\b(authorization|password|token|secret)\b\s*[:=]\s*[^,\s]+/gi,
      "$1=[redacted]",
    );
}

export function formatPermissionAssignmentsApiError(
  error: unknown,
  fallback = "The action could not be completed. Check access, duplicate assignments, or high-risk confirmation.",
) {
  if (!isApiErrorLike(error)) {
    return fallback;
  }

  const detail = safeApiDetail(error.message || "");
  const lowerDetail = detail.toLowerCase();

  if (error.status === 401) {
    return "Sign in again before managing permissions.";
  }
  if (error.status === 403) {
    return "Only an owner can manage permissions.";
  }
  if (error.status === 404) {
    return "The user or assignment was not found. Refresh and try again.";
  }
  if (error.status === 409) {
    return "This assignment already exists or conflicts with current access.";
  }
  if (
    error.status === 400 &&
    (lowerDetail.includes("high-risk") ||
      lowerDetail.includes("confirmation") ||
      lowerDetail.includes("reason"))
  ) {
    return "High-risk permissions require a reason and confirmation text.";
  }
  if (error.status === 400) {
    return detail || fallback;
  }
  if (error.status === 422) {
    return "The request is incomplete or invalid. Check permission, scope, expires_at, and reason.";
  }
  if (error.status === 503) {
    return "The backend API is unavailable.";
  }
  if (error.status >= 500) {
    return "The backend returned an internal error. Try again later.";
  }

  return detail || fallback;
}
