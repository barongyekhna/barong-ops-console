import type {
  FrontendPermissions,
  PermissionAwareModule,
} from "./permissions";
import type { LucideIcon } from "lucide-react";

export type ModuleCategory =
  | "core"
  | "admin"
  | "system"
  | "business"
  | "integration"
  | "experimental";

export type ModuleStatus =
  | "planned"
  | "adapter_pending"
  | "installed"
  | "enabled"
  | "active"
  | "disabled"
  | "unavailable"
  | "deprecated"
  | "sealed";

export type ModuleDeniedBehavior = "show_locked" | "hide_when_denied";

export type ModuleUnavailableBehavior =
  | "hide"
  | "show_unavailable"
  | "planned"
  | "adapter_pending"
  | "execution_not_connected"
  | "disabled";

export type ModuleAccessStateName =
  | "available"
  | "locked"
  | "hidden"
  | "unavailable"
  | "planned"
  | "adapter_pending";

export type ModuleNavigationMetadata = {
  group: string;
  label: string;
  icon: string;
  order: number;
  default_visible: boolean;
  owner_only: boolean;
};

export type ModulePermissionManifestEntry = {
  permission_key: string;
  module_key: string;
  category: ModuleCategory;
  action: string;
  label: string;
  description: string;
  risk_level: "low" | "medium" | "high" | "critical";
  menu_policy: ModuleDeniedBehavior;
  default_scope_type: string;
  allowed_scope_types: string[];
  high_risk_confirmation_required: boolean;
  operation_log_required: boolean;
};

export type ModuleManifest = {
  module_key: string;
  display_name: string;
  description: string;
  category: ModuleCategory;
  status: ModuleStatus;
  lifecycle: string;
  route_namespace: string;
  api_namespace: string;
  no_api: boolean;
  navigation: ModuleNavigationMetadata;
  required_permissions: string[];
  permission_manifest: ModulePermissionManifestEntry[];
  denied_behavior: ModuleDeniedBehavior;
  unavailable_behavior: ModuleUnavailableBehavior;
  external_dependencies: string[];
  execution_provider_required: boolean;
  module_adapter_required: boolean;
  sandbox_required: boolean;
  feature_flag_key: string | null;
  audit_log_actions: string[];
  allowed_scope_types: string[];
  staging_acceptance_required: boolean;
  production_release_required: boolean;
  docs_path: string;
};

export type ModuleRegistryResponse = {
  items: ModuleManifest[];
  count: number;
};

export type ModuleAccessState = {
  module_key: string;
  visible: boolean;
  locked: boolean;
  hidden: boolean;
  unavailable: boolean;
  executable: boolean;
  access_state: ModuleAccessStateName;
  denied_behavior: ModuleDeniedBehavior;
  reason: string;
  required_permissions: string[];
  missing_permissions: string[];
  status: ModuleStatus;
  category: ModuleCategory;
  route_namespace: string;
};

export type UserModulesResponse = {
  user_id: number;
  role: string;
  is_owner_full_access: boolean;
  items: ModuleAccessState[];
  count: number;
};

export type ModuleAwareNavigationRecord = PermissionAwareModule & {
  href: string;
  label: string;
  icon?: LucideIcon;
  module_key: string;
  route_namespace: string;
  category: ModuleCategory;
  denied_behavior: ModuleDeniedBehavior;
  status?: ModuleStatus;
  core_shell_exception?: boolean;
  embedded?: boolean;
};

export type ModuleNavigationState = {
  canAccess: boolean;
  canEnter: boolean;
  isVisible: boolean;
  isLocked: boolean;
  isHidden: boolean;
  isUnavailable: boolean;
  moduleAccessUnknown: boolean;
  accessState: ModuleAccessStateName | "unknown";
  status: ModuleStatus | "unknown";
  badge: "locked" | "planned" | "adapter_pending" | "unavailable" | null;
  reason: string;
  missingPermissions: string[];
};

