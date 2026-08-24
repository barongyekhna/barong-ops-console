"use client";

import { LogOut, Menu, RefreshCcw, Search, Settings, X } from "lucide-react";
import Link from "next/link";

import { Logo } from "@/components/brand-logo";
import { CapabilitySidebarEngine } from "@/components/capability-sidebar-engine";
import { formatDisplayName, useProfile } from "@/components/profile-provider";
import { NotificationBell } from "@/modules/notifications/NotificationBell";

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
            {/* L1 (QA 2026-08-22): removed the internal release-version badge
                (e.g. "C-SERIES-V1.1.0") from the top bar — it's an internal
                codename with no meaning to end users. */}
            <h1>{title}</h1>
          </div>
        </div>
      </div>

      <div className="topbar-tools">
        <label className="topbar-search">
          <Search aria-hidden="true" size={16} />
          <input aria-label="搜索工作台" placeholder="搜索模块" type="search" />
        </label>

        <NotificationBell />

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
