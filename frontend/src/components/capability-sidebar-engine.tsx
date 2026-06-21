"use client";

import { LockKeyhole } from "lucide-react";
import Link from "next/link";

import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import type { ProductCapabilityBadge } from "@/lib/frontend-capability-state";

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
    sidebarItems,
    uiState,
  } = useFrontendCapabilityState();
  const footerLabel = isLoading
    ? "正在加载工作台"
    : uiState === "fallback"
      ? "准备中"
      : uiState === "degraded"
        ? "部分信息待刷新"
        : `${sidebarItems.length} 个功能区`;

  return (
    <>
      <nav aria-label="Console navigation" className="sidebar-navigation">
        {groups.map((group) => (
          <div className="navigation-group" key={group.label}>
            <span className="navigation-label">{group.label}</span>
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
        ))}
      </nav>

      <div className="sidebar-footer">
        <span className="environment-dot" />
        {footerLabel}
      </div>
    </>
  );
}
