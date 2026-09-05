"use client";

import {
  Building2,
  ChevronDown,
  ChevronRight,
  LockKeyhole,
  MessageCircle,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import type {
  ProductCapabilityBadge,
  ProductCapabilityItem,
} from "@/lib/frontend-capability-state";
import { getModuleDisplayName } from "@/lib/i18n";
import type {
  ModuleControlOrgGroup,
  ModuleControlState,
} from "@/lib/module-control-api";
import type { ModuleAccessState } from "@/lib/module-registry";
import { isOwnerRole, isSuperAdminRole, normalizeRole } from "@/lib/roles";
import { useC19UnreadCount } from "@/modules/c19/C19UnreadStatus";
import { useCsNewCount } from "@/modules/cs/customer-service/useCsNewCount";

const C_SYSTEM_MODULE_ORDER = [
  {
    label: "模块控制",
    module_key: "admin.modules",
  },
  {
    label: "密钥检测",
    module_key: "admin.key_health",
  },
  {
    label: "权限管理",
    module_key: "admin.permissions",
  },
  {
    label: "用户管理",
    module_key: "admin.users",
  },
  {
    label: "接入钥匙",
    module_key: "admin.mcp_keys",
  },
  {
    label: "控制台",
    module_key: "core.dashboard",
  },
  {
    label: "VPN",
    module_key: "core.vpn",
  },
] as const;

const C_SYSTEM_MODULE_KEYS: ReadonlySet<string> = new Set(
  C_SYSTEM_MODULE_ORDER.map((item) => item.module_key),
);

// ⚠️ 死规矩:新建业务系列必须往这里加前缀,否则模块在侧边栏组织树里
// 直接隐身(W-A 踩过一次,B2B 又踩了一次)。加模块时这是第一个要改的地方。
const ORGANIZATION_MODULE_PREFIXES = [
  "r.",
  "k.",
  "i.",
  "p.",
  "f.",
  "h.",
  "w.",
  "cs.",
  "b2b.",
  "geo.",
  "seo.",
  "gmc.",
  "content.",
  "mfg.",
  "sm.",
] as const;
const SIDEBAR_ORG_SNAPSHOT_PREFIX = "barong:sidebar-orgs";
const R_WAREHOUSE_MODULE_KEY = "r.warehouse";
const R_ANALYSIS_MODULE_KEY = "r.analysis";
const CS_CUSTOMER_SERVICE_MODULE_KEY = "cs.customer_service";

const CAPABILITY_BADGE_LABELS: Record<
  Exclude<ProductCapabilityBadge, null>,
  string
> = {
  adapter_pending: "配置中",
  backend_unavailable: "暂不可用",
  locked: "受限",
  mock: "预览",
  no_execution: "待配置",
  read_only: "部分可用",
};

function isOrganizationLayerModule(module: ModuleControlState) {
  const moduleId = module.module_id.trim().toLowerCase();
  if (!moduleId || C_SYSTEM_MODULE_KEYS.has(moduleId)) {
    return false;
  }
  if (
    ORGANIZATION_MODULE_PREFIXES.some((prefix) => moduleId.startsWith(prefix))
  ) {
    return true;
  }
  return (
    moduleId.includes(".seo") ||
    moduleId.includes("_seo") ||
    moduleId.includes(".gmc") ||
    moduleId.includes("_gmc") ||
    moduleId.includes("merchant") ||
    moduleId.includes("product")
  );
}

function organizationKey(organization: ModuleControlOrgGroup) {
  return organization.org_id || organization.org_name;
}

function capabilityForModule(
  byModuleKey: Map<string, ProductCapabilityItem>,
  moduleKey: string,
) {
  return byModuleKey.get(moduleKey) ?? null;
}

function capabilitySidebarVisible(item: ProductCapabilityItem | null) {
  return Boolean(
    item?.route_bound &&
      item.sidebar_state !== "hidden" &&
      item.state !== "hidden",
  );
}

function clearLegacySidebarOrgSnapshots() {
  if (typeof window === "undefined") {
    return;
  }
  try {
    for (let index = window.sessionStorage.length - 1; index >= 0; index -= 1) {
      const key = window.sessionStorage.key(index);
      if (key?.startsWith(SIDEBAR_ORG_SNAPSHOT_PREFIX)) {
        window.sessionStorage.removeItem(key);
      }
    }
  } catch {
    // Sidebar state must come from backend bootstrap; stale local snapshots are ignored.
  }
}

function moduleAccessAllows(
  moduleAccessByKey: Map<string, ModuleAccessState>,
  moduleKey: string,
  fallbackItem: ProductCapabilityItem | null,
) {
  const access = moduleAccessByKey.get(moduleKey);
  if (access) {
    return Boolean(access.visible && !access.hidden);
  }

  return capabilitySidebarVisible(fallbackItem);
}

function isRSeriesModule(moduleId: string) {
  return moduleId.trim().toLowerCase().startsWith("r.");
}

function isRWarehouseModule(moduleId: string) {
  return moduleId.trim().toLowerCase() === R_WAREHOUSE_MODULE_KEY;
}

function isRAnalysisModule(moduleId: string) {
  return moduleId.trim().toLowerCase() === R_ANALYSIS_MODULE_KEY;
}

function isActiveModuleControlState(module: ModuleControlState) {
  return (
    module.enabled === true &&
    module.status === "active" &&
    module.runtime_status === "active"
  );
}

function rSeriesSidebarAllows({
  item,
  module,
  moduleAccessByKey,
  organization,
}: {
  item: ProductCapabilityItem | null;
  module: ModuleControlState;
  moduleAccessByKey: Map<string, ModuleAccessState>;
  organization: ModuleControlOrgGroup;
}) {
  if (!isRSeriesModule(module.module_id)) {
    return null;
  }
  // 组织归属由后端判定：R 系列在 INTL_TRADE_ONLY_MODULE_KEYS 里，
  // 非国际贸易组织的成员在模块清单里根本拿不到这些条目。
  // 这里原本还按组织中文名再判一次——第二套真相源，改个组织名就失效。
  if (!item?.route_bound) {
    return false;
  }
  if (isRWarehouseModule(module.module_id)) {
    return isActiveModuleControlState(module);
  }
  if (isRAnalysisModule(module.module_id)) {
    return true;
  }
  return moduleAccessAllows(moduleAccessByKey, module.module_id, item);
}

function sidebarItemForOrganizationModule({
  item,
  module,
}: {
  item: ProductCapabilityItem | null;
  module: ModuleControlState;
}) {
  if (!item) {
    return null;
  }

  if (isRWarehouseModule(module.module_id) && isActiveModuleControlState(module)) {
    return {
      ...item,
      badge: null,
      can_enter: true,
      reason: "R-W 已为当前组织启用。",
      required_module_state: "R-W module-control 状态为 active。",
      sidebar_state: "allowed" as const,
      state: "allowed" as const,
      unlock_condition: "打开 R-W 产品数据仓库。",
    };
  }

  if (isRAnalysisModule(module.module_id)) {
    return {
      ...item,
      can_enter: true,
      reason: "R-A 占位页可查看，运行能力等待 R-W 就绪。",
      required_module_state: "R-A 当前为占位模块。",
      sidebar_state:
        item.sidebar_state === "hidden" ? "partial" as const : item.sidebar_state,
      state: item.state === "hidden" ? "partial" as const : item.state,
      unlock_condition: "打开 R-A 产品分析中心占位页。",
    };
  }

  return item;
}

function sortModules(modules: ModuleControlState[]) {
  return [...modules].sort((left, right) => {
    const categoryDelta = left.category.localeCompare(right.category);
    if (categoryDelta !== 0) {
      return categoryDelta;
    }
    const labelDelta = left.display_name.localeCompare(right.display_name);
    if (labelDelta !== 0) {
      return labelDelta;
    }
    return left.module_id.localeCompare(right.module_id);
  });
}

function sortOrganizations(organizations: ModuleControlOrgGroup[]) {
  return [...organizations].sort((left, right) => {
    const labelDelta = left.org_name.localeCompare(right.org_name);
    if (labelDelta !== 0) {
      return labelDelta;
    }
    return left.org_id.localeCompare(right.org_id);
  });
}

function scopedOrganizationGroups({
  byModuleKey,
  isOwner,
  moduleAccessByKey,
  moduleControlReady,
  organizations,
  role,
  userOrgId,
}: {
  byModuleKey: Map<string, ProductCapabilityItem>;
  isOwner: boolean;
  moduleAccessByKey: Map<string, ModuleAccessState>;
  moduleControlReady: boolean;
  organizations: ModuleControlOrgGroup[];
  role: string;
  userOrgId: string | null | undefined;
}) {
  if (!moduleControlReady) {
    return [];
  }

  const owner = isOwner || isOwnerRole(role);
  const superAdmin = isSuperAdminRole(role);

  return sortOrganizations(
    organizations
      .filter((organization) => owner || organization.org_id === userOrgId)
      .map((organization) => ({
        ...organization,
        modules: sortModules(
          organization.modules.filter((module) => {
            const item = capabilityForModule(byModuleKey, module.module_id);
            if (!isOrganizationLayerModule(module)) {
              return false;
            }
            const rSeriesAllowed = rSeriesSidebarAllows({
              item,
              module,
              moduleAccessByKey,
              organization,
            });
            if (rSeriesAllowed !== null) {
              return rSeriesAllowed;
            }
            // 「哪些模块只属于国际贸易组织」由后端 INTL_TRADE_ONLY_MODULE_KEYS
            // 判定，非该组织成员在模块清单里根本拿不到这些条目。
            // 这里以前还有一层前端遮罩，靠比对组织中文名实现——既是第二套真相源
            // （后端漏了 k./i./p. 就只在前端被遮，敲 URL 照样进），改个组织名还会
            // 整套失效。2026-08-31 收敛成后端一套。
            if (!moduleAccessAllows(moduleAccessByKey, module.module_id, item)) {
              return false;
            }
            if (owner || superAdmin) {
              return true;
            }
            return capabilitySidebarVisible(item);
          }),
        ),
      })),
  );
}

function SidebarLink({
  item,
  label,
  onNavigate,
  pathname,
  notificationCount = 0,
  tree,
}: {
  item: ProductCapabilityItem;
  label?: string;
  notificationCount?: number;
  onNavigate: () => void;
  pathname: string;
  tree?: boolean;
}) {
  const Icon = item.icon;
  const active = pathname === item.href;
  const locked =
    item.sidebar_state === "forbidden" ||
    item.state === "hidden" ||
    item.can_enter === false;
  const unavailable = item.sidebar_state === "partial";
  const badge = locked ? null : item.badge;
  const visibleBadge = badge === "no_execution" ? null : badge;
  const displayLabel = label ?? getModuleDisplayName(item.module_key, item.label);

  return (
    <Link
      aria-current={active ? "page" : undefined}
      aria-label={
        notificationCount > 0
          ? `${displayLabel}，${notificationCount} 条新消息`
          : visibleBadge
          ? `${displayLabel} ${CAPABILITY_BADGE_LABELS[visibleBadge]}`
          : displayLabel
      }
      className={`navigation-link ${tree ? "navigation-tree-link" : ""} ${
        active ? "active" : ""
      } ${locked ? "locked" : ""} ${unavailable ? "unavailable" : ""}`}
      href={item.href}
      onClick={onNavigate}
      title={locked || unavailable ? item.reason : displayLabel}
    >
      <Icon aria-hidden="true" size={18} />
      <span>{displayLabel}</span>
      {locked ? (
        <LockKeyhole
          aria-hidden="true"
          className="navigation-lock"
          size={14}
        />
      ) : null}
      {!locked && visibleBadge ? (
        <span className={`navigation-status-badge ${visibleBadge}`}>
          {CAPABILITY_BADGE_LABELS[visibleBadge]}
        </span>
      ) : null}
      {!locked && notificationCount > 0 ? (
        <span
          aria-hidden="true"
          className="navigation-status-badge cs-new-badge"
          title={`${notificationCount} 条新消息`}
        >
          {notificationCount > 99 ? "99+" : notificationCount}
        </span>
      ) : null}
    </Link>
  );
}

function OrganizationModuleRow({
  module,
  item,
  notificationCount,
  onNavigate,
  pathname,
}: {
  module: ModuleControlState;
  item: ProductCapabilityItem | null;
  notificationCount?: number;
  onNavigate: () => void;
  pathname: string;
}) {
  const displayItem = sidebarItemForOrganizationModule({ item, module });
  const label = getModuleDisplayName(
    module.module_id,
    displayItem?.label ?? module.display_name,
  );
  if (displayItem?.route_bound) {
    return (
      <SidebarLink
        item={displayItem}
        label={label}
        notificationCount={notificationCount}
        onNavigate={onNavigate}
        pathname={pathname}
        tree
      />
    );
  }

  return (
    <div className="navigation-link navigation-tree-link unavailable" title={label}>
      <Building2 aria-hidden="true" size={18} />
      <span>{label}</span>
    </div>
  );
}

export function CapabilitySidebarEngine({
  onNavigate,
  pathname,
}: {
  pathname: string;
  onNavigate: () => void;
}) {
  const { isOwner, status, user } = useAuth();
  const {
    byModuleKey,
    isLoading,
    moduleAccessResult,
    moduleControlResult,
    uiState,
  } = useFrontendCapabilityState();
  const role = normalizeRole(user?.role);
  const c19UnreadCount = useC19UnreadCount(status === "authenticated");
  const csNewCount = useCsNewCount(status === "authenticated");
  const [expandedOrgIds, setExpandedOrgIds] = useState<Set<string>>(
    () => new Set(),
  );
  const knownOrgIdsRef = useRef<Set<string>>(new Set());
  const moduleAccessByKey = useMemo(
    () =>
      new Map(
        (moduleAccessResult?.data.items ?? []).map((item) => [
          item.module_key,
          item,
        ]),
      ),
    [moduleAccessResult?.data.items],
  );
  const runtimeOrganizations = useMemo(
    () =>
      scopedOrganizationGroups({
        byModuleKey,
        isOwner,
        moduleAccessByKey,
        moduleControlReady: moduleControlResult?.ok === true,
        organizations: moduleControlResult?.data.organizations ?? [],
        role,
        userOrgId: user?.organization_id,
      }),
    [
      byModuleKey,
      isOwner,
      moduleAccessByKey,
      moduleControlResult?.data.organizations,
      moduleControlResult?.ok,
      role,
      user?.organization_id,
    ],
  );
  const organizations = runtimeOrganizations;

  useEffect(() => {
    clearLegacySidebarOrgSnapshots();
  }, []);

  useEffect(() => {
    if (organizations.length === 0) {
      return;
    }
    setExpandedOrgIds((current) => {
      let changed = false;
      const next = new Set(current);
      for (const organization of organizations) {
        const key = organizationKey(organization);
        if (!knownOrgIdsRef.current.has(key)) {
          knownOrgIdsRef.current.add(key);
          next.add(key);
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [organizations]);

  const cSystemItems = useMemo(
    () =>
      C_SYSTEM_MODULE_ORDER.flatMap((entry) => {
        const item = capabilityForModule(byModuleKey, entry.module_key);
        if (!moduleAccessAllows(moduleAccessByKey, entry.module_key, item)) {
          return [];
        }
        return item ? [{ item, label: entry.label as string }] : [];
      }),
    [byModuleKey, moduleAccessByKey],
  );
  const organizationGroups = organizations;
  const organizationModuleCount = organizationGroups.reduce(
    (count, organization) => count + organization.modules.length,
    0,
  );
  const visibleSidebarCount = cSystemItems.length + organizationModuleCount + 1;
  // 三种状态说三句不同的话（2026-08-31）。
  // 以前「没权限」和「真降级」都渲染成「部分信息待刷新」，而那句话又因为
  // 4 个有意 deferred 的 bootstrap 项被折进降级判定，从登录第一秒起就永远亮着 ——
  // 一个永远亮的警报等于没有警报，真出事时没人会当回事。
  const footerLabel = isLoading
    ? "正在加载工作台"
    : uiState === "fallback"
      ? "准备中"
      : uiState === "unauthorized"
        ? "这个账号没有部分模块的权限"
        : uiState === "degraded"
          ? "部分信息没取到，稍后自动重试"
          : `${visibleSidebarCount} 个功能区`;

  return (
    <>
      <nav aria-label="工作台导航" className="sidebar-navigation">
        <div className="navigation-group">
          <span className="navigation-label">C系统</span>
          {cSystemItems.map(({ item, label }) => (
            <SidebarLink
              item={item}
              key={item.module_key}
              label={label}
              onNavigate={onNavigate}
              pathname={pathname}
            />
          ))}
          <Link
            aria-current={pathname === "/c19" ? "page" : undefined}
            aria-label={
              c19UnreadCount > 0
                ? `通讯，${c19UnreadCount} 条未读消息`
                : "通讯"
            }
            className={`navigation-link ${pathname === "/c19" ? "active" : ""}`}
            href="/c19"
            onClick={onNavigate}
          >
            <MessageCircle aria-hidden="true" size={18} />
            <span>通讯</span>
            {c19UnreadCount > 0 ? (
              <span
                aria-hidden="true"
                className="navigation-status-badge c19-unread-badge"
                title={`${c19UnreadCount} 条未读消息`}
              >
                {c19UnreadCount > 99 ? "99+" : c19UnreadCount}
              </span>
            ) : null}
          </Link>
        </div>

        <div className="navigation-divider" role="separator" />

        <div className="navigation-group">
          <span className="navigation-label">组织</span>
          {organizationGroups.length === 0 ? (
            <div className="navigation-tree-empty" role="status">
              暂无组织
            </div>
          ) : (
            organizationGroups.map((organization) => {
              const key = organizationKey(organization);
              const expanded = expandedOrgIds.has(key);

              return (
                <div className="navigation-tree-node" key={key}>
                  <button
                    aria-expanded={expanded}
                    className="navigation-tree-toggle"
                    onClick={() => {
                      setExpandedOrgIds((current) => {
                        const next = new Set(current);
                        if (next.has(key)) {
                          next.delete(key);
                        } else {
                          next.add(key);
                        }
                        return next;
                      });
                    }}
                    type="button"
                  >
                    {expanded ? (
                      <ChevronDown aria-hidden="true" size={15} />
                    ) : (
                      <ChevronRight aria-hidden="true" size={15} />
                    )}
                    <Building2 aria-hidden="true" size={17} />
                    <span>{organization.org_name || "未命名组织"}</span>
                  </button>
                  {expanded ? (
                    <div className="navigation-tree-items">
                      {organization.modules.length === 0 ? (
                        <div className="navigation-tree-empty" role="status">
                          暂无模块
                        </div>
                      ) : (
                        organization.modules.map((module) => (
                          <OrganizationModuleRow
                            item={capabilityForModule(
                              byModuleKey,
                              module.module_id,
                            )}
                            key={`${key}:${module.module_id}`}
                            module={module}
                            notificationCount={
                              module.module_id.trim().toLowerCase() ===
                              CS_CUSTOMER_SERVICE_MODULE_KEY
                                ? csNewCount
                                : 0
                            }
                            onNavigate={onNavigate}
                            pathname={pathname}
                          />
                        ))
                      )}
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </div>
      </nav>

      <div className="sidebar-footer">
        <span className="environment-dot" />
        {footerLabel}
      </div>
    </>
  );
}
