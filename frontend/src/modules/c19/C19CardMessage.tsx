"use client";

import styles from "./C19Workspace.module.css";
import { type ParsedCard } from "./c19Card";

export { parseC19Card, type ParsedCard } from "./c19Card";

/**
 * 数字员工的「待确认卡」。
 *
 * C19 的记录服务只认 text/emoji/image/file 四种消息,所以卡片仍是一条文本:
 * 首行 `【待确认 #ab12】入库`,末行机器标记 `⟦card:ab12⟧`。前端认出标记就渲染成
 * 带「确认 / 取消」按钮的卡片,按钮替用户发「确认 #ab12」/「取消 #ab12」;
 * 别的客户端看到的还是可读文本。
 */

export function C19CardMessage({
  card,
  actionable,
  busy,
  onAction,
}: {
  card: ParsedCard;
  /** 只有卡还是会话里最新一条、且是当前用户开的时候才能点。 */
  actionable: boolean;
  busy: boolean;
  onAction: (text: string) => void;
}) {
  return (
    <>
    {card.preface ? <p>{card.preface}</p> : null}
    <div className={styles.confirmCard} data-actionable={actionable}>
      <header className={styles.confirmCardHead}>
        <span className={styles.confirmCardTitle}>{card.title}</span>
      </header>
      <pre className={styles.confirmCardBody}>{card.lines.join("\n")}</pre>
      {actionable ? (
        <div className={styles.confirmCardActions}>
          <button
            className={styles.confirmCardCancel}
            disabled={busy}
            onClick={() => onAction(`取消 #${card.cardId}`)}
            type="button"
          >
            取消
          </button>
          <button
            className={styles.confirmCardConfirm}
            disabled={busy}
            onClick={() => onAction(`确认 #${card.cardId}`)}
            type="button"
          >
            确认执行
          </button>
        </div>
      ) : (
        <footer className={styles.confirmCardDone}>已处理 / 已作废</footer>
      )}
    </div>
    </>
  );
}
