"use client";

import { LogOut, Menu, RefreshCcw, Search, Settings, X } from "lucide-react";
import Link from "next/link";

import { Logo } from "@/components/brand-logo";
import { CapabilitySidebarEngine } from "@/components/capability-sidebar-engine";
import { formatDisplayName, useProfile } from "@/components/profile-provider";
import { NotificationBell } from "@/modules/notifications/NotificationBell";

import { ReleaseNotesButton } from "./release-notes-button";
import { OrgSwitcher } from "./org-switcher";

import styles from "./saas-shell.module.css";

type SidebarProps = {
  isOpen: boolean;
  onClose: () => void;
  onLogoClick: () => void;
  onNavigate: () => void;
  pathname: string;
};

type TopHeaderProps = {
  isActionPending: boolean;
  onLogout: () => void;
  onMenuToggle: () => void;
  onRefresh: () => void;
  role: string;
  title: string;
  username?: string | null;
};

export function Sidebar({
  isOpen,
  onClose,
  onLogoClick,
  onNavigate,
  pathname,
}: SidebarProps) {
  return (
    <aside className={`sidebar ${isOpen ? "sidebar-open" : ""}`}>
      <button
        aria-label="返回首页"
        className="brand-lockup brand-home-button"
        onClick={onLogoClick}
        title="返回首页"
        type="button"
      >
        <span className="brand-mark">
          <Logo decorative />
        </span>
        <span>
          <strong>Barong</strong>
          <small>Operations</small>
        </span>
      </button>

      <button
        aria-label="收起导航"
        className="sidebar-close"
        onClick={onClose}
        title="收起导航"
        type="button"
      >
        <X aria-hidden="true" size={18} />
      </button>

      <CapabilitySidebarEngine onNavigate={onNavigate} pathname={pathname} />
    </aside>
  );
}

export function TopHeader({
  isActionPending,
  onLogout,
  onMenuToggle,
  onRefresh,
  role,
  title,
  username,
}: TopHeaderProps) {
  const { profile } = useProfile();
  const realName = profile?.display_name || username || "";
  const shownName = formatDisplayName(profile?.nickname, realName || (username ?? "—"));
  const avatarUrl = profile?.avatar_url ?? null;
  const initial = (realName || username || "?").slice(0, 1).toUpperCase();
  return (
    <header className="topbar">
      <div className="topbar-title">
        <button
          aria-label="打开或收起导航"
          className="icon-button menu-button"
          onClick={onMenuToggle}
          title="打开或收起导航"
          type="button"
        >
          <Menu aria-hidden="true" size={20} />
        </button>
        <span className="brand-mark topbar-brand-mark">
          <Logo decorative />
        </span>
        <div className="topbar-heading-copy">
          <span className="eyebrow">工作台</span>
          <div className="topbar-title-row">
            {/* L1 (QA 2026-08-22) 曾把版本徽章从这里删掉，理由是
                "C-SERIES-V1.1.0" 是内部代号、对使用者没有意义 —— 那个理由成立。
                2026-09-02 版本号改成 2.0.0（不再是代号），并且做成了
                「版本更新」抽屉的入口，所以版本号回到了顶栏，
                但位置在右侧工具区（见 ReleaseNotesButton），不再挤在标题旁边。 */}
            <h1>{title}</h1>
          </div>
        </div>
      </div>

      <div className="topbar-tools">
        {/* 组织切换器：只在账号属于 ≥2 个组织时出现。
            放这里而不是侧边栏 —— 侧边栏那棵「组织」树是模块分组导航，
            不是身份切换，两件事放一起会让人以为点树就切换了。 */}
        <OrgSwitcher />

        <label className="topbar-search">
          <Search aria-hidden="true" size={16} />
          <input aria-label="搜索工作台" placeholder="搜索模块" type="search" />
        </label>

        <NotificationBell />

        {/* 版本号按钮：点开是「版本更新」抽屉。
            按钮上直接显示版本号，所以它同时是「现在是哪一版」和
            「这一版改了什么」两件事的答案。 */}
        <ReleaseNotesButton />

        <button className="secondary-button topbar-action" onClick={onRefresh} type="button">
          <RefreshCcw aria-hidden="true" size={16} />
          刷新
        </button>

        <div className="account-area">
          <span className={styles.avatar} aria-hidden="true">
            {avatarUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={avatarUrl} alt="" />
            ) : (
              <span className={styles.avatarInitial}>{initial}</span>
            )}
          </span>
          <div className="account-copy">
            <strong>{shownName}</strong>
            <span>{role}</span>
          </div>
          <Link
            href="/settings"
            className={styles.gear}
            title="设置"
            aria-label="设置"
          >
            <Settings aria-hidden="true" size={17} />
          </Link>
          <button
            className="logout-button"
            disabled={isActionPending}
            onClick={onLogout}
            type="button"
          >
            <LogOut aria-hidden="true" size={17} />
            {isActionPending ? "退出中" : "退出"}
          </button>
        </div>
      </div>
    </header>
  );
}
