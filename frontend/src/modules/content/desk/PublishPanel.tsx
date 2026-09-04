"use client";

import styles from "./ContentDesk.module.css";
import type { PublishState, PublishUnit } from "./types";

/**
 * 发布。三段，缺一段就会让人以为「点了没反应」：
 *
 * 1. **可以发布的** —— 操作的是「发布单元」不是文章。GEO 一次发整簇，所以
 *    按钮旁边逐篇列出这次会发哪几篇。
 * 2. **派单中** —— 派单到 n8n 回报之间有 ~30 秒窗口，这期间文章还没有
 *    wp_post_id，单元仍然出现在待发列表里。不标出来，用户会以为没发出去。
 * 3. **已经发到站上的** —— 最要命的一段，原本完全不存在。n8n **刻意**把文章
 *    落成草稿等人工发布，所以派单成功 ≠ 读者能看到。2026-08-03 用户发了两篇，
 *    任务 success、地址也有，匿名访问却是 404。战报只说到派单、不说到读者能不能
 *    看见，那就是报了个假成功。
 */
export function PublishPanel({
  state,
  busy,
  onPublish,
}: {
  state: PublishState;
  busy: string | null;
  onPublish: (unit: PublishUnit) => void;
}) {
  const flying = new Map(
    state.in_flight.map((job) => [`${job.source}:${job.unit_id}`, job]),
  );

  /** 「派单中…（已 2 分钟）」。n8n 一趟约半分钟；超过 3 分钟多半是回报丢了，
   *  说出来，别让人对着一个永远转的圈猜。 */
  function flyingLabel(since: string | null): string {
    if (!since) return "派单中…";
    const mins = Math.floor((Date.now() - new Date(since).getTime()) / 60000);
    if (mins < 1) return "派单中…";
    if (mins < 3) return `派单中…（已 ${mins} 分钟）`;
    return `已 ${mins} 分钟没回报`;
  }
  const nothing =
    !state.units.length && !state.drafts.length && !state.live.length;
  if (nothing) return null;

  return (
    <>
      {state.units.length ? (
        <>
          <div className={styles.sectionLabel}>可以发布的</div>
          {state.units.map((unit) => {
            const key = `${unit.source}:${unit.unit_id}`;
            const job = flying.get(key);
            const blocked = unit.blockers.length > 0;
            return (
              <div className={styles.card} key={key}>
                <div className={styles.todoRow}>
                  <div className={styles.todoMain}>
                    <div className={styles.todoLead}>{unit.label}</div>
                    <div className={styles.todoNote}>
                      这次会发这 {unit.titles.length} 篇：
                      {unit.titles.map((t) => `《${t}》`).join("、")}
                    </div>
                  </div>
                  <button
                    className={styles.btn}
                    disabled={busy !== null || blocked || job !== undefined}
                    onClick={() => onPublish(unit)}
                    title={
                      blocked
                        ? unit.blockers.join("；")
                        : "派单给 n8n；文章会先落成草稿，最后一步由你在 WordPress 点发布"
                    }
                    type="button"
                  >
                    {job
                      ? flyingLabel(job.since)
                      : busy === key
                        ? "派单中…"
                        : "发布"}
                  </button>
                </div>
                {blocked ? (
                  <ul className={`${styles.panelList} ${styles.risk}`}>
                    {unit.blockers.map((b) => (
                      <li key={b}>{b}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            );
          })}
        </>
      ) : null}

      {state.drafts.length ? (
        <>
          <div className={styles.sectionLabel}>
            已经在 WordPress 里，还是草稿
          </div>
          <div className={`${styles.card} ${styles.todoRow} ${styles.actionable}`}>
            <span className={styles.bead} />
            <div className={styles.todoMain}>
              <div className={styles.todoLead}>
                {state.drafts.length} 篇等你在 WP 后台点发布
              </div>
              <div className={styles.todoNote}>
                在那之前读者看到的是 404。逐篇打开：
                {state.drafts.slice(0, 6).map((row) => (
                  <span key={row.id}>
                    {" "}
                    <a
                      href={`https://barongyekhna.com/wp-admin/post.php?post=${row.wp_post_id}&action=edit`}
                      rel="noreferrer"
                      style={{ color: "var(--color-warning)" }}
                      target="_blank"
                    >
                      {row.title.slice(0, 26)}
                    </a>
                  </span>
                ))}
                {state.drafts.length > 6 ? " …" : ""}
              </div>
            </div>
            <span className={styles.count}>{state.drafts.length}</span>
          </div>
        </>
      ) : null}

      {state.live.length ? (
        <>
          <div className={styles.sectionLabel}>已经在线上</div>
          <div className={styles.card}>
            <div className={styles.todoNote}>
              {state.live.length} 篇读者能看到：
              {state.live.slice(0, 8).map((row) => (
                <span key={row.id}>
                  {" "}
                  <a
                    href={row.url ?? "#"}
                    rel="noreferrer"
                    style={{ color: "var(--color-success)" }}
                    target="_blank"
                  >
                    {row.title.slice(0, 26)}
                  </a>
                </span>
              ))}
              {state.live.length > 8 ? " …" : ""}
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
