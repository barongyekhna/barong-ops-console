import type { FrontendPermissions } from "./permissions";

export const HIGH_RISK_CONFIRMATION_TEXT =
  "CONFIRM_HIGH_RISK_PERMISSION";
export const OWNER_FULL_ACCESS_NOTICE =
  "owner拥有全部工作台权限，不需要单独授权。";
export const ROLE_DEFAULT_PERMISSIONS_NOTICE =
  "管理该用户的显式权限分配。";
export const EMPTY_ASSIGNMENTS_NOTICE = "暂无显式权限分配。";

const GLOBAL_PERMISSION_WILDCARD = "*";
const REMOVED_PERMISSION_MODULES = new Set([
  String.fromCharCode(97, 114, 116, 105, 102, 97, 99, 116, 115),
]);
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
const FEATURE_PERMISSION_MODULES = new Set([
  "agents",
  "approvals",
  "reviews",
]);
const FEATURE_PERMISSION_PREFIXES = new Set([
  "agents",
  "approvals",
  "reviews",
]);
const MODULE_DISPLAY_LABELS: Record<string, string> = {
  // 业务模块统一写成「X系列 名称」，分组标题再把 module_key 挂在括号里。
  "b2b.wholesale": "B2B系列 批发业务",
  "content.desk": "GEO/SEO系列 内容台",
  "cs.customer_service": "CS系列 客服中心",
  "f.enrichment": "F系列 类目富化",
  "geo.content": "GEO系列 内容引擎",
  "h.site_health": "H系列 站点健康",
  "i.image_system": "I系列 图片系统",
  "k.product_knowledge": "K系列 产品知识库",
  "mfg.inventory": "M系列 制造库存",
  "p.upload": "P系列 自动化上传",
  "seo.content": "SEO系列 内容引擎",
  "sm.social": "SM系列 社媒运营",
  "w.site_ops": "W系列 物流网络中枢",
  adapters: "适配器",
  agents: "智能体",
  approvals: "审批",
  execution: "执行",
  modules: "模块",
  operation_logs: "操作日志",
  permissions: "权限配置",
  production: "生产发布",
  registry: "注册表",
  reviews: "评审",
  roles: "角色",
  settings: "系统设置",
  system: "系统",
  users: "用户",
};
const ACTION_DISPLAY_LABELS: Record<string, string> = {
  admin: "管理",
  approve: "审批",
  create: "创建",
  delete: "删除",
  execute: "执行",
  manage: "管理",
  read: "查看",
  release: "发布",
  write: "编辑",
};
// 卡片名：中文（permission_key）。这里只放中文，括号里的英文键由
// getPermissionDisplayName 统一追加，保证每张卡片格式一致。
const PERMISSION_DISPLAY_LABELS: Record<string, string> = {
  "agents.manage": "管理智能体",
  "agents.read": "查看智能体",
  "approvals.approve": "审批",
  "approvals.read": "查看审批",
  "b2b.wholesale.export": "导出批发报价单",
  "b2b.wholesale.manage": "管理批发目录",
  "b2b.wholesale.read": "查看批发目录",
  "content.desk.execute": "在内容台操作",
  "content.desk.manage": "管理内容台",
  "content.desk.read": "查看内容台",
  "cs.customer_service.read": "查看客服消息",
  "cs.customer_service.update": "处理客服消息",
  "execution.manage": "管理执行",
  "f.enrichment.execute": "执行类目富化",
  "f.enrichment.read": "查看类目富化",
  "f.enrichment.review": "评审富化候选",
  "geo.content.execute": "生成 GEO 内容",
  "geo.content.manage": "管理 GEO 内容",
  "geo.content.read": "查看 GEO 内容",
  "h.site_health.manage": "管理站点健康",
  "h.site_health.read": "查看站点健康",
  "i.image_system.execute": "生成与编辑图片",
  "i.image_system.manage": "管理媒体库",
  "i.image_system.read": "查看图片系统",
  "k.product_knowledge.archive": "归档产品知识",
  "k.product_knowledge.attributes.manage": "管理产品属性",
  "k.product_knowledge.create": "新建产品知识",
  "k.product_knowledge.keywords.manage": "管理产品关键词",
  "k.product_knowledge.read": "查看产品知识",
  "k.product_knowledge.risk_terms.manage": "管理产品风险词",
  "k.product_knowledge.update": "更新产品知识",
  "mfg.inventory.manage": "管理制造库存",
  "mfg.inventory.read": "查看制造库存",
  "modules.manage": "管理模块",
  "modules.read": "查看模块",
  "operation_logs.read": "查看操作日志",
  "p.upload.execute": "派发上传任务",
  "p.upload.read": "查看上传流水线",
  "permissions.manage": "管理权限配置",
  "permissions.read": "查看权限配置",
  "production.release": "生产发布",
  "products.read": "查看产品",
  "registry.manage": "管理注册表",
  "registry.read": "查看注册表",
  "reviews.approve": "评审审批",
  "reviews.read": "查看评审",
  "roles.read": "查看角色",
  "seo.content.execute": "生成 SEO 内容",
  "seo.content.manage": "管理 SEO 内容",
  "seo.content.read": "查看 SEO 内容",
  "settings.manage": "管理系统设置",
  "settings.read": "查看系统设置",
  "sm.social.execute": "执行社媒运营",
  "sm.social.manage": "管理社媒运营",
  "sm.social.read": "查看社媒运营",
  "system.admin": "系统管理",
  "users.manage": "管理用户",
  "users.read": "查看用户",
  "w.site_ops.manage": "管理站点运营",
  "w.site_ops.read": "查看站点运营",
};

