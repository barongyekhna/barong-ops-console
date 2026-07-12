"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getC19UnreadSummary } from "./api";

const C19_UNREAD_POLL_INTERVAL_MS = 30_000;

export const C19_UNREAD_CHANGED_EVENT = "barong:c19-unread-changed";

export function announceC19UnreadChanged() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(C19_UNREAD_CHANGED_EVENT));
  }
}

export function normalizeC19UnreadCount(value: number) {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.floor(value);
}

async function readC19UnreadCount(signal: AbortSignal) {
  const summary = await getC19UnreadSummary(signal);
  if (
    !Number.isSafeInteger(summary.total_unread_count) ||
    summary.total_unread_count < 0 ||
    !Number.isSafeInteger(summary.unread_conversation_count) ||
    summary.unread_conversation_count < 0
  ) {
    throw new Error("C19 unread summary response is invalid.");
  }
  return normalizeC19UnreadCount(summary.total_unread_count);
}

export function useC19UnreadCount(enabled = true) {
  const [unreadCount, setUnreadCount] = useState(0);
  const activeControllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(() => {
    activeControllerRef.current?.abort();
    const controller = new AbortController();
    activeControllerRef.current = controller;
    void readC19UnreadCount(controller.signal)
      .then((count) => {
        if (!controller.signal.aborted) setUnreadCount(count);
      })
      .catch(() => {
        // Navigation remains usable when the optional unread hint is unavailable.
      });
  }, []);

  useEffect(() => {
    if (!enabled) {
      activeControllerRef.current?.abort();
      setUnreadCount(0);
      return;
    }
    refresh();
    const onVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    const interval = window.setInterval(refresh, C19_UNREAD_POLL_INTERVAL_MS);
    window.addEventListener("focus", refresh);
    window.addEventListener(C19_UNREAD_CHANGED_EVENT, refresh);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      activeControllerRef.current?.abort();
      window.clearInterval(interval);
      window.removeEventListener("focus", refresh);
      window.removeEventListener(C19_UNREAD_CHANGED_EVENT, refresh);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, refresh]);

  return unreadCount;
}
