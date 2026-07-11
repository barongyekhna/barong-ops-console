"use client";

import { Bell } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getUnreadCount } from "./api";
import { NotificationOverlay } from "./NotificationOverlay";

const POLL_MS = 30000;

export function NotificationBell() {
  const [unread, setUnread] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const handleClose = useCallback(() => setIsOpen(false), []);

  useEffect(() => {
    if (isOpen) {
      return;
    }
    let active = true;
    const load = async () => {
      try {
        const count = await getUnreadCount();
        if (active) setUnread(count);
      } catch {
        // best-effort; leave last known count
      }
    };
    void load();
    const id = window.setInterval(load, POLL_MS);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [isOpen]);

  return (
    <>
      <button
        aria-controls="notification-overlay-dialog"
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label={unread > 0 ? `通知收件箱，${unread} 条未读` : "通知收件箱"}
        className="secondary-button topbar-action notif-bell"
        onClick={() => setIsOpen(true)}
        title="通知收件箱"
        type="button"
      >
        <Bell aria-hidden="true" size={16} />
        通知
        {unread > 0 ? (
          <span className="notif-badge">{unread > 99 ? "99+" : unread}</span>
        ) : null}
      </button>
      {isOpen ? (
        <NotificationOverlay
          onClose={handleClose}
          onUnreadChange={setUnread}
        />
      ) : null}
    </>
  );
}