export type ModuleRouteDecision = ModuleNavigationState & {
  isProtected: boolean;
  module_key: string | null;
  noticeType: "none" | "no_permission" | "module_unavailable";
};

const MODULE_CATEGORIES = new Set<ModuleCategory>([
  "core",
  "admin",
  "system",
  "business",
  "integration",
  "experimental",
]);
const MODULE_STATUSES = new Set<ModuleStatus>([
  "planned",
  "adapter_pending",
  "installed",
  "enabled",
  "active",
  "disabled",
  "unavailable",
  "deprecated",
  "sealed",
]);
const DENIED_BEHAVIORS = new Set<ModuleDeniedBehavior>([
  "show_locked",
  "hide_when_denied",
]);
const ACCESS_STATES = new Set<ModuleAccessStateName>([
  "available",
  "locked",
  "hidden",
  "unavailable",
  "planned",
  "adapter_pending",
]);
const UNAVAILABLE_BEHAVIORS = new Set<ModuleUnavailableBehavior>([
  "hide",
  "show_unavailable",
  "planned",
  "adapter_pending",
  "execution_not_connected",
  "disabled",
]);
const SAFE_EXTERNAL_DEPENDENCIES = new Set([
  "n8n",
  "woocommerce",
  "minio",
  "filebrowser",
  "ai_provider",
]);
const SENSITIVE_EXTERNAL_DEPENDENCY_MARKERS = [
  "secret",
  "token",
  "password",
  "credential",
  "authorization",
  "api_key",
  "env",
  "url",
  "http",
  "://",
  "=",
];
const NON_EXECUTABLE_STATUSES = new Set<ModuleStatus>([
  "planned",
  "adapter_pending",
  "disabled",
  "unavailable",
]);
const GLOBAL_PERMISSION_WILDCARD = "*";

function isOwnerFullAccess(
  permissions: FrontendPermissions | null | undefined,
) {
  return permissions?.is_owner_full_access === true;
}

function hasPermission(
  permissions: FrontendPermissions | null | undefined,
  permissionKey: string | null | undefined,
) {
  if (!permissions || !permissionKey) {
    return false;
  }
  if (isOwnerFullAccess(permissions)) {
    return true;
  }
  return (
    permissions.permission_keys.includes(GLOBAL_PERMISSION_WILDCARD) ||
    permissions.permission_keys.includes(permissionKey)
  );
}

