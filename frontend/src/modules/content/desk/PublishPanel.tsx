"use client";

import styles from "./ContentDesk.module.css";
import type { PublishUnit } from "./types";

/**
 * 发布。**操作的是「发布单元」，不是文章。**
 *
 * GEO 一次发整簇。做成「每篇一个发布按钮」必然骗人：点一篇，同簇另外三篇会跟着
 * 出去而界面上什么都没说。所以按钮旁边**逐篇列出这次到底会发哪几篇**。
 */
export function PublishPanel({
  units,
  busy,
  onPublish,
}: {
  units: PublishUnit[];
  busy: string | null;
  onPublish: (unit: PublishUnit) => void;
}) {
  if (!units.length) return null;
  return (
    <>
      <div className={styles.sectionLabel}>可以发布的</div>
      {units.map((unit) => {
        const key = `${unit.source}:${unit.unit_id}`;
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
                disabled={busy !== null || blocked}
                onClick={() => onPublish(unit)}
                title={blocked ? unit.blockers.join("；") : "派单给 n8n，落草稿等你在 WP 里发布"}
                type="button"
              >
                {busy === key ? "派单中…" : "发布"}
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
  );
}
