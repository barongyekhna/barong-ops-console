"use client";

import { LockKeyhole } from "lucide-react";
import Link from "next/link";

import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import type { ProductCapabilityBadge } from "@/lib/frontend-capability-state";

const CAPABILITY_BADGE_LABELS: Record<
  Exclude<ProductCapabilityBadge, null>,
  string
> = {
  adapter_pending: "Adapter pending",
  backend_unavailable: "Backend unavailable",
  locked: "Locked",
  mock: "Mock",
  no_execution: "No execution",
  read_only: "Read-only",
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
    registryError,
    registryUnavailable,
    sidebarItems,
  } = useFrontendCapabilityState();

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
                      : `${item.label}: ${item.required_permission}`
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
        {isLoading
          ? "Resolving capability graph"
          : registryUnavailable
            ? (registryError?.message ?? "Capability registry unavailable")
            : `${sidebarItems.length} product capabilities`}
      </div>
    </>
  );
}
