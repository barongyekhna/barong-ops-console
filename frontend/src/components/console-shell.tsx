"use client";

import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { Sidebar, TopHeader } from "@/components/saas-shell";
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
    ? "正在同步系统状态"
    : "数据同步延迟";
  const fallbackBannerBody = capabilityState.isLoading
    ? "权限与模块状态正在更新。"
    : "当前导航已保留，可重试刷新。";

  return (
    <div className="console-layout">
      <button
        aria-label="关闭导航"
        className={`nav-scrim ${isNavigationOpen ? "nav-scrim-open" : ""}`}
        onClick={() => setIsNavigationOpen(false)}
        type="button"
      />
      <Sidebar
        isOpen={isNavigationOpen}
        onClose={() => setIsNavigationOpen(false)}
        onLogoClick={handleLogoClick}
        onNavigate={() => setIsNavigationOpen(false)}
        pathname={pathname}
      />

      <div className="console-main">
        <TopHeader
          isActionPending={isLoggingOut}
          onLogout={() => void handleLogout()}
          onMenuToggle={() => setIsNavigationOpen((open) => !open)}
          onRefresh={() => void capabilityState.refresh()}
          role={roleLabel(user?.role)}
          title={title}
          username={user?.username}
        />

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
