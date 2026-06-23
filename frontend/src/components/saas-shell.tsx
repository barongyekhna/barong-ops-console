"use client";

import { LogOut, Menu, RefreshCcw, Search } from "lucide-react";

import { Logo } from "@/components/brand-logo";
import { CapabilitySidebarEngine } from "@/components/capability-sidebar-engine";

type SidebarProps = {
  isOpen: boolean;
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
        <div>
          <span className="eyebrow">Workspace</span>
          <h1>{title}</h1>
        </div>
      </div>

      <div className="topbar-tools">
        <label className="topbar-search">
          <Search aria-hidden="true" size={16} />
          <input aria-label="搜索工作台" placeholder="Search modules" type="search" />
        </label>

        <button className="secondary-button topbar-action" onClick={onRefresh} type="button">
          <RefreshCcw aria-hidden="true" size={16} />
          Refresh
        </button>

        <div className="account-area">
          <div className="account-copy">
            <strong>{username}</strong>
            <span>{role}</span>
          </div>
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