function getPermissionAccessState(
  permissions: FrontendPermissions | null | undefined,
  module: PermissionAwareModule,
) {
  const canAccess = module.owner_only
    ? isOwnerFullAccess(permissions)
    : module.required_permission
      ? hasPermission(permissions, module.required_permission)
      : true;

  if (canAccess) {
    return {
      canAccess: true,
      isLocked: false,
      isVisible: true,
    };
  }

  if (module.denied_behavior === "show_locked") {
    return {
      canAccess: false,
      isLocked: true,
      isVisible: true,
    };
  }

  return {
    canAccess: false,
    isLocked: false,
    isVisible: false,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function numberValue(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : fallback;
}

function stringArray(value: unknown) {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === "string")
    : [];
}

function normalizeCategory(value: unknown): ModuleCategory {
  return typeof value === "string" && MODULE_CATEGORIES.has(value as ModuleCategory)
    ? (value as ModuleCategory)
    : "business";
}

function normalizeStatus(value: unknown): ModuleStatus {
  return typeof value === "string" && MODULE_STATUSES.has(value as ModuleStatus)
    ? (value as ModuleStatus)
    : "unavailable";
}

function normalizeDeniedBehavior(value: unknown): ModuleDeniedBehavior {
  return typeof value === "string" &&
    DENIED_BEHAVIORS.has(value as ModuleDeniedBehavior)
    ? (value as ModuleDeniedBehavior)
    : "hide_when_denied";
}

function normalizeUnavailableBehavior(value: unknown): ModuleUnavailableBehavior {
  return typeof value === "string" &&
    UNAVAILABLE_BEHAVIORS.has(value as ModuleUnavailableBehavior)
    ? (value as ModuleUnavailableBehavior)
    : "show_unavailable";
}

function normalizeAccessStateName(value: unknown): ModuleAccessStateName {
  return typeof value === "string" &&
    ACCESS_STATES.has(value as ModuleAccessStateName)
    ? (value as ModuleAccessStateName)
    : "unavailable";
}

function normalizeExternalDependencies(value: unknown) {
  return stringArray(value)
    .map((dependency) => dependency.trim().toLowerCase())
    .filter(
      (dependency) =>
        SAFE_EXTERNAL_DEPENDENCIES.has(dependency) &&
        !SENSITIVE_EXTERNAL_DEPENDENCY_MARKERS.some((marker) =>
          dependency.includes(marker),
        ),
    );
}

function normalizeNavigationMetadata(
  value: unknown,
): ModuleNavigationMetadata {
  const record = isRecord(value) ? value : {};
  return {
    default_visible: booleanValue(record.default_visible, true),
    group: stringValue(record.group),
    icon: stringValue(record.icon),
    label: stringValue(record.label),
    order: numberValue(record.order),
    owner_only: booleanValue(record.owner_only, false),
  };
}

function normalizePermissionManifestEntry(
  value: unknown,
): ModulePermissionManifestEntry | null {
  if (!isRecord(value)) {
    return null;
  }
  const permissionKey = stringValue(value.permission_key);
  const moduleKey = stringValue(value.module_key);
  if (!permissionKey || !moduleKey) {
    return null;
  }

  const riskLevel = stringValue(value.risk_level, "low");

  return {
    action: stringValue(value.action),
    allowed_scope_types: stringArray(value.allowed_scope_types),
    category: normalizeCategory(value.category),
    default_scope_type: stringValue(value.default_scope_type, "global"),
    description: stringValue(value.description),
    high_risk_confirmation_required: booleanValue(
      value.high_risk_confirmation_required,
      false,
    ),
    label: stringValue(value.label, permissionKey),
    menu_policy: normalizeDeniedBehavior(value.menu_policy),
    module_key: moduleKey,
    operation_log_required: booleanValue(
      value.operation_log_required,
      false,
    ),
    permission_key: permissionKey,
    risk_level:
      riskLevel === "medium" ||
      riskLevel === "high" ||
      riskLevel === "critical"
        ? riskLevel
        : "low",
  };
}

export function normalizeModuleManifest(value: unknown): ModuleManifest | null {
  if (!isRecord(value) || typeof value.module_key !== "string") {
    return null;
  }

  return {
    allowed_scope_types: stringArray(value.allowed_scope_types),
    api_namespace: stringValue(value.api_namespace, "no_api"),
    audit_log_actions: stringArray(value.audit_log_actions),
    category: normalizeCategory(value.category),
    denied_behavior: normalizeDeniedBehavior(value.denied_behavior),
    description: stringValue(value.description),
    display_name: stringValue(value.display_name, value.module_key),
    docs_path: stringValue(value.docs_path),
    execution_provider_required: booleanValue(
      value.execution_provider_required,
      false,
    ),
    external_dependencies: normalizeExternalDependencies(
      value.external_dependencies,
    ),
    feature_flag_key: optionalString(value.feature_flag_key),
    lifecycle: stringValue(value.lifecycle),
    module_adapter_required: booleanValue(
      value.module_adapter_required,
      false,
    ),
    module_key: value.module_key,
    navigation: normalizeNavigationMetadata(value.navigation),
    no_api: booleanValue(value.no_api, false),
    permission_manifest: Array.isArray(value.permission_manifest)
      ? value.permission_manifest
          .map(normalizePermissionManifestEntry)
          .filter(
            (
              entry,
            ): entry is ModulePermissionManifestEntry => entry !== null,
          )
      : [],
    production_release_required: booleanValue(
      value.production_release_required,
      false,
    ),
    required_permissions: stringArray(value.required_permissions),
    route_namespace: stringValue(value.route_namespace, "/"),
    sandbox_required: booleanValue(value.sandbox_required, false),
    staging_acceptance_required: booleanValue(
      value.staging_acceptance_required,
      false,
    ),
    status: normalizeStatus(value.status),
    unavailable_behavior: normalizeUnavailableBehavior(
      value.unavailable_behavior,
    ),
  };
}

export function normalizeModuleRegistryResponse(
  value: unknown,
): ModuleRegistryResponse {
  const record = isRecord(value) ? value : {};
  const items = Array.isArray(record.items)
    ? record.items
        .map(normalizeModuleManifest)
        .filter((item): item is ModuleManifest => item !== null)
    : [];

  return {
    count: numberValue(record.count, items.length),
    items,
  };
}

export function normalizeModuleAccessState(
  value: unknown,
): ModuleAccessState | null {
  if (!isRecord(value) || typeof value.module_key !== "string") {
    return null;
  }

  const status = normalizeStatus(value.status);
  const accessState = normalizeAccessStateName(value.access_state);
  const category = normalizeCategory(value.category);

  return {
    access_state: accessState,
    category,
    denied_behavior: normalizeDeniedBehavior(value.denied_behavior),
    executable: booleanValue(value.executable, false),
    hidden: booleanValue(value.hidden, accessState === "hidden"),
    locked: booleanValue(value.locked, accessState === "locked"),
    missing_permissions: stringArray(value.missing_permissions),
    module_key: value.module_key,
    reason: stringValue(value.reason),
    required_permissions: stringArray(value.required_permissions),
    route_namespace: stringValue(value.route_namespace, "/"),
    status,
    unavailable: booleanValue(
      value.unavailable,
      accessState === "unavailable" || NON_EXECUTABLE_STATUSES.has(status),
    ),
    visible: booleanValue(value.visible, false),
  };
}

export function normalizeUserModulesResponse(
  value: unknown,
): UserModulesResponse {
  const record = isRecord(value) ? value : {};
  const items = Array.isArray(record.items)
    ? record.items
        .map(normalizeModuleAccessState)
        .filter((item): item is ModuleAccessState => item !== null)
    : [];

  return {
    count: numberValue(record.count, items.length),
    is_owner_full_access: booleanValue(
      record.is_owner_full_access,
      false,
    ),
    items,
    role: stringValue(record.role),
    user_id: numberValue(record.user_id),
  };
}

export function isBusinessModule(
  module: Pick<ModuleAwareNavigationRecord, "category"> | ModuleAccessState,
) {
  return module.category === "business";
}

export function isAdminOrSystemModule(
  module: Pick<ModuleAwareNavigationRecord, "category"> | ModuleAccessState,
) {
  return module.category === "admin" || module.category === "system";
}

export function findModuleAccessState(
  moduleKey: string,
  accessStates: readonly ModuleAccessState[] | null | undefined,
) {
  return (
    accessStates?.find((state) => state.module_key === moduleKey) ?? null
  );
}

export function isModuleVisible(
  state: ModuleAccessState | ModuleNavigationState | null | undefined,
) {
  if (!state) {
    return false;
  }
  return "isVisible" in state ? state.isVisible : state.visible;
}

export function isModuleLocked(
  state: ModuleAccessState | ModuleNavigationState | null | undefined,
) {
  if (!state) {
    return false;
  }
  return "isLocked" in state ? state.isLocked : state.locked;
}

export function isModuleHidden(
  state: ModuleAccessState | ModuleNavigationState | null | undefined,
) {
  if (!state) {
    return false;
  }
  return "isHidden" in state ? state.isHidden : state.hidden;
}

export function isModuleUnavailable(
  state: ModuleAccessState | ModuleNavigationState | null | undefined,
) {
  if (!state) {
    return false;
  }
  if ("isUnavailable" in state) {
    return state.isUnavailable;
  }
  return (
    state.unavailable ||
    state.access_state === "planned" ||
    state.access_state === "adapter_pending" ||
    state.access_state === "unavailable" ||
    NON_EXECUTABLE_STATUSES.has(state.status)
  );
}

export function canEnterModuleRoute(
  state: ModuleAccessState | ModuleNavigationState | null | undefined,
) {
  if (!state) {
    return false;
  }
  if ("canEnter" in state) {
    return state.canEnter;
  }
  return (
    state.visible &&
    !state.locked &&
    !state.hidden &&
    !isModuleUnavailable(state) &&
    state.access_state === "available"
  );
}

function getBadge(
  state: Pick<
    ModuleNavigationState,
    "isLocked" | "isUnavailable" | "accessState" | "status"
  >,
): ModuleNavigationState["badge"] {
  if (state.isLocked) {
    return "locked";
  }
  if (state.accessState === "planned" || state.status === "planned") {
    return "planned";
  }
  if (
    state.accessState === "adapter_pending" ||
    state.status === "adapter_pending"
  ) {
    return "adapter_pending";
  }
  if (state.isUnavailable) {
    return "unavailable";
  }
  return null;
}

function stateFromAccessState(
  accessState: ModuleAccessState,
  moduleAccessUnknown: boolean,
): ModuleNavigationState {
  const isUnavailable = isModuleUnavailable(accessState);
  const result: ModuleNavigationState = {
    accessState: accessState.access_state,
    badge: null,
    canAccess: accessState.visible && !accessState.locked && !accessState.hidden,
    canEnter: canEnterModuleRoute(accessState),
    isHidden: accessState.hidden,
    isLocked: accessState.locked,
    isUnavailable,
    isVisible: accessState.visible && !accessState.hidden,
    missingPermissions: accessState.missing_permissions,
    moduleAccessUnknown,
    reason: accessState.reason,
    status: accessState.status,
  };

  return {
    ...result,
    badge: getBadge(result),
  };
}

function fallbackNavigationState(
  permissions: FrontendPermissions | null | undefined,
  module: ModuleAwareNavigationRecord,
  moduleAccessUnknown: boolean,
): ModuleNavigationState {
  const permissionState = getPermissionAccessState(permissions, module);
  const staticUnavailable =
    module.status !== undefined && NON_EXECUTABLE_STATUSES.has(module.status);
  const isVisible = permissionState.isVisible;
  const isHidden = !isVisible;
  const isLocked = !staticUnavailable && permissionState.isLocked;
  const isUnavailable = permissionState.canAccess && staticUnavailable;
  const accessState: ModuleNavigationState["accessState"] = staticUnavailable
    ? module.status === "planned"
      ? "planned"
      : module.status === "adapter_pending"
        ? "adapter_pending"
        : "unavailable"
    : moduleAccessUnknown
      ? "unknown"
      : permissionState.canAccess
        ? "available"
        : permissionState.isLocked
          ? "locked"
          : "hidden";

  const result: ModuleNavigationState = {
    accessState,
    badge: null,
    canAccess: permissionState.canAccess,
    canEnter: permissionState.canAccess && !isUnavailable,
    isHidden,
    isLocked,
    isUnavailable,
    isVisible,
    missingPermissions:
      !permissionState.canAccess && module.required_permission
        ? [module.required_permission]
        : [],
    moduleAccessUnknown,
    reason: moduleAccessUnknown
      ? "Module access state is unavailable; using permission fallback."
      : "",
    status: module.status ?? "unknown",
  };

  return {
    ...result,
    badge: getBadge(result),
  };
}

function ownerNavigationState(
  module: ModuleAwareNavigationRecord,
  moduleAccessUnknown: boolean,
): ModuleNavigationState {
  return {
    accessState: "available",
    badge: null,
    canAccess: true,
    canEnter: true,
    isHidden: false,
    isLocked: false,
    isUnavailable: false,
    isVisible: true,
    missingPermissions: [],
    moduleAccessUnknown,
    reason: "Owner full access bypasses frontend permission checks.",
    status: module.status ?? "unknown",
  };
}

export function getNavigationStateForModule(
  permissions: FrontendPermissions | null | undefined,
  module: ModuleAwareNavigationRecord,
  accessStates: readonly ModuleAccessState[] | null | undefined,
  options: { moduleAccessUnknown?: boolean } = {},
): ModuleNavigationState {
  const accessState = findModuleAccessState(module.module_key, accessStates);
  const moduleAccessUnknown =
    options.moduleAccessUnknown === true || accessState === null;

  if (isOwnerFullAccess(permissions)) {
    return ownerNavigationState(module, moduleAccessUnknown);
  }

  if (accessState) {
    return stateFromAccessState(accessState, options.moduleAccessUnknown === true);
  }

  return fallbackNavigationState(permissions, module, moduleAccessUnknown);
}

export function findModuleRouteForPath<
  T extends Pick<ModuleAwareNavigationRecord, "route_namespace">,
>(pathname: string, routes: readonly T[]) {
  const normalizedPath = pathname === "/" ? "/" : pathname.replace(/\/+$/, "");
  const matches = routes.filter((route) => {
    const namespace =
      route.route_namespace === "/"
        ? "/"
        : route.route_namespace.replace(/\/+$/, "");
    return (
      normalizedPath === namespace ||
      (namespace !== "/" && normalizedPath.startsWith(`${namespace}/`))
    );
  });

  return (
    matches.sort(
      (left, right) =>
        right.route_namespace.length - left.route_namespace.length,
    )[0] ?? null
  );
}

export function getModuleRouteDecision(
  permissions: FrontendPermissions | null | undefined,
  pathname: string,
  routes: readonly ModuleAwareNavigationRecord[],
  accessStates: readonly ModuleAccessState[] | null | undefined,
  options: { moduleAccessUnknown?: boolean } = {},
): ModuleRouteDecision {
  const route = findModuleRouteForPath(pathname, routes);

  if (!route) {
    return {
      accessState: "unknown",
      badge: null,
      canAccess: true,
      canEnter: true,
      isHidden: false,
      isLocked: false,
      isProtected: false,
      isUnavailable: false,
      isVisible: true,
      missingPermissions: [],
      moduleAccessUnknown: options.moduleAccessUnknown === true,
      module_key: null,
      noticeType: "none",
      reason: "",
      status: "unknown",
    };
  }

  const state = getNavigationStateForModule(
    permissions,
    route,
    accessStates,
    options,
  );
  const noticeType = state.canEnter
    ? "none"
    : state.isUnavailable && !state.isLocked
      ? "module_unavailable"
      : "no_permission";

  return {
    ...state,
    isProtected: true,
    module_key: route.module_key,
    noticeType,
  };
}

export function assertNavigationModulesRegistered(
  navigationRecords: readonly ModuleAwareNavigationRecord[],
  registryItems: readonly ModuleManifest[],
) {
  const registryByKey = new Map(
    registryItems.map((manifest) => [manifest.module_key, manifest]),
  );
  const errors: string[] = [];

  for (const item of navigationRecords) {
    if (!item.module_key && !item.core_shell_exception) {
      errors.push(`${item.label} is missing module_key.`);
      continue;
    }
    if (item.core_shell_exception) {
      continue;
    }

    const manifest = registryByKey.get(item.module_key);
    if (!manifest) {
      errors.push(`${item.label} uses unregistered module ${item.module_key}.`);
      continue;
    }
    if (item.category !== manifest.category) {
      errors.push(`${item.module_key} category does not match registry.`);
    }
    if (item.denied_behavior !== manifest.denied_behavior) {
      errors.push(`${item.module_key} denied_behavior does not match registry.`);
    }
    if (item.route_namespace !== manifest.route_namespace) {
      errors.push(`${item.module_key} route_namespace does not match registry.`);
    }
    if (
      item.required_permission &&
      !manifest.required_permissions.includes(item.required_permission)
    ) {
      errors.push(
        `${item.module_key} required_permission is not declared by registry.`,
      );
    }
  }

  if (errors.length > 0) {
    throw new Error(errors.join("\n"));
  }
}
