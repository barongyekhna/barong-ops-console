"use client";

import { Blocks, LockKeyhole, LogOut, Menu } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { useModuleAccess } from "@/components/module-access-provider";
import { navigationGroups, pageTitles } from "@/lib/navigation";
import { getNavigationStateForModule } from "@/lib/module-registry";

const MODULE_BADGE_LABELS = {
  adapter_pending: "Adapter pending",
  locked: "Locked",
  planned: "Planned",
  unavailable: "Unavailable",
} as const;

export function ConsoleShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const {
    error: moduleAccessError,
    items: moduleAccessItems,
    moduleAccessUnknown,
  } = useModuleAccess();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [isNavigationOpen, setIsNavigationOpen] = useState(false);
  const visibleNavigationGroups = navigationGroups
    .map((group) => ({
      ...group,
      items: group.items
        .map((item) => ({
          ...item,
          access: getNavigationStateForModule(
            user?.permissions,
            item,
            moduleAccessItems,
            { moduleAccessUnknown },
          ),
        }))
        .filter((item) => item.access.isVisible),
    }))
    .filter((group) => group.items.length > 0);

  async function handleLogout() {
    setIsLoggingOut(true);
    try {
      await logout();
      router.replace("/login");
    } finally {
      setIsLoggingOut(false);
    }
  }

  const title = pageTitles[pathname] ?? "Console";

  return (
    <div className="console-layout">
      <aside
        className={`sidebar ${isNavigationOpen ? "sidebar-open" : ""}`}
      >
        <div className="brand-lockup">
          <span className="brand-mark">
            <Blocks aria-hidden="true" size={20} />
          </span>
          <span>
            <strong>Barong</strong>
            <small>Ops Console</small>
          </span>
        </div>

        <nav aria-label="Console navigation" className="sidebar-navigation">
          {visibleNavigationGroups.map((group) => (
            <div className="navigation-group" key={group.label}>
              <span className="navigation-label">{group.label}</span>
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = pathname === item.href;
                const locked = item.access.isLocked;
                const unavailable = item.access.isUnavailable;
                const badge = item.access.badge;

                return (
                  <Link
                    aria-current={active ? "page" : undefined}
                    aria-label={
                      badge
                        ? `${item.label} ${MODULE_BADGE_LABELS[badge]}`
                        : item.label
                    }
                    className={`navigation-link ${active ? "active" : ""} ${
                      locked ? "locked" : ""
                    } ${unavailable ? "unavailable" : ""}`}
                    href={item.href}
                    key={item.href}
                    onClick={() => setIsNavigationOpen(false)}
                    title={
                      locked
                        ? "No permission for this section"
                        : unavailable
                          ? "Module unavailable"
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
                        {MODULE_BADGE_LABELS[badge]}
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
          {moduleAccessUnknown
            ? (moduleAccessError?.message ?? "Module access fallback")
            : "Foundation environment"}
        </div>
      </aside>

      <div className="console-main">
        <header className="topbar">
          <div className="topbar-title">
            <button
              aria-label="Toggle navigation"
              className="icon-button menu-button"
              onClick={() => setIsNavigationOpen((open) => !open)}
              title="Toggle navigation"
              type="button"
            >
              <Menu aria-hidden="true" size={20} />
            </button>
            <div>
              <span className="eyebrow">Workspace</span>
              <h1>{title}</h1>
            </div>
          </div>

          <div className="account-area">
            <div className="account-copy">
              <strong>{user?.username}</strong>
              <span>{user?.role}</span>
            </div>
            <button
              className="logout-button"
              disabled={isLoggingOut}
              onClick={() => void handleLogout()}
              type="button"
            >
              <LogOut aria-hidden="true" size={17} />
              {isLoggingOut ? "Signing out" : "Logout"}
            </button>
          </div>
        </header>

        <main className="page-content">{children}</main>
      </div>
    </div>
  );
}
