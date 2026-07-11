"use client";

import { Bell } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getUnreadCount } from "./api";

const POLL_MS = 30000;
const RETURN_PATH_STORAGE_KEY = "barong.notifications.return-path";

export function NotificationBell() {
  const router = useRouter();
  const pathname = usePathname();
  const [unread, setUnread] = useState(0);

  useEffect(() => {
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
    // re-fetch when navigating (e.g. after marking read on the inbox page)
  }, [pathname]);

  function handleOpen() {
    if (pathname === "/notifications") {
      return;
    }
    try {
      const returnPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      window.sessionStorage.setItem(RETURN_PATH_STORAGE_KEY, returnPath);
    } catch {
      // Browser history remains the fallback when session storage is unavailable.
    }
    router.push("/notifications");
  }

  return (
    <button
      aria-label={unread > 0 ? `通知收件箱，${unread} 条未读` : "通知收件箱"}
      className="secondary-button topbar-action notif-bell"
      onClick={handleOpen}
      title="通知收件箱"
      type="button"
    >
      <Bell aria-hidden="true" size={16} />
      通知
      {unread > 0 ? (
        <span className="notif-badge">{unread > 99 ? "99+" : unread}</span>
      ) : null}
    </button>
  );
}
