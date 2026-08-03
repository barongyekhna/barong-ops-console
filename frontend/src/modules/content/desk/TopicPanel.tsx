"use client";

import styles from "./ContentDesk.module.css";
import type { TopicState } from "./types";

/**
 * 第①②步：挑选题、挑问句、派生成。
 *
 * 原本这两步只能去 GEO/SEO 老页面做，内容台只显示一个数字然后让人自己走开——
 * 那等于把「你不知道下一步该干嘛」原样退还给用户。
 *
 * 分数已经把「有没有事实支撑」折进去了，所以清单里直接把「能写什么/缺什么」
 * 摆出来：挑之前就该看见，不然挑完才发现没料。
 */
const AUDIENCE_LABEL: Record<string, string> = {
  brand: "品牌",
  consumer: "C 端买家",
  wholesale: "B 端采购",
};

export function TopicPanel({
  state,
  busy,
  onPick,
  onPickQuestions,
  onGenerateCluster,
}: {
  state: TopicState;
  busy: string | null;
  onPick: (id: string, status: "picked" | "rejected") => void;
  onPickQuestions: (clusterId: string) => void;
  onGenerateCluster: (clusterId: string) => void;
}) {
  const { seo_candidates: candidates, clusters_needing_questions: clusters } = state;
  if (!candidates.length && !clusters.length) {
    return (
      <div className={styles.card}>
        <span className={styles.empty}>
          没有待挑的选题。关键词雷达跑出新候选时会出现在这里。
        </span>
      </div>
    );
  }

  return (
    <>
      {clusters.length ? (
        <>
          <div className={styles.sectionLabel}>还没挑买家问句的话题簇</div>
          {clusters.map((cluster) => (
            <div className={styles.card} key={cluster.id}>
              <div className={styles.todoRow}>
                <div className={styles.todoMain}>
                  <div className={styles.todoLead}>{cluster.title}</div>
                  <div className={styles.todoNote}>
                    {cluster.product_count} 个产品 ·{" "}
                    {cluster.category_path ?? "未挂类目"}　挑了才会回答真实买家
                    问题；不挑也能写，但只能按规格写。
                  </div>
                </div>
                <button
                  className={styles.btn}
                  disabled={busy !== null}
                  onClick={() => onPickQuestions(cluster.id)}
                  type="button"
                >
                  挑问句
                </button>
                <button
                  className={`${styles.btn} ${styles.btnQuiet}`}
                  disabled={busy !== null}
                  onClick={() => onGenerateCluster(cluster.id)}
                  type="button"
                >
                  {busy === `cluster:${cluster.id}` ? "派单中…" : "直接生成"}
                </button>
              </div>
            </div>
          ))}
        </>
      ) : null}

      {candidates.length ? (
        <>
          <div className={styles.sectionLabel}>待挑的选题</div>
          {candidates.map((topic) => (
            <div className={styles.card} key={topic.id}>
              <div className={styles.todoRow}>
                <div className={styles.todoMain}>
                  <div className={styles.todoLead}>
                    {topic.keyword}
                    <span className={styles.surface}>
                      {"  "}
                      {AUDIENCE_LABEL[topic.audience] ?? topic.audience} · 落{" "}
                      /{topic.destination}/
                    </span>
                  </div>
                  <div className={styles.todoNote}>
                    分 {topic.score ?? "—"}
                    {topic.searches ? ` · 月搜 ${topic.searches}` : ""}
                    {typeof topic.attackability === "number"
                      ? ` · 可攻 ${topic.attackability}`
                      : ""}
                    {topic.supported.length
                      ? `　有料：${topic.supported.join("、")}`
                      : ""}
                    {topic.missing.length
                      ? `　缺：${topic.missing.join("、")}`
                      : ""}
                  </div>
                </div>
                <button
                  className={styles.btn}
                  disabled={busy !== null}
                  onClick={() => onPick(topic.id, "picked")}
                  type="button"
                >
                  {busy === `pick:${topic.id}` ? "…" : "挑中"}
                </button>
                <button
                  className={`${styles.btn} ${styles.btnQuiet}`}
                  disabled={busy !== null}
                  onClick={() => onPick(topic.id, "rejected")}
                  type="button"
                >
                  不写
                </button>
              </div>
            </div>
          ))}
        </>
      ) : null}
    </>
  );
}
