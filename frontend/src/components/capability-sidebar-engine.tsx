"use client";

import { Building2, ChevronDown, ChevronRight, LockKeyhole } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import type { ProductCapabilityBadge } from "@/lib/frontend-capability-state";

const TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司";
const OWNER_ORG_MODULE_ORDER = [
  {
    label: "Product Knowledge (K)",
    module_key: "k.product_knowledge",
  },
  {
    label: "Module Control",
    module_key: "admin.modules",
  },
  {
    label: "API Key Management",
    module_key: "admin.key_management",
  },
  {
    label: "Users",
    module_key: "admin.users",
  },
  {
    label: "Permissions",
    module_key: "admin.permissions",
  },
];

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

export function CapabilitySidebarEngine({
  onNavigate,
  pathname,
}: {
  pathname: string;
  onNavigate: () => void;
}) {
  const {
    groups,
    isLoading,
    moduleControlResult,
    permissionSnapshot,
    sidebarItems,
    uiState,
  } = useFrontendCapabilityState();
  const [expandedOrgIds, setExpandedOrgIds] = useState<Set<string>>(
    () => new Set([TARGET_ORGANIZATION_NAME]),
  );
  const isOwner = permissionSnapshot.is_owner_full_access === true;
  const ownerOrganization = useMemo(() => {
    const organizations = moduleControlResult?.data.organizations ?? [];
    return (
      organizations.find(
        (organization) => organization.org_name === TARGET_ORGANIZATION_NAME,
      ) ??
      organizations[0] ??
      null
    );
  }, [moduleControlResult]);
  const ownerTreeItems = useMemo(() => {
    if (!ownerOrganization) {
      return [];
    }
    const organizationModuleIds = new Set(
      ownerOrganization.modules.map((module) => module.module_id),
    );
    const itemByKey = new Map(
      sidebarItems.map((item) => [item.module_key, item]),
    );
    return OWNER_ORG_MODULE_ORDER
      .filter((entry) => organizationModuleIds.has(entry.module_key))
      .map((entry) => {
        const item = itemByKey.get(entry.module_key);
        return item ? { ...item, label: entry.label } : null;
      })
      .filter((item): item is NonNullable<typeof item> => item !== null);
  }, [ownerOrganization, sidebarItems]);
  const orgTreeKey = ownerOrganization?.org_name ?? TARGET_ORGANIZATION_NAME;
  const orgExpanded = expandedOrgIds.has(orgTreeKey);
  const visibleSidebarCount = isOwner ? ownerTreeItems.length : sidebarItems.length;
  const footerLabel = isLoading
    ? "正在加载工作台"
    : uiState === "fallback"
      ? "准备中"
      : uiState === "degraded"
        ? "部分信息待刷新"
        : `${visibleSidebarCount} 个功能区`;

  return (
    <>
      <nav aria-label="工作台导航" className="sidebar-navigation">
        {isOwner ? (
          <div className="navigation-group">
            <span className="navigation-label">Organizations</span>
            {ownerOrganization ? (
              <>
                <button
                  aria-expanded={orgExpanded}
                  className="navigation-tree-toggle"
                  onClick={() => {
                    setExpandedOrgIds((current) => {
                      const next = new Set(current);
                      if (next.has(orgTreeKey)) {
                        next.delete(orgTreeKey);
                      } else {
                        next.add(orgTreeKey);
                      }
                      return next;
                    });
                  }}
                  type="button"
                >
                  {orgExpanded ? (
                    <ChevronDown aria-hidden="true" size={15} />
                  ) : (
                    <ChevronRight aria-hidden="true" size={15} />
                  )}
                  <Building2 aria-hidden="true" size={17} />
                  <span>{ownerOrganization.org_name}</span>
                </button>
                {orgExpanded ? (
                  <div className="navigation-tree-items">
                    {ownerTreeItems.map((item) => {
                      const Icon = item.icon;
                      const active = pathname === item.href;

                      return (
                        <Link
                          aria-current={active ? "page" : undefined}
                          aria-label={item.label}
                          className={`navigation-link navigation-tree-link ${
                            active ? "active" : ""
                          }`}
                          href={item.href}
                          key={`${ownerOrganization.org_id}:${item.module_key}`}
                          onClick={onNavigate}
                          title={item.label}
                        >
                          <Icon aria-hidden="true" size={18} />
                          <span>{item.label}</span>
                        </Link>
                      );
                    })}
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
        ) : (
          groups.map((group) => (
          <div className="navigation-group" key={group.label}>
            {group.label === "Modules" ? null : (
              <span className="navigation-label">{group.label}</span>
            )}
            {group.items.map((item) => {
              const Icon = item.icon;
              const active = pathname === item.href;
              const locked = item.sidebar_state === "forbidden";
              const unavailable = item.sidebar_state === "partial";
              const badge = item.badge;

              return (
                <Link
                  aria-current={active ? "page" : undefined}
                  aria-label={
                    badge
                      ? `${item.label} ${CAPABILITY_BADGE_LABELS[badge]}`
                      : item.label
                  }
                  className={`navigation-link ${active ? "active" : ""} ${
                    locked ? "locked" : ""
                  } ${unavailable ? "unavailable" : ""}`}
                  href={item.href}
                  key={item.module_key}
                  onClick={onNavigate}
                  title={
                    locked || unavailable
                      ? item.reason
                      : item.label
                  }
                >
                  <Icon aria-hidden="true" size={18} />
                  <span>{item.label}</span>
                  {locked ? (
                    <LockKeyhole
                      aria-hidden="true"
                      className="navigation-lock"
                      size={14}
                    />
                  ) : null}
                  {!locked && badge ? (
                    <span className={`navigation-status-badge ${badge}`}>
                      {CAPABILITY_BADGE_LABELS[badge]}
                    </span>
                  ) : null}
                </Link>
              );
            })}
          </div>
          ))
        )}
      </nav>

      <div className="sidebar-footer">
        <span className="environment-dot" />
        {footerLabel}
      </div>
    </>
  );
}
