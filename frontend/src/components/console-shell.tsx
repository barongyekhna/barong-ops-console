"use client";

import { Blocks, LogOut, Menu } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { CapabilitySidebarEngine } from "@/components/capability-sidebar-engine";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { pageTitles } from "@/lib/navigation";

function roleLabel(role: string | null | undefined) {
  if (role === "owner") {
    return "owner";
  }
  if (role === "super_admin" || role === "admin") {
    return "组织管理员";
  }
  if (role === "reviewer") {
    return "审核员";
  }
  if (role === "operator") {
    return "操作员";
  }
  if (role === "viewer") {
    return "查看员";
  }
  return "成员";
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const capabilityState = useFrontendCapabilityState();
  const { getCapabilityForPath } = capabilityState;
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

  function handleLogoClick() {
    setIsNavigationOpen(false);
    router.push("/");
  }

  const currentCapability = getCapabilityForPath(pathname);
  const title = pageTitles[pathname] ?? currentCapability?.label ?? "工作台";
  const showFallbackBanner =
    capabilityState.isLoading || capabilityState.uiState === "fallback";
  const fallbackBannerTitle = capabilityState.isLoading
    ? "正在加载系统状态"
    : "服务暂时不可用";
  const fallbackBannerBody = capabilityState.isLoading
    ? "部分信息稍后刷新"
    : "请稍后刷新";

  return (
    <div className="console-layout">
      <aside
        className={`sidebar ${isNavigationOpen ? "sidebar-open" : ""}`}
      >
        <button
          aria-label="返回首页"
          className="brand-lockup brand-home-button"
          onClick={handleLogoClick}
          title="返回首页"
          type="button"
        >
          <span className="brand-mark">
            <Blocks aria-hidden="true" size={20} />
          </span>
          <span>
            <strong>Barong</strong>
            <small>运营工作台</small>
          </span>
        </button>

        <CapabilitySidebarEngine
          onNavigate={() => setIsNavigationOpen(false)}
          pathname={pathname}
        />
      </aside>

      <div className="console-main">
        <header className="topbar">
          <div className="topbar-title">
            <button
              aria-label="打开或收起导航"
              className="icon-button menu-button"
              onClick={() => setIsNavigationOpen((open) => !open)}
              title="打开或收起导航"
              type="button"
            >
              <Menu aria-hidden="true" size={20} />
            </button>
            <div>
              <span className="eyebrow">工作台</span>
              <h1>{title}</h1>
            </div>
          </div>

          <div className="account-area">
            <div className="account-copy">
              <strong>{user?.username}</strong>
              <span>{roleLabel(user?.role)}</span>
            </div>
            <button
              className="logout-button"
              disabled={isLoggingOut}
              onClick={() => void handleLogout()}
              type="button"
            >
              <LogOut aria-hidden="true" size={17} />
              {isLoggingOut ? "正在退出" : "退出"}
            </button>
          </div>
        </header>

        <main className="page-content">
          {showFallbackBanner ? (
            <section
              aria-live="polite"
              className="runtime-fallback-banner"
              role="status"
            >
              <div>
                <strong>{fallbackBannerTitle}</strong>
                <span>{fallbackBannerBody}</span>
              </div>
              <button
                className="secondary-button"
                onClick={() => void capabilityState.refresh()}
                type="button"
              >
                刷新
              </button>
            </section>
          ) : null}
          {children}
        </main>
      </div>
    </div>
  );
}
