"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ArticleModal } from "./ArticleModal";
import styles from "./ContentDesk.module.css";
import { MachineStrip } from "./MachineStrip";
import { PublishPanel } from "./PublishPanel";
import { QuestionPicker } from "./QuestionPicker";
import { TopicPanel } from "./TopicPanel";
import { StepRail } from "./StepRail";
import type { IgnorePayload } from "./AuditPanel";
import {
  analyzeArticle,
  fetchOverview,
  fetchPublishState,
  fetchTopics,
  generateCluster,
  generateTopics,
  pickTopic,
  fetchQueue,
  ignoreFinding,
  publishUnit,
  reviewArticle,
  reviseArticle,
} from "./api";
import type {
  Article,
  Overview,
  PublishState,
  PublishUnit,
  TopicState,
} from "./types";

// 派单在飞时 5 秒一刷（n8n 一趟约 30 秒），闲着 30 秒一刷。
const BUSY_POLL_MS = 5000;
const IDLE_POLL_MS = 30000;

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
  const [publishState, setPublishState] = useState<PublishState>({
    drafts: [],
    in_flight: [],
    live: [],
    units: [],
  });
  const [pageBusy, setPageBusy] = useState<string | null>(null);
  const [pageNotice, setPageNotice] = useState<string | null>(null);
  const [topicState, setTopicState] = useState<TopicState>({
    awaiting_generation: [],
    clusters_needing_questions: [],
    seo_candidates: [],
  });
  const [pickingFor, setPickingFor] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [nextQueue, nextOverview, nextUnits, nextTopics] = await Promise.all([
        fetchQueue(),
        fetchOverview(),
        fetchPublishState(),
        fetchTopics(),
      ]);
      setQueue(nextQueue);
      setOverview(nextOverview);
      setPublishState(nextUnits);
      setTopicState(nextTopics);
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  /** 选题类动作长得都一样：置忙 → 调一次 → 报一句人话 → 整页刷新。 */
  const topicAction = useCallback(
    async (tag: string, action: () => Promise<string>) => {
      setPageBusy(tag);
      setError(null);
      setPageNotice(null);
      try {
        setPageNotice(await action());
        await reload();
      } catch (actionError) {
        setError((actionError as Error).message);
      } finally {
        setPageBusy(null);
      }
    },
    [reload],
  );

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
            "n8n 正在建草稿，约半分钟。**建好之后还要你去 WordPress 点发布**——" +
            "在那之前读者看到的是 404。刷新这一页就能看到进度。",
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

  // 有派单在飞的时候快刷，闲着的时候慢刷（照 EnrichmentDeck 的忙/闲双档）。
  //
  // 2026-08-03 用户报「n8n 已经发布成功了，控制台还显示派单中」——后端一切正常，
  // 是这一页**根本没有轮询**：点完发布那一刻刷了一次（那时任务刚派出去、状态
  // 确实是 dispatched），然后就再也不刷了。**一个瞬时状态被冻在屏幕上，
  // 比不显示它更糟**——它会让人以为系统卡死了。
  const busyPipeline = publishState.in_flight.length > 0;
  useEffect(() => {
    const timer = window.setInterval(
      () => void reload(),
      busyPipeline ? BUSY_POLL_MS : IDLE_POLL_MS,
    );
    return () => window.clearInterval(timer);
  }, [busyPipeline, reload]);

  // OverlayModal 的 onClose 进 effect 依赖，必须 useCallback——
  // 否则每次 render 都重挂滚动锁，scrollbarWidth 会算成 0 把 padding 弄错。
  const closeModal = useCallback(() => setIndex(null), []);
  const closePicker = useCallback(() => setPickingFor(null), []);
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

      <TopicPanel
        busy={pageBusy}
        onGenerate={(ids) =>
          void topicAction("generate", async () => {
            const r = await generateTopics(ids);
            return `已排队 ${r.queued} 篇。AI 写一篇一分钟起步，写完会出现在「等你审」。`;
          })
        }
        onGenerateCluster={(id) =>
          void topicAction(`cluster:${id}`, async () => {
            const r = await generateCluster(id);
            return `已排队 ${r.queued} 个任务。已批准的文章不会被动。`;
          })
        }
        onPick={(id, status) =>
          void topicAction(`pick:${id}`, async () => {
            await pickTopic(id, status);
            return status === "picked"
              ? "挑中了，可以生成了。"
              : "已标为不写。";
          })
        }
        onPickQuestions={(id) => setPickingFor(id)}
        state={topicState}
      />

      <PublishPanel busy={pageBusy} onPublish={(u) => void publish(u)} state={publishState} />

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

      {pickingFor ? (
        <QuestionPicker
          clusterId={pickingFor}
          onClose={closePicker}
          onSaved={(count) => {
            setPageNotice(`挑了 ${count} 条买家问句，现在可以生成了。`);
            void reload();
          }}
        />
      ) : null}

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
