"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { CapabilityEmptyStateEngine } from "@/components/capability-empty-state";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { useModuleAccess } from "@/components/module-access-provider";
import {
  ModuleUnavailableNotice,
  NoPermissionNotice,
} from "@/components/no-permission-notice";
import { useAuth } from "@/components/auth-provider";
import { navigationModuleRecords } from "@/lib/navigation";
import { getModuleRouteDecision } from "@/lib/module-registry";
import { isOwnerRole, isSuperAdminRole } from "@/lib/roles";

const R_SERIES_TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司";
const R_WAREHOUSE_MODULE_KEY = "r.warehouse";
const R_WAREHOUSE_ROUTE_PREFIX = "/r-w";
const R_SERIES_ROUTE_PREFIXES = [R_WAREHOUSE_ROUTE_PREFIX, "/r-a"] as const;
const R_ANALYSIS_ROUTE_PREFIX = "/r-a";

function isRSeriesPath(pathname: string) {
  return R_SERIES_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function isRAnalysisPath(pathname: string) {
  return (
    pathname === R_ANALYSIS_ROUTE_PREFIX ||
    pathname.startsWith(`${R_ANALYSIS_ROUTE_PREFIX}/`)
  );
}

function isRWarehousePath(pathname: string) {
  return (
    pathname === R_WAREHOUSE_ROUTE_PREFIX ||
    pathname.startsWith(`${R_WAREHOUSE_ROUTE_PREFIX}/`)
  );
}

function RWarehouseNoPermissionPopup() {
  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        alignItems: "center",
        background: "color-mix(in srgb, var(--color-panel-base) 38%, transparent)",
        display: "grid",
        inset: 0,
        justifyItems: "center",
        padding: 20,
        position: "fixed",
        zIndex: 80,
      }}
    >
      <div
        style={{
          background: "var(--color-surface)",
          border: "1px solid var(--color-line)",
          borderRadius: 8,
          boxShadow: "0 20px 60px color-mix(in srgb, var(--color-panel-base) 22%, transparent)",
          color: "var(--color-text-strong)",
          fontWeight: 760,
          maxWidth: 420,
          padding: 20,
          width: "100%",
        }}
      >
        暂无权限，请联系管理员开通权限
      </div>
    </div>
  );
}

export function PermissionRouteGuard({
  children,
}: {
  children: ReactNode;
}) {
  const pathname = usePathname();
  const { status, user } = useAuth();
  const {
    getCapabilityForPath,
    isLoading: capabilityStateLoading,
    moduleControlResult,
  } =
    useFrontendCapabilityState();
  const { items, moduleAccessUnknown } = useModuleAccess();
  const capability = getCapabilityForPath(pathname);
  const isAuthenticated = status === "authenticated";
  const isC19Route =
    (pathname === "/c19" || pathname.startsWith("/c19/")) && isAuthenticated;
  const isPrivilegedRole =
    isOwnerRole(user?.role) || isSuperAdminRole(user?.role);
  const isOwner = isOwnerRole(user?.role);
  const isUserManagerRoute =
    pathname === "/users" && isAuthenticated;
  const isOrganizationListRoute =
    pathname === "/organizations" && isAuthenticated;
  const isPermissionCenterRoute =
    pathname === "/permissions" && isAuthenticated && isPrivilegedRole;
  const isMcpKeysRoute =
    pathname === "/mcp-keys" && isAuthenticated && isPrivilegedRole;
  const isModuleControlRoute =
    (pathname === "/modules" || pathname === "/module-control") &&
    isAuthenticated &&
    isOwner;
  const rSeriesOrganization = moduleControlResult?.data.organizations.find(
    (organization) =>
      organization.org_name.trim() === R_SERIES_TARGET_ORGANIZATION_NAME,
  );
  const hasRSeriesOrganizationBinding = Boolean(rSeriesOrganization);
  const rWarehouseActive = Boolean(
    rSeriesOrganization?.modules.some(
      (module) =>
        module.module_id.trim().toLowerCase() === R_WAREHOUSE_MODULE_KEY &&
        module.enabled === true &&
        module.status === "active" &&
        module.runtime_status === "active",
    ),
  );

  if (
    isC19Route ||
    isUserManagerRoute ||
    isOrganizationListRoute ||
    isPermissionCenterRoute ||
    isMcpKeysRoute ||
    isModuleControlRoute
  ) {
    return children;
  }

  if (
    isAuthenticated &&
    isRSeriesPath(pathname) &&
    !capabilityStateLoading &&
    moduleControlResult?.ok === true &&
    !hasRSeriesOrganizationBinding
  ) {
    return (
      <NoPermissionNotice
        description="R 系列模块仅绑定到涌龙麟（深圳）国际贸易有限公司。"
        title="R 系列模块不可见"
      />
    );
  }

  if (
    isAuthenticated &&
    isRWarehousePath(pathname) &&
    hasRSeriesOrganizationBinding &&
    rWarehouseActive &&
    isPrivilegedRole
  ) {
    return children;
  }

  if (
    isAuthenticated &&
    isRWarehousePath(pathname) &&
    hasRSeriesOrganizationBinding &&
    !isPrivilegedRole
  ) {
    return <RWarehouseNoPermissionPopup />;
  }

  if (
    isAuthenticated &&
    isRAnalysisPath(pathname) &&
    hasRSeriesOrganizationBinding
  ) {
    return children;
  }

  if (
    status === "authenticated" &&
    (capabilityStateLoading || moduleAccessUnknown)
  ) {
    return children;
  }

  if (capability && !capability.can_enter) {
    return (
      <CapabilityEmptyStateEngine
        reason={capability.reason}
        required_execution_mode={capability.required_execution_mode}
        required_module_state={capability.required_module_state}
        required_org_state={capability.required_org_state}
        required_permission={capability.required_permission}
        state={capability.state}
        title={`${capability.label}暂不可用`}
        unlock_condition={capability.unlock_condition}
      />
    );
  }

  const decision = getModuleRouteDecision(
    null,
    pathname,
    navigationModuleRecords,
    items,
    { moduleAccessUnknown },
  );

  if (decision.isProtected && !decision.canEnter) {
    if (decision.noticeType === "module_unavailable") {
      return <ModuleUnavailableNotice />;
    }

    return <NoPermissionNotice />;
  }

  return children;
}
