"use client";

import { useCallback } from "react";

import { OverlayModal, isTypingTarget } from "@/components/overlay-modal";

import { AnalysisPanel } from "./AnalysisPanel";
import { ArticleBody } from "./ArticleBody";
import { AuditPanel, type IgnorePayload } from "./AuditPanel";
import styles from "./ContentDesk.module.css";
import type { Article } from "./types";

/**
 * 审稿浮窗。设计目标只有一个：**8 篇能一口气过完，中途不回列表。**
 *
 * 所以「批准」之后直接跳下一篇，`←/→` 也能翻。翻页快捷键在本仓是第一处
 * （非游戏的 keydown 只有 5 处 Esc），有一个现有代码都没覆盖的坑：焦点在
 * 输入框里时方向键属于光标，必须放行。
 */
export type ModalAction = {
  busy: string | null;
  onApprove: () => void;
  onReject: () => void;
  onRevise: () => void;
  onAnalyze: () => void;
  onToggleIgnore: (payload: IgnorePayload, ignored: boolean) => void;
};

export function ArticleModal({
  article,
  index,
  total,
  onClose,
  onPrev,
  onNext,
  action,
  error,
  notice,
}: {
  article: Article;
  index: number;
  total: number;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
  action: ModalAction;
  error: string | null;
  notice: string | null;
}) {
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      // 焦点在输入控件里 → 方向键归光标，不翻页。
      if (isTypingTarget(event.target)) return false;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        onPrev();
        return true;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        onNext();
        return true;
      }
      return false;
    },
    [onNext, onPrev],
  );

  const audit = article.brand_audit;
  const risks = article.analysis?.risks ?? [];
  const busy = action.busy;
  const perms = article.permissions;

  // 「按批评重写」的三种状态，都不是报错：没解读 → 先跑解读；
  // 解读了但零批评 → 本来就不用重写。
  const reviseBlocked = !article.analysis
    ? "先跑一次解读，重写要照着批评改"
    : risks.length === 0
      ? "解读没提出问题，无需重写"
      : perms.can_revise === false
        ? (perms.blocked_reason ?? "没有重写权限")
        : null;

  const approveBlocked =
    perms.can_review === false
      ? (perms.blocked_reason ?? "没有审阅权限")
      : !audit.clean && audit.audited
        ? "先处理审查发现，或把误报放行"
        : null;

  return (
    <OverlayModal label={`审阅：${article.title}`} onClose={onClose} onKeyDown={handleKeyDown} width="min(1100px, 100%)">
      <div className={styles.modalHead}>
        <div style={{ flex: 1 }}>
          <h3 className={styles.modalTitle}>{article.title}</h3>
          <div className={styles.chips}>
            <span className={styles.chip}>
              {article.source_label} · {article.kind_label}
            </span>
            {article.parent_label ? (
              <span className={styles.chip}>{article.parent_label}</span>
            ) : null}
            <span
              className={`${styles.chip} ${audit.clean ? styles.chipOk : styles.chipBad}`}
            >
              {audit.audited
                ? audit.clean
                  ? "审查通过"
                  : "审查未过"
                : "没有审查记录"}
            </span>
            {article.published_url ? (
              <span className={`${styles.chip} ${styles.chipOk}`}>
                线上 · {article.wp_status ?? "?"}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <div className={styles.modalBody}>
        {error ? (
          <div className={`${styles.card} ${styles.error}`} style={{ marginBottom: 14 }}>
            {error}
          </div>
        ) : null}
        {notice ? (
          <div className={`${styles.card} ${styles.notice}`} style={{ marginBottom: 14 }}>
            {notice}
          </div>
        ) : null}

        <ArticleBody article={article} />

        <AnalysisPanel
          analysis={article.analysis}
          busy={busy === "analyze"}
          onAnalyze={action.onAnalyze}
        />

        <AuditPanel
          audit={audit}
          busy={busy !== null}
          onToggleIgnore={action.onToggleIgnore}
        />

        {article.revision ? (
          <div className={styles.panel}>
            <div className={styles.panelLabel}>
              已按批评重写（第 {article.revision.round ?? 1} 轮）
            </div>
            {article.revision.addressed?.length ? (
              <ul className={`${styles.panelList} ${styles.good}`}>
                {article.revision.addressed.map((item, i) => (
                  <li key={`ad-${i}`}>{item}</li>
                ))}
              </ul>
            ) : null}
            {article.revision.unaddressed?.length ? (
              <>
                <div className={`${styles.panelLabel} ${styles.risk}`}>
                  改不了的（绝不编造事实）
                </div>
                <ul className={styles.panelList}>
                  {article.revision.unaddressed.map((item, i) => (
                    <li key={`un-${i}`}>
                      {item.critique}
                      {item.reason ? ` —— ${item.reason}` : ""}
                      {item.missing_fact ? `（需补数据：${item.missing_fact}）` : ""}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className={styles.modalFoot}>
        <span className={styles.footHint}>
          第 {index + 1} / 共 {total} 篇
          {total > 1 ? " · ←/→ 翻页" : ""}
        </span>
        <button
          className={`${styles.btn} ${styles.btnQuiet}`}
          disabled={busy !== null || reviseBlocked !== null}
          onClick={action.onRevise}
          title={reviseBlocked ?? "把批评喂回去重写这一篇"}
          type="button"
        >
          {busy === "revise" ? "重写中…（约 30 秒）" : "打回重写"}
        </button>
        <button
          className={`${styles.btn} ${styles.btnQuiet}`}
          disabled={busy !== null || perms.can_review === false}
          onClick={action.onReject}
          type="button"
        >
          驳回
        </button>
        <button
          className={`${styles.btn} ${styles.btnGo}`}
          disabled={busy !== null || approveBlocked !== null}
          onClick={action.onApprove}
          title={approveBlocked ?? "批准并看下一篇"}
          type="button"
        >
          {busy === "approve"
            ? "提交中…"
            : index + 1 < total
              ? "批准，下一篇 →"
              : "批准，完成"}
        </button>
      </div>
    </OverlayModal>
  );
}
