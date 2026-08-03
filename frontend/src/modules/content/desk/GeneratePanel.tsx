"use client";

import styles from "./ContentDesk.module.css";
import type { Todo, TopicState } from "./types";

/**
 * 第②步：派生成。
 *
 * 生成失败的任务也归这一步——「修好的东西一直红着，比不显示更糟」，所以
 * 这里只列**还没被后来的成功盖过**的失败（后端已经算好了）。
 */
export function GeneratePanel({
  state,
  failures,
  busy,
  onGenerate,
}: {
  state: TopicState;
  failures: Todo[];
  busy: string | null;
  onGenerate: (ids: string[]) => void;
}) {
  const awaiting = state.awaiting_generation;
  if (!awaiting.length && !failures.length) {
    return (
      <div className={styles.card}>
        <span className={styles.empty}>
          没有等着写的。去「选题」挑几条，挑中的会出现在这里。
        </span>
      </div>
    );
  }
  return (
    <>
      {awaiting.length ? (
        <div className={`${styles.card} ${styles.todoRow} ${styles.actionable}`}>
          <span className={styles.bead} />
          <div className={styles.todoMain}>
            <div className={styles.todoLead}>
              {awaiting.length} 个选题已挑中，还没写
            </div>
            <div className={styles.todoNote}>
              {awaiting.slice(0, 4).map((t) => t.keyword).join(" · ")}
              {awaiting.length > 4 ? " …" : ""}
              　AI 写一篇一分钟起步，写完会出现在「你审」。
            </div>
          </div>
          <span className={styles.count}>{awaiting.length}</span>
          <button
            className={styles.btn}
            disabled={busy !== null}
            onClick={() => onGenerate(awaiting.map((t) => t.id))}
            type="button"
          >
            {busy === "generate" ? "派单中…" : "全部生成"}
          </button>
        </div>
      ) : null}

      {failures.map((todo) => (
        <div className={`${styles.card} ${styles.error}`} key={todo.lead}>
          <div className={styles.todoLead}>{todo.lead}</div>
          <div className={styles.todoNote}>
            {todo.note}　—— 去 GEO / SEO 引擎页面看完整报错。
          </div>
        </div>
      ))}
    </>
  );
}
