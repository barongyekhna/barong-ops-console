"use client";

import styles from "./ContentDesk.module.css";
import type { Step } from "./types";

/**
 * 四步导轨。**卡在哪一步是后端算出来的**（从①往④第一个有待办的），
 * 不是前端手画的——手画的迟早和真实状态对不上。
 *
 * 每一步下面标「谁干」：用户原话「我经常不知道自己下一步该干嘛了」，
 * 那句话的一半答案是「这一步根本不用你干」。
 */
export function StepRail({ steps }: { steps: Step[] }) {
  return (
    <div className={styles.rail}>
      {steps.map((step, i) => (
        <div
          className={`${styles.step}${step.here ? ` ${styles.stepHere}` : ""}${
            step.done ? ` ${styles.stepDone}` : ""
          }`}
          key={step.key}
        >
          <div className={styles.stepIndex}>{String(i + 1).padStart(2, "0")}</div>
          <div className={styles.stepTitle}>{step.title}</div>
          <div className={styles.stepValue}>{step.value}</div>
          <div className={styles.stepWho}>{step.who}</div>
        </div>
      ))}
    </div>
  );
}
