export const GLOBAL_PERMISSION_WILDCARD = "*";

export type FrontendPermissionAssignment = {
  permission_key: string;
  scope_type: string;
  scope_key: string;
};

export type FrontendPermissionScopeSummary = {
  scope_type: string;
  scope_key: string;
  permission_keys: string[];
};

export type FrontendPermissions = {
  is_owner_full_access: boolean;
  permission_keys: string[];
  assignments: FrontendPermissionAssignment[];
  scope_summary: FrontendPermissionScopeSummary[];
};

export type PermissionCategory =
  | "core"
  | "business"
  | "admin"
  | "system"
  | "integration"
  | "experimental";

export type PermissionDeniedBehavior =
  | "show_locked"
  | "hide_when_denied";

export type PermissionAwareModule = {
  category: PermissionCategory;
  denied_behavior: PermissionDeniedBehavior;
  required_permission?: string;
  owner_only?: boolean;
};

export type PermissionAwareRoute = PermissionAwareModule & {
  href: string;
};

export type PermissionAccessState = {
  canAccess: boolean;
  isLocked: boolean;
  isVisible: boolean;
};

export type RoutePermissionDecision = PermissionAccessState & {
  isProtected: boolean;
};

export function createOwnerFullAccessPermissions(): FrontendPermissions {
  return {
    assignments: [],
    is_owner_full_access: true,
    permission_keys: [GLOBAL_PERMISSION_WILDCARD],
    scope_summary: [],
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringArray(value: unknown) {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === "string")
    : [];
}

function normalizeAssignment(
  value: unknown,
): FrontendPermissionAssignment | null {
  if (!isRecord(value)) {
    return null;
  }

  if (
    typeof value.permission_key !== "string" ||
    typeof value.scope_type !== "string" ||
    typeof value.scope_key !== "string"
  ) {
    return null;
  }

  return {
    permission_key: value.permission_key,
    scope_key: value.scope_key,
    scope_type: value.scope_type,
  };
}

function normalizeScopeSummary(
  value: unknown,
): FrontendPermissionScopeSummary | null {
  if (!isRecord(value)) {
    return null;
  }

  if (
    typeof value.scope_type !== "string" ||
    typeof value.scope_key !== "string"
  ) {
    return null;
  }

  return {
    permission_keys: stringArray(value.permission_keys),
    scope_key: value.scope_key,
    scope_type: value.scope_type,
  };
}

export function normalizeCurrentUserPermissions(
  value: unknown,
): FrontendPermissions | null {
  if (!isRecord(value)) {
    return null;
  }

  return {
    assignments: Array.isArray(value.assignments)
      ? value.assignments
          .map(normalizeAssignment)
          .filter(
            (
              assignment,
            ): assignment is FrontendPermissionAssignment =>
              assignment !== null,
          )
      : [],
    is_owner_full_access: value.is_owner_full_access === true,
    permission_keys: stringArray(value.permission_keys),
    scope_summary: Array.isArray(value.scope_summary)
      ? value.scope_summary
          .map(normalizeScopeSummary)
          .filter(
            (
              scope,
            ): scope is FrontendPermissionScopeSummary =>
              scope !== null,
          )
      : [],
  };
}

export function isOwnerFullAccess(
  permissions: FrontendPermissions | null | undefined,
) {
  return permissions?.is_owner_full_access === true;
}

export function hasPermission(
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

export function canAccessModule(
  permissions: FrontendPermissions | null | undefined,
  module: PermissionAwareModule | string,
) {
  if (typeof module === "string") {
    return hasPermission(permissions, module);
  }

  if (module.owner_only) {
    return isOwnerFullAccess(permissions);
  }

  if (!module.required_permission) {
    return true;
  }

  return hasPermission(permissions, module.required_permission);
}

export function getPermissionAccessState(
  permissions: FrontendPermissions | null | undefined,
  module: PermissionAwareModule,
): PermissionAccessState {
  const canAccess = canAccessModule(permissions, module);

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

export function findPermissionAwareRoute<T extends PermissionAwareRoute>(
  pathname: string,
  routes: T[],
) {
  return routes.find((route) => route.href === pathname) ?? null;
}

export function getRoutePermissionDecision(
  permissions: FrontendPermissions | null | undefined,
  pathname: string,
  routes: PermissionAwareRoute[],
): RoutePermissionDecision {
  const route = findPermissionAwareRoute(pathname, routes);

  if (!route) {
    return {
      canAccess: true,
      isLocked: false,
      isProtected: false,
      isVisible: true,
    };
  }

  return {
    ...getPermissionAccessState(permissions, route),
    isProtected: true,
  };
}
