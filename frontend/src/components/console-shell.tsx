"use client";

import { Blocks, LogOut, Menu } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { CapabilitySidebarEngine } from "@/components/capability-sidebar-engine";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { pageTitles } from "@/lib/navigation";

export function ConsoleShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const { getCapabilityForPath } = useFrontendCapabilityState();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [isNavigationOpen, setIsNavigationOpen] = useState(false);

  async function handleLogout() {
    setIsLoggingOut(true);
    try {
      await logout();
      router.replace("/login");
    } finally {
      setIsLoggingOut(false);
    }
  }

  const currentCapability = getCapabilityForPath(pathname);
  const title = pageTitles[pathname] ?? currentCapability?.label ?? "Workspace";

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
            <small>Operations</small>
          </span>
        </div>

        <CapabilitySidebarEngine
          onNavigate={() => setIsNavigationOpen(false)}
          pathname={pathname}
        />
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

        <main className="page-content">
          {children}
        </main>
      </div>
    </div>
  );
}
