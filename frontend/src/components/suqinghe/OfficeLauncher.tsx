"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";

import styles from "./Office.module.css";
import { OfficeWindow } from "./OfficeWindow";
import { AVATAR_SRC, STATE_LABEL, getOffice, type OfficeRead } from "./office-api";

const CLOSED_POLL_MS = 30_000;
const OPEN_POLL_MS = 5_000;

/**
 * 苏青禾的办公室入口:右下角头像 + 状态点。不进侧边栏。
 * 谁都能打开看她干活;能不能指挥她由后端返回的 can_command 决定(真正的闸在后端 require_owner)。
 * 状态点只反映后端按真实心跳算出来的状态,前端不编造。
 */
export function OfficeLauncher() {
  const { status, user } = useAuth();
  const [office, setOffice] = useState<OfficeRead | null>(null);
  const [open, setOpen] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const inFlight = useRef(false);

  const isBot =
    Boolean((user as { is_bot?: boolean } | null)?.is_bot) || user?.username === "suqinghe";
  const enabled = status === "authenticated" && Boolean(user) && !isBot;

  const refresh = useCallback(async () => {
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;
    try {
      const next = await getOffice();
      setOffice(next);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "办公室加载失败");
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    void refresh();
    const interval = window.setInterval(
      () => {
        if (typeof document !== "undefined" && document.hidden) {
          return;
        }
        void refresh();
      },
      open ? OPEN_POLL_MS : CLOSED_POLL_MS,
    );
    return () => window.clearInterval(interval);
  }, [enabled, open, refresh]);

  const close = useCallback(() => setOpen(false), []);

  if (!enabled) {
    return null;
  }

  const state = office?.state ?? "offline";
  const pending = office?.can_command ? office.today.cards_pending : 0;
  const label = office ? `苏青禾 · ${STATE_LABEL[state]}${office.paused ? " · 已暂停" : ""}` : "苏青禾的办公室";

  return (
    <>
      <button
        aria-expanded={open}
        aria-label={`${label}，打开她的办公室`}
        className={styles.launcher}
        data-state={state}
        onClick={() => setOpen((value) => !value)}
        title={label}
        type="button"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img alt="" className={styles.launcherAvatar} height={52} src={AVATAR_SRC} width={52} />
        <span aria-hidden className={styles.launcherDot} data-state={state} />
        {pending > 0 ? <span className={styles.launcherBadge}>{pending > 99 ? "99+" : pending}</span> : null}
      </button>
      {open ? (
        <OfficeWindow loadError={loadError} office={office} onChanged={refresh} onClose={close} />
      ) : null}
    </>
  );
}
