"use client";

import { useEffect, type ReactNode } from "react";

import styles from "./Inventory.module.css";

export function Dialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className={styles.backdrop}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className={styles.dialog} role="dialog" aria-modal="true">
        <div className={styles.dialogHead}>
          <h3 className={styles.dialogTitle}>{title}</h3>
          <button type="button" className={styles.btnGhost} onClick={onClose}>
            关闭
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function QtyClass(value: string | number) {
  const n = Number(value);
  if (n > 0) return styles.pos;
  if (n < 0) return styles.neg;
  return styles.zero;
}