function normalizeRole(role: string | null | undefined) {
  if (!role) {
    return "";
  }
  const normalized = role
    .trim()
    .toLowerCase()
    .replace(/-/g, "_")
    .replace(/\s+/g, "_");
  if (
    normalized === "superadmin" ||
    normalized === "super_admin" ||
    normalized === "org_admin" ||
    normalized === "organization_admin"
  ) {
    return "super_admin";
  }
  return normalized;
}

function isOwnerRole(role: string | null | undefined) {
  return normalizeRole(role) === "owner";
}

function isSuperAdminRole(role: string | null | undefined) {
  return normalizeRole(role) === "super_admin";
}

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

export type PermissionUiCategory = "control_plane" | "feature";

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

function normalizedPermissionModule(permissionKey: string) {
  return permissionKey.split(".")[0]?.trim().toLowerCase() ?? "";
}

function isRemovedPermission(
  permission:
    | Pick<PermissionRegistryItem, "module_key" | "permission_key">
    | Pick<PermissionAssignment, "permission_key">
    | string,
) {
  const permissionKey =
    typeof permission === "string"
      ? permission
      : permission.permission_key;
  const moduleKey =
    typeof permission === "object" && "module_key" in permission
      ? permission.module_key
      : normalizedPermissionModule(permissionKey);
  return REMOVED_PERMISSION_MODULES.has(moduleKey.trim().toLowerCase());
}

function normalizedPermissionAction(permissionKey: string) {
  const parts = permissionKey.split(".");
  return parts[parts.length - 1]?.trim().toLowerCase() ?? "";
}

export function permissionModuleLabel(moduleKey: string) {
  const normalized = moduleKey.trim().toLowerCase();
  return MODULE_DISPLAY_LABELS[normalized] ?? normalized.replace(/_/g, " ");
}

/** 分组标题：「X系列 名称（module_key）」，英文键名留在括号里便于对照后端。 */
export function permissionModuleGroupTitle(moduleKey: string) {
  const normalized = moduleKey.trim().toLowerCase();
  const label = permissionModuleLabel(normalized);
  return label === normalized ? normalized : `${label}（${normalized}）`;
}

