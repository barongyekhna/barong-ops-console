"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ArticleModal } from "./ArticleModal";
import styles from "./ContentDesk.module.css";
import { fetchQueue } from "./api";
import type { Article } from "./types";

/**
 * 内容台。**不是第三台引擎**——不生成内容、不发明状态，只把 GEO/SEO 合成一页：
 * 现在卡在哪一步、该你做什么、机器有没有在跑。
 *
 * 步 2 只做「读」：队列 + 浮窗。审阅动作在步 3，四步导轨与绿条在步 5。
 */
export function ContentDesk() {
  const [queue, setQueue] = useState<Article[] | null>(null);
  const [index, setIndex] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setQueue(await fetchQueue());
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  // OverlayModal 的 onClose 进 effect 依赖，必须 useCallback——
  // 否则每次 render 都重挂滚动锁，scrollbarWidth 会算成 0 把 padding 弄错。
  const closeModal = useCallback(() => setIndex(null), []);
  const total = queue?.length ?? 0;

  const goPrev = useCallback(() => {
    setIndex((current) =>
      current === null ? null : (current - 1 + total) % Math.max(total, 1),
    );
  }, [total]);

  const goNext = useCallback(() => {
    setIndex((current) =>
      current === null ? null : (current + 1) % Math.max(total, 1),
    );
  }, [total]);

  const bySource = useMemo(() => {
    const groups = new Map<string, Article[]>();
    for (const article of queue ?? []) {
      groups.set(article.source, [...(groups.get(article.source) ?? []), article]);
    }
    return [...groups.entries()];
  }, [queue]);

  const current = index !== null ? (queue?.[index] ?? null) : null;

  return (
    <div className={styles.stack}>
      {error ? <div className={`${styles.card} ${styles.error}`}>{error}</div> : null}

      <div className={styles.sectionLabel}>现在该你做的</div>

      {queue === null ? (
        <div className={styles.card}>
          <span className={styles.empty}>读取中…</span>
        </div>
      ) : total === 0 ? (
        <div className={styles.card}>
          <span className={styles.empty}>没有待办。机器写完了会出现在这里。</span>
        </div>
      ) : (
        bySource.map(([source, articles]) => {
          const first = queue.findIndex((a) => a.source === source);
          return (
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
                  {articles
                    .slice(0, 2)
                    .map((a) => a.title)
                    .join(" · ")}
                  {articles.length > 2 ? " …" : ""}
                </div>
              </div>
              <span className={styles.count}>{articles.length}</span>
              <button
                className={styles.btn}
                onClick={() => setIndex(first)}
                type="button"
              >
                打开第一篇
              </button>
            </div>
          );
        })
      )}

      {current ? (
        <ArticleModal
          action={{
            busy: null,
            onAnalyze: () => undefined,
            onApprove: () => undefined,
            onReject: () => undefined,
            onRevise: () => undefined,
            onToggleIgnore: () => undefined,
          }}
          article={current}
          error={null}
          index={index ?? 0}
          notice="步 2 只做「读」——批准、重写、放行下一步接上。"
          onClose={closeModal}
          onNext={goNext}
          onPrev={goPrev}
          total={total}
        />
      ) : null}
    </div>
  );
}
