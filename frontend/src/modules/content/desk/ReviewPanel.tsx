"use client";

import styles from "./ContentDesk.module.css";
import type { Article } from "./types";

/** 第③步：待审队列。一行一个来源，点开就进浮窗连着过完。 */
export function ReviewPanel({
  queue,
  onOpen,
}: {
  queue: Article[] | null;
  onOpen: (index: number) => void;
}) {
  if (queue === null) {
    return (
      <div className={styles.card}>
        <span className={styles.empty}>读取中…</span>
      </div>
    );
  }
  if (!queue.length) {
    return (
      <div className={styles.card}>
        <span className={styles.empty}>
          都审完了。机器写完新的会出现在这里。
        </span>
      </div>
    );
  }
  const groups = new Map<string, Article[]>();
  for (const article of queue) {
    groups.set(article.source, [...(groups.get(article.source) ?? []), article]);
  }
  return (
    <>
      {[...groups.entries()].map(([source, articles]) => (
        <div
          className={`${styles.card} ${styles.todoRow} ${styles.actionable}`}
          key={source}
        >
          <span className={styles.bead} />
          <div className={styles.todoMain}>
            <div className={styles.todoLead}>
              {articles.length} 篇{articles[0].source_label}等你审
            </div>
            <div className={styles.todoNote}>
              {articles.slice(0, 2).map((a) => a.title).join(" · ")}
              {articles.length > 2 ? " …" : ""}
            </div>
          </div>
          <span className={styles.count}>{articles.length}</span>
          <button
            className={styles.btn}
            onClick={() => onOpen(queue.findIndex((a) => a.source === source))}
            type="button"
          >
            打开第一篇
          </button>
        </div>
      ))}
    </>
  );
}
