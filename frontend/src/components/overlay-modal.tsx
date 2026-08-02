"use client";

import { useCallback, useEffect, useRef } from "react";
import type { MouseEvent as ReactMouseEvent, ReactNode } from "react";
import { createPortal } from "react-dom";

import styles from "./overlay-modal.module.css";

/**
 * 通用浮窗。仓库里原本一个都没有 —— 四处各造一半的轮子：
 *
 * - `modules/notifications/NotificationOverlay.tsx` 行为最全（portal / focus trap /
 *   双层滚动锁 / Esc / 恢复焦点），但视觉是通知专用的
 * - `modules/r/analysis/DetailModal.tsx` 视觉可复用，但**没有** portal、
 *   没有 focus trap、没有滚动锁、没有 Esc
 * - ImageSystem 和 K 各自还有两份
 *
 * 这里把两边合起来。本次**不去重构那四处** —— 无关的爆炸半径，另开单。
 */

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function focusableElements(container: HTMLElement) {
  return Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter((element) => element.getAttribute("aria-hidden") !== "true");
}

/** 焦点在输入控件里时，方向键属于光标，不属于浮窗。 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export type OverlayModalProps = {
  /** 必须用 useCallback 包住。它进 effect 依赖，每次 render 换新引用会重挂
   *  effect —— 那时滚动条已经锁上了，scrollbarWidth 会算成 0，padding 补偿出错。 */
  onClose: () => void;
  label: string;
  children: ReactNode;
  /** 默认 min(860px,100%)。整篇文章 + 全部审阅信息要更宽。 */
  width?: string;
  /** 额外的键盘处理（比如 ←/→ 翻页）。返回 true 表示已消费，浮窗不再处理。 */
  onKeyDown?: (event: KeyboardEvent) => boolean | void;
};

export function OverlayModal({
  onClose,
  label,
  children,
  width,
  onKeyDown,
}: OverlayModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  // onKeyDown 放 ref：让它不进下面那个 effect 的依赖，避免调用方忘了
  // useCallback 就把滚动锁重挂一遍。
  const extraKeyRef = useRef(onKeyDown);
  extraKeyRef.current = onKeyDown;

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
    // html 也要锁，否则 iOS/Safari 背景照样能滚。
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

      if (extraKeyRef.current?.(event) === true) return;

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

    // 捕获阶段：抢在页面级快捷键之前。
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

  const handleBackdropClick = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      if (event.target === event.currentTarget) onClose();
    },
    [onClose],
  );

  if (typeof document === "undefined") return null;

  return createPortal(
    <div className={styles.overlay} onClick={handleBackdropClick} role="presentation">
      <div
        aria-label={label}
        aria-modal="true"
        className={styles.modal}
        ref={dialogRef}
        role="dialog"
        style={width ? { width } : undefined}
        tabIndex={-1}
      >
        <button
          aria-label="关闭"
          className={styles.closeButton}
          onClick={onClose}
          type="button"
        >
          ×
        </button>
        {children}
      </div>
    </div>,
    document.body,
  );
}
