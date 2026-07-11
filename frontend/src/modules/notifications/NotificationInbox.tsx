"use client";

import {
  AlertTriangle,
  BellRing,
  CheckCheck,
  Circle,
  ExternalLink,
  Inbox,
  LoaderCircle,
  Radio,
  RotateCcw,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { DashboardScene } from "@/components/dashboard-scene";

import {
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from "./api";
import styles from "./NotificationInbox.module.css";

type Filter = "all" | "unread";
type NotificationInboxProps = {
  onClose?: () => void;
  onUnreadChange?: (unread: number) => void;
  variant?: "overlay" | "page";
};

const LEVEL_LABEL: Record<string, string> = {
  info: "信息",
  success: "成功",
  warning: "警告",
  error: "错误",
};

const POLL_MS = 30000;
const RETURN_PATH_STORAGE_KEY = "barong.notifications.return-path";

function safeReturnPath(value: string | null) {
  if (
    !value ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value === "/notifications" ||
    value.startsWith("/notifications?") ||
    value.startsWith("/notifications#")
  ) {
    return null;
  }
  return value;
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function externalLinks(refs: Record<string, unknown> | null) {
  if (!refs) {
    return [] as Array<{ label: string; value: string; href?: string }>;
  }
  const out: Array<{ label: string; value: string; href?: string }> = [];
  for (const [key, raw] of Object.entries(refs)) {
    if (raw == null) continue;
    const value = String(raw);
    const isUrl = /^https?:\/\//i.test(value);
    out.push({ label: key, value, href: isUrl ? value : undefined });
  }
  return out;
}

export function NotificationInbox({
  onClose,
  onUnreadChange,
  variant = "page",
}: NotificationInboxProps = {}) {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [markingAll, setMarkingAll] = useState(false);
  const mounted = useRef(true);

  const load = useCallback(async (which: Filter) => {
    setLoading(true);
    setError("");
    try {
      const result = await getNotifications({
        status: which === "unread" ? "unread" : undefined,
        limit: 100,
      });
      if (!mounted.current) return;
      setItems(result.items);
      setUnread(result.unread);
      onUnreadChange?.(result.unread);
    } catch (err) {
      if (!mounted.current) return;
      setError(err instanceof Error ? err.message : "通知加载失败。");
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [onUnreadChange]);

  useEffect(() => {
    mounted.current = true;
    void load(filter);
    return () => {
      mounted.current = false;
    };
  }, [filter, load]);

  // Lightweight background poll so the unread badge stays fresh.
  useEffect(() => {
    const id = window.setInterval(() => {
      void load(filter);
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [filter, load]);

  async function handleMarkRead(id: number) {
    setBusyId(id);
    try {
      await markNotificationRead(id);
      await load(filter);
    } catch (err) {
      setError(err instanceof Error ? err.message : "标记已读失败。");
    } finally {
      setBusyId(null);
    }
  }

  async function handleMarkAll() {
    setMarkingAll(true);
    try {
      await markAllNotificationsRead();
      await load(filter);
    } catch (err) {
      setError(err instanceof Error ? err.message : "全部已读失败。");
    } finally {
      setMarkingAll(false);
    }
  }

  function handleClose() {
    if (onClose) {
      onClose();
      return;
    }
    let returnPath: string | null = null;
    try {
      returnPath = safeReturnPath(
        window.sessionStorage.getItem(RETURN_PATH_STORAGE_KEY),
      );
      window.sessionStorage.removeItem(RETURN_PATH_STORAGE_KEY);
    } catch {
      // Fall through to a deterministic in-console destination.
    }
    window.location.replace(returnPath ?? "/dashboard");
  }

  const closeLabel = onClose ? "关闭通知浮层" : "关闭通知并返回";

  return (
    <section
      className={`${styles.inbox} ${variant === "overlay" ? styles.inboxOverlay : ""} cc-dash`}
      aria-label="通知收件箱"
    >
      <DashboardScene />
      <div className={styles.content}>
        <button
          aria-label={closeLabel}
          className={styles.closeButton}
          onClick={handleClose}
          title={closeLabel}
          type="button"
        >
          <X aria-hidden="true" size={19} />
        </button>

        <header className={styles.header}>
          <div className={styles.heading}>
            <span className={styles.eyebrow}>
              <Radio aria-hidden="true" size={14} />
              PHOENIX SIGNAL DECK / LIVE
            </span>
            <h2>
              <BellRing aria-hidden="true" size={21} />
              通知驾驶舱
              {unread > 0 ? (
                <span className={styles.unreadBadge}>{unread}</span>
              ) : null}
            </h2>
            <p>系统信号 · {unread} 条未读 · 30 秒同步</p>
          </div>
          <div className={styles.headerActions}>
            <button
              className={styles.secondaryAction}
              disabled={loading}
              onClick={() => void load(filter)}
              type="button"
            >
              {loading ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <RotateCcw aria-hidden="true" size={16} />
              )}
              刷新
            </button>
            <button
              className={styles.primaryAction}
              disabled={markingAll || unread === 0}
              onClick={() => void handleMarkAll()}
              type="button"
            >
              {markingAll ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <CheckCheck aria-hidden="true" size={16} />
              )}
              全部已读
            </button>
          </div>
        </header>

        <div className={styles.commandBar}>
          <div className={styles.filters} role="tablist" aria-label="通知筛选">
            <button
              aria-selected={filter === "all"}
              className={filter === "all" ? styles.filterActive : styles.filter}
              onClick={() => setFilter("all")}
              role="tab"
              type="button"
            >
              <Inbox aria-hidden="true" size={14} />
              全部
            </button>
            <button
              aria-selected={filter === "unread"}
              className={filter === "unread" ? styles.filterActive : styles.filter}
              onClick={() => setFilter("unread")}
              role="tab"
              type="button"
            >
              <Radio aria-hidden="true" size={14} />
              未读{unread > 0 ? ` · ${unread}` : ""}
            </button>
          </div>
          <span className={styles.channelStatus}>
            <span aria-hidden="true" className={styles.liveDot} />
            SIGNAL CHANNEL ONLINE
          </span>
        </div>

        {error ? (
          <p className={styles.error} role="alert">
            <AlertTriangle aria-hidden="true" size={16} />
            {error}
          </p>
        ) : null}

        {loading && items.length === 0 ? (
          <div className={styles.state}>
            <LoaderCircle aria-hidden="true" className="spin" size={22} />
            <span>正在加载通知…</span>
          </div>
        ) : null}

        {!loading && items.length === 0 && !error ? (
          <div className={styles.state}>
            <Inbox aria-hidden="true" size={22} />
            <span>{filter === "unread" ? "没有未读通知。" : "暂无通知。"}</span>
          </div>
        ) : null}

        <ul className={styles.list}>
        {items.map((item) => {
          const links = externalLinks(item.external_refs);
          const isUnread = item.status === "unread";
          return (
            <li
              className={`${styles.item} ${isUnread ? styles.itemUnread : ""}`}
              data-level={item.level}
              key={item.id}
            >
              <span
                aria-hidden="true"
                className={styles.levelDot}
                data-level={item.level}
              >
                <Circle size={10} />
              </span>
              <div className={styles.body}>
                <div className={styles.itemTop}>
                  <strong className={styles.title}>{item.title}</strong>
                  <span className={styles.meta}>
                    <span className={styles.levelTag} data-level={item.level}>
                      {LEVEL_LABEL[item.level] ?? item.level}
                    </span>
                    <span className={styles.source}>{item.source}</span>
                    <time>{formatTime(item.created_at)}</time>
                  </span>
                </div>
                {item.body ? <p className={styles.text}>{item.body}</p> : null}
                {links.length > 0 ? (
                  <div className={styles.refs}>
                    {links.map((link) => (
                      <span className={styles.ref} key={`${item.id}-${link.label}`}>
                        <span className={styles.refKey}>{link.label}:</span>
                        {link.href ? (
                          <a href={link.href} rel="noreferrer" target="_blank">
                            {link.value}
                            <ExternalLink aria-hidden="true" size={12} />
                          </a>
                        ) : (
                          <span className={styles.refVal}>{link.value}</span>
                        )}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              {isUnread ? (
                <button
                  className={styles.markButton}
                  disabled={busyId === item.id}
                  onClick={() => void handleMarkRead(item.id)}
                  type="button"
                >
                  {busyId === item.id ? (
                    <LoaderCircle aria-hidden="true" className="spin" size={14} />
                  ) : (
                    "标记已读"
                  )}
                </button>
              ) : (
                <span className={styles.readTag}>已读</span>
              )}
            </li>
          );
        })}
        </ul>
      </div>
    </section>
  );
}