function permissionActionLabel(action: string) {
  const normalized = action.trim().toLowerCase();
  return ACTION_DISPLAY_LABELS[normalized] ?? normalized.replace(/_/g, " ");
}

export function getPermissionUiCategory(
  permission:
    | Pick<PermissionRegistryItem, "category" | "module_key" | "permission_key">
    | Pick<PermissionAssignment, "permission_key">
    | string
    | null
    | undefined,
): PermissionUiCategory {
  const category =
    typeof permission === "object" && permission !== null
      ? "category" in permission
        ? permission.category.trim().toLowerCase()
        : ""
      : "";
  if (category === "feature" || category === "control_plane") {
    return category;
  }

  const permissionKey =
    typeof permission === "string"
      ? permission
      : permission?.permission_key ?? "";
  const moduleKey =
    typeof permission === "object" && permission !== null && "module_key" in permission
      ? permission.module_key
      : normalizedPermissionModule(permissionKey);
  const normalizedModule = moduleKey.trim().toLowerCase();
  const keyPrefix = normalizedPermissionModule(permissionKey);

  return FEATURE_PERMISSION_MODULES.has(normalizedModule) ||
    FEATURE_PERMISSION_PREFIXES.has(keyPrefix)
    ? "feature"
    : "control_plane";
}

export function getPermissionDisplayName(
  permission:
    | Pick<
        PermissionRegistryItem,
        "action" | "label" | "module_key" | "permission_key"
      >
    | Pick<PermissionAssignment, "permission_key" | "permission_name">
    | string
    | null
    | undefined,
) {
  const permissionKey = (
    typeof permission === "string"
      ? permission
      : permission?.permission_key ?? ""
  ).trim();
  const withKey = (name: string) =>
    permissionKey && name !== permissionKey ? `${name}（${permissionKey}）` : name;
  const mapped = PERMISSION_DISPLAY_LABELS[permissionKey];
  if (mapped) {
    return withKey(mapped);
  }

  if (typeof permission === "object" && permission !== null) {
    if ("permission_name" in permission && permission.permission_name) {
      return withKey(permission.permission_name);
    }
    if ("label" in permission && permission.label) {
      return withKey(permission.label);
    }
  }

  const moduleKey =
    typeof permission === "object" && permission !== null && "module_key" in permission
      ? permission.module_key
      : normalizedPermissionModule(permissionKey);
  const action =
    typeof permission === "object" && permission !== null && "action" in permission
      ? permission.action
      : normalizedPermissionAction(permissionKey);
  const moduleLabel = permissionModuleLabel(moduleKey);
  const actionLabel = permissionActionLabel(action);

  return withKey(`${actionLabel}${moduleLabel}`);
}

export function getPermissionCategoryLabel(category: PermissionUiCategory) {
  return category === "control_plane"
    ? "系统权限"
    : "功能权限";
}

export function canViewPermissionCenter(role: string | null | undefined) {
  return isOwnerRole(role) || isSuperAdminRole(role);
}

export function canManagePermissionAssignments(role: string | null | undefined) {
  return isOwnerRole(role);
}

