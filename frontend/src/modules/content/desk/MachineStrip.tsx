"use client";

import styles from "./ContentDesk.module.css";
import type { MachineLane } from "./types";

/**
 * 机器自己在跑的。**零按钮**——只给你看一眼「没事」。
 *
 * 要处理就去 GEO/SEO 老页面。在这里加按钮，等于把那 39 个按钮又搬一部分回来，
 * 而这一页存在的全部理由就是别让你面对那 39 个。
 */
export function MachineStrip({ lanes }: { lanes: MachineLane[] }) {
  if (!lanes.length) return null;
  const anyBad = lanes.some((lane) => !lane.ok);
  return (
    <>
      <div className={styles.sectionLabel}>机器自己在跑的（不用管）</div>
      <div className={`${styles.machine}${anyBad ? ` ${styles.machineWarn}` : ""}`}>
        {lanes.map((lane) => (
          <span key={lane.key}>
            <span className={lane.ok ? styles.ok : styles.warn}>
              {lane.ok ? "✓" : "!"}
            </span>{" "}
            {lane.label}　{lane.text}
          </span>
        ))}
      </div>
    </>
  );
}
