"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ArticleModal } from "./ArticleModal";
import styles from "./ContentDesk.module.css";
import { MachineStrip } from "./MachineStrip";
import { PublishPanel } from "./PublishPanel";
import { StepRail } from "./StepRail";
import type { IgnorePayload } from "./AuditPanel";
import {
  analyzeArticle,
  fetchOverview,
  fetchPublishPreview,
  fetchQueue,
  ignoreFinding,
  publishUnit,
  reviewArticle,
  reviseArticle,
} from "./api";
import type { Article, Overview, PublishUnit } from "./types";

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
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [units, setUnits] = useState<PublishUnit[]>([]);
  const [pageBusy, setPageBusy] = useState<string | null>(null);
  const [pageNotice, setPageNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [nextQueue, nextOverview, nextUnits] = await Promise.all([
        fetchQueue(),
        fetchOverview(),
        fetchPublishPreview(),
      ]);
      setQueue(nextQueue);
      setOverview(nextOverview);
      setUnits(nextUnits);
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  const publish = useCallback(
    async (unit: PublishUnit) => {
      const key = `${unit.source}:${unit.unit_id}`;
      setPageBusy(key);
      setError(null);
      setPageNotice(null);
      try {
        const result = await publishUnit(unit.source, unit.unit_id);
        setPageNotice(
          `已派单（${result.status}）：${result.titles.length} 篇。` +
            "n8n 会在站点上建草稿，最后一步由你在 WordPress 里点发布。",
        );
        await reload();
      } catch (publishError) {
        setError((publishError as Error).message);
      } finally {
        setPageBusy(null);
      }
    },
    [reload],
  );

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

  /** 用响应的**完整 DTO 整体替换**当前条，不做字段级 merge——
   *  GEO 老 review 端点返回裸 UUID 的 product labels，merge 会把 SKU 变 UUID。 */
  const replaceCurrent = useCallback((article: Article) => {
    setQueue((rows) =>
      rows
        ? rows.map((row) =>
            row.id === article.id && row.source === article.source ? article : row,
          )
        : rows,
    );
  }, []);

  const run = useCallback(
    async (tag: string, action: () => Promise<Article>, done?: string) => {
      setBusy(tag);
      setError(null);
      setNotice(null);
      try {
        replaceCurrent(await action());
        if (done) setNotice(done);
        return true;
      } catch (actionError) {
        setError((actionError as Error).message);
        return false;
      } finally {
        setBusy(null);
      }
    },
    [replaceCurrent],
  );

  const approveAndAdvance = useCallback(async () => {
    if (!current) return;
    const ok = await run("approve", () =>
      reviewArticle(current.source, current.id, "approved"),
    );
    if (!ok) return;
    // 批准完直接跳下一篇——8 篇要能一口气过完，不回列表。
    if ((index ?? 0) + 1 < total) {
      setIndex((value) => (value === null ? null : value + 1));
    } else {
      setIndex(null);
      await reload();
    }
  }, [current, index, reload, run, total]);

  return (
    <div className={styles.stack}>
      {error ? <div className={`${styles.card} ${styles.error}`}>{error}</div> : null}
      {pageNotice ? (
        <div className={`${styles.card} ${styles.notice}`}>{pageNotice}</div>
      ) : null}

      {overview ? <StepRail steps={overview.steps} /> : null}

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

      <PublishPanel busy={pageBusy} onPublish={(u) => void publish(u)} units={units} />

      {overview ? <MachineStrip lanes={overview.machine} /> : null}

      <div className={styles.sectionLabel}>要调细节</div>
      <div className={styles.card}>
        <span className={styles.empty}>
          选题、生成、事实库、阵地监测这些在两个引擎页面里：
          <a href="/geo" style={{ color: "#d9a441" }}>GEO 内容引擎</a>
          {" · "}
          <a href="/seo" style={{ color: "#d9a441" }}>SEO 内容引擎</a>
          。平时不用开。
        </span>
      </div>

      {current ? (
        <ArticleModal
          action={{
            busy,
            onAnalyze: () =>
              void run(
                "analyze",
                () => analyzeArticle(current.source, current.id),
                "解读好了。",
              ),
            onApprove: () => void approveAndAdvance(),
            onReject: () =>
              void run(
                "reject",
                () => reviewArticle(current.source, current.id, "rejected"),
                "已驳回。",
              ),
            onRevise: () =>
              void run(
                "revise",
                () => reviseArticle(current.source, current.id),
                "已按批评重写——改不了的会在下面如实说明。",
              ),
            onToggleIgnore: (payload: IgnorePayload, ignored: boolean) =>
              void run(
                "ignore",
                () =>
                  ignoreFinding(
                    current.source,
                    current.id,
                    payload as unknown as Record<string, unknown>,
                    ignored,
                  ),
                ignored ? "已放行这一条。" : "已撤销放行。",
              ),
          }}
          article={current}
          error={error}
          index={index ?? 0}
          notice={notice}
          onClose={closeModal}
          onNext={goNext}
          onPrev={goPrev}
          total={total}
        />
      ) : null}
    </div>
  );
}