export function filterPermissionRegistryForRole(
  registry: PermissionRegistryItem[],
  role: string | null | undefined,
) {
  const activeRegistry = registry.filter(
    (permission) => !isRemovedPermission(permission),
  );
  const normalized = normalizeRole(role);
  if (normalized === "owner") {
    return activeRegistry;
  }
  if (normalized === "super_admin") {
    return activeRegistry.filter(
      (permission) => getPermissionUiCategory(permission) === "feature",
    );
  }
  return [];
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
      !isWildcardPermissionKey(permission.permission_key) &&
      !isRemovedPermission(permission),
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
    getPermissionDisplayName(permission),
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
  role?: string | null,
) {
  return (
    permissions?.is_owner_full_access === true ||
    isSuperAdminRole(role)
  );
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
    return { ok: false, message: "请先选择要授予的权限。" };
  }
  if (isWildcardPermissionKey(permissionKey)) {
    return {
      ok: false,
      message: "这里不能授予通配权限。",
    };
  }

  const highRisk = detectHighRiskPermission(input.permission);
  const reason = normalizeReason(input.reason);
  if (highRisk && !reason) {
    return {
      ok: false,
      message: "高风险权限必须填写原因。",
    };
  }
  if (
    highRisk &&
    (!input.confirm_high_risk ||
      input.confirmation_text.trim() !== HIGH_RISK_CONFIRMATION_TEXT)
  ) {
    return {
      ok: false,
      message: "高风险权限必须填写确认文本。",
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
      message: "更新高风险权限必须填写原因。",
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
      message: "变更高风险权限必须填写确认文本。",
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
      message: "撤销高风险权限必须填写原因。",
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
  fallback = "操作未完成，请检查权限、重复授权或高风险确认。",
) {
  if (!isApiErrorLike(error)) {
    return fallback;
  }

  const detail = safeApiDetail(error.message || "");
  const lowerDetail = detail.toLowerCase();

  if (error.status === 401) {
    return "请重新登录后再管理权限。";
  }
  if (error.status === 403) {
    return "只有owner可以管理权限分配。";
  }
  if (error.status === 404) {
    return "未找到用户或权限分配，请刷新后重试。";
  }
  if (error.status === 409) {
    return "该权限分配已存在或与当前访问范围冲突。";
  }
  if (
    error.status === 400 &&
    (lowerDetail.includes("high-risk") ||
      lowerDetail.includes("confirmation") ||
      lowerDetail.includes("reason"))
  ) {
    return "高风险权限必须填写原因和确认文本。";
  }
  if (error.status === 400) {
    return detail || fallback;
  }
  if (error.status === 422) {
    return "请求不完整或格式不正确，请检查权限、范围、过期时间和原因。";
  }
  if (error.status === 503) {
    return "后端服务暂时不可用。";
  }
  if (error.status >= 500) {
    return "后端返回内部错误，请稍后重试。";
  }

  return detail || fallback;
}

// ---------------------------------------------------------------------------
// 按员工授权的权限树：纯逻辑，供 permissions-product-view 与测试共用。
// 没有通配权限键（后端拒绝 "*"），所以「模块全选」= 逐条落，取消其中
// 一条只撤销那一条。
// ---------------------------------------------------------------------------

export const PERMISSION_TREE_SCOPE_TYPE = "global";
export const PERMISSION_TREE_SCOPE_KEY = "*";

export type PermissionTreeModule = {
  moduleKey: string;
  title: string;
  /** 业务权限可勾选；admin/system 控制面只读展示。 */
  grantable: boolean;
  permissions: PermissionRegistryItem[];
};

export type PermissionCheckState = "all" | "some" | "none";

export type PermissionAssignmentDiff = {
  grants: PermissionRegistryItem[];
  revokes: { permission: PermissionRegistryItem; assignment: PermissionAssignment }[];
  highRiskGrants: PermissionRegistryItem[];
  highRiskRevokes: PermissionRegistryItem[];
};

/** 卡片/树行显示用：中文名与英文键分开，避免一行塞爆。 */
export function splitPermissionDisplayName(
  permission: Parameters<typeof getPermissionDisplayName>[0],
) {
  const key = (
    typeof permission === "string"
      ? permission
      : permission?.permission_key ?? ""
  ).trim();
  const full = getPermissionDisplayName(permission);
  const suffix = key ? `（${key}）` : "";
  const label =
    suffix && full.endsWith(suffix) ? full.slice(0, -suffix.length) : full;
  return { label: label || key, key };
}

/**
 * 按 module_key 分组成树。业务组按权限数降序、标题升序排在前面，
 * 控制面组（owner 才看得到）固定排最后且 grantable=false。
 */
export function buildPermissionTree(
  registry: PermissionRegistryItem[],
  role: string | null | undefined,
): PermissionTreeModule[] {
  const visible = filterPermissionRegistryForRole(
    filterGrantablePermissionRegistry(registry),
    role,
  );
  const buckets = new Map<string, PermissionRegistryItem[]>();
  for (const permission of visible) {
    const grantable = getPermissionUiCategory(permission) === "feature";
    const moduleKey = grantable
      ? permission.module_key?.trim().toLowerCase() || "other"
      : "__control_plane__";
    const bucket = buckets.get(moduleKey);
    if (bucket) {
      bucket.push(permission);
    } else {
      buckets.set(moduleKey, [permission]);
    }
  }

  const modules: PermissionTreeModule[] = [];
  let controlPlane: PermissionTreeModule | null = null;
  for (const [moduleKey, permissions] of buckets.entries()) {
    const sorted = [...permissions].sort((a, b) =>
      a.permission_key.localeCompare(b.permission_key),
    );
    if (moduleKey === "__control_plane__") {
      controlPlane = {
        moduleKey,
        title: "系统权限（控制面，只读）",
        grantable: false,
        permissions: sorted,
      };
      continue;
    }
    modules.push({
      moduleKey,
      title: permissionModuleGroupTitle(moduleKey),
      grantable: true,
      permissions: sorted,
    });
  }
  modules.sort(
    (a, b) =>
      b.permissions.length - a.permissions.length ||
      a.title.localeCompare(b.title),
  );
  if (controlPlane) {
    modules.push(controlPlane);
  }
  return modules;
}

function assignmentIsLive(assignment: PermissionAssignment) {
  return assignment.is_enabled !== false && assignment.enabled !== false;
}

/**
 * 当前生效授权：key → assignment。优先 global/* 那行；同一 key 只有
 * 非全局范围的行也算「已有」（撤销时撤那一行）。已 disabled 的旧行不算。
 */
export function assignedPermissionMap(
  assignments: PermissionAssignment[],
): Map<string, PermissionAssignment> {
  const result = new Map<string, PermissionAssignment>();
  for (const assignment of assignments) {
    if (!assignmentIsLive(assignment)) {
      continue;
    }
    const key = assignment.permission_key.trim();
    const existing = result.get(key);
    const isGlobal =
      assignment.scope_type === PERMISSION_TREE_SCOPE_TYPE &&
      assignment.scope_key === PERMISSION_TREE_SCOPE_KEY;
    if (!existing || isGlobal) {
      result.set(key, assignment);
    }
  }
  return result;
}

export function moduleCheckState(
  keys: string[],
  draft: ReadonlySet<string>,
): PermissionCheckState {
  if (keys.length === 0) {
    return "none";
  }
  let checked = 0;
  for (const key of keys) {
    if (draft.has(key)) {
      checked += 1;
    }
  }
  if (checked === 0) {
    return "none";
  }
  return checked === keys.length ? "all" : "some";
}

/** 草稿 vs 当前生效 → 需要 POST 的 grants 与需要 DELETE 的 revokes。 */
export function computeAssignmentDiff(
  current: ReadonlyMap<string, PermissionAssignment>,
  draft: ReadonlySet<string>,
  tree: PermissionTreeModule[],
): PermissionAssignmentDiff {
  const grants: PermissionRegistryItem[] = [];
  const revokes: PermissionAssignmentDiff["revokes"] = [];
  for (const moduleNode of tree) {
    if (!moduleNode.grantable) {
      continue;
    }
    for (const permission of moduleNode.permissions) {
      const key = permission.permission_key;
      const assignment = current.get(key);
      const wanted = draft.has(key);
      if (wanted && !assignment) {
        grants.push(permission);
      } else if (!wanted && assignment) {
        revokes.push({ permission, assignment });
      }
    }
  }
  return {
    grants,
    revokes,
    highRiskGrants: grants.filter((permission) =>
      detectHighRiskPermission(permission),
    ),
    highRiskRevokes: revokes
      .map((entry) => entry.permission)
      .filter((permission) => detectHighRiskPermission(permission)),
  };
}
