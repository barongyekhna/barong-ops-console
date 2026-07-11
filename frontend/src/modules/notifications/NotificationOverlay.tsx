"use client";

import { createPortal } from "react-dom";
import {
  useEffect,
  useRef,
  type MouseEvent as ReactMouseEvent,
} from "react";

import { NotificationInbox } from "./NotificationInbox";
import styles from "./NotificationOverlay.module.css";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

type NotificationOverlayProps = {
  onClose: () => void;
  onUnreadChange: (unread: number) => void;
};

function focusableElements(container: HTMLElement) {
  return Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter((element) => element.getAttribute("aria-hidden") !== "true");
}

export function NotificationOverlay({
  onClose,
  onUnreadChange,
}: NotificationOverlayProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const body = document.body;
    const root = document.documentElement;
    const previouslyFocused =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const previousBodyOverflow = body.style.overflow;
    const previousBodyPaddingRight = body.style.paddingRight;
    const previousRootOverflow = root.style.overflow;
    const scrollbarWidth = window.innerWidth - root.clientWidth;

    if (scrollbarWidth > 0) {
      const currentPadding = Number.parseFloat(
        window.getComputedStyle(body).paddingRight,
      );
      body.style.paddingRight = `${currentPadding + scrollbarWidth}px`;
    }
    body.style.overflow = "hidden";
    root.style.overflow = "hidden";

    const focusTimer = window.setTimeout(() => {
      const dialog = dialogRef.current;
      const firstTarget = dialog ? focusableElements(dialog)[0] : null;
      (firstTarget ?? dialog)?.focus({ preventScroll: true });
    }, 0);

    const handleKeyDown = (event: KeyboardEvent) => {
      const dialog = dialogRef.current;
      if (!dialog) return;

      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      const targets = focusableElements(dialog);
      if (targets.length === 0) {
        event.preventDefault();
        dialog.focus({ preventScroll: true });
        return;
      }

      const first = targets[0];
      const last = targets[targets.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown, true);
      body.style.overflow = previousBodyOverflow;
      body.style.paddingRight = previousBodyPaddingRight;
      root.style.overflow = previousRootOverflow;
      if (previouslyFocused?.isConnected) {
        previouslyFocused.focus({ preventScroll: true });
      }
    };
  }, [onClose]);

  function handleBackdropClick(event: ReactMouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) {
      onClose();
    }
  }

  if (typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div className={styles.backdrop} onClick={handleBackdropClick}>
      <div
        aria-label="通知驾驶舱"
        aria-modal="true"
        className={styles.dialog}
        id="notification-overlay-dialog"
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        <NotificationInbox
          onClose={onClose}
          onUnreadChange={onUnreadChange}
          variant="overlay"
        />
      </div>
    </div>,
    document.body,
  );
}
