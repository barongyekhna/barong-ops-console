"use client";

import { useCallback, useEffect, useState } from "react";

import { OverlayModal } from "@/components/overlay-modal";

import styles from "./ContentDesk.module.css";
import { fetchClusterQuestions, saveClusterQuestions } from "./api";
import type { ClusterQuestions } from "./types";

/**
 * 挑买家问句。
 *
 * **空问句不阻塞生成**，只是退化成「按产品规格写」。所以文案是「挑了才会回答
 * 真实买家问题」，不是「不挑不能生成」——把建议写成阻塞，人会以为系统坏了。
 *
 * 候选**不出新网**：复用 K 的 FAQ 研究、F 的关键词、以及已经挖好的问句表。
 * 每条挂着阵地读数——挑的时候就看得见「这条打不打得动」，而不是写完发布了
 * 才发现前排全是守门人榜单。
 */
export function QuestionPicker({
  clusterId,
  onClose,
  onSaved,
}: {
  clusterId: string;
  onClose: () => void;
  onSaved: (count: number) => void;
}) {
  const [data, setData] = useState<ClusterQuestions | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const loaded = await fetchClusterQuestions(clusterId);
        if (!alive) return;
        setData(loaded);
        setChosen(new Set(loaded.picked.map((p) => p.question)));
      } catch (loadError) {
        if (alive) setError((loadError as Error).message);
      }
    })();
    return () => {
      alive = false;
    };
  }, [clusterId]);

  const toggle = useCallback((question: string) => {
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(question)) next.delete(question);
      else next.add(question);
      return next;
    });
  }, []);

  const save = useCallback(async () => {
    if (!data) return;
    setBusy(true);
    setError(null);
    try {
      const picked = data.candidates
        .filter((c) => chosen.has(c.question))
        .map((c) => ({ intent: c.intent, question: c.question }));
      const result = await saveClusterQuestions(clusterId, picked);
      onSaved(result.picked);
      onClose();
    } catch (saveError) {
      setError((saveError as Error).message);
    } finally {
      setBusy(false);
    }
  }, [chosen, clusterId, data, onClose, onSaved]);

  return (
    <OverlayModal
      label="挑买家问句"
      onClose={onClose}
      width="min(880px, 100%)"
    >
      <div className={styles.modalHead}>
        <div style={{ flex: 1 }}>
          <h3 className={styles.modalTitle}>
            挑买家问句{data ? `：${data.cluster.title}` : ""}
          </h3>
          <div className={styles.todoNote}>
            挑中的问句会被逐条回答。不挑也能生成，但那样只能按产品规格写。
          </div>
        </div>
      </div>

      <div className={styles.modalBody}>
        {error ? (
          <div className={`${styles.card} ${styles.error}`}>{error}</div>
        ) : null}
        {!data ? (
          <span className={styles.empty}>读取候选中…</span>
        ) : data.candidates.length === 0 ? (
          <span className={styles.empty}>
            这个类目还没挖到候选问句。去 GEO 引擎跑一次「话题采集」。
          </span>
        ) : (
          data.candidates.map((candidate) => {
            const on = chosen.has(candidate.question);
            const score = candidate.terrain?.attackability;
            return (
              <label
                className={styles.finding}
                key={candidate.question}
                style={{ cursor: "pointer" }}
              >
                <input
                  checked={on}
                  onChange={() => toggle(candidate.question)}
                  type="checkbox"
                />
                <span className={styles.findingMain}>
                  {candidate.question}
                  {candidate.intent ? (
                    <span className={styles.surface}> · {candidate.intent}</span>
                  ) : null}
                </span>
                {typeof score === "number" ? (
                  <span
                    className={styles.surface}
                    title="可攻度：越高越有机会排上去"
                  >
                    可攻 {score}
                  </span>
                ) : null}
              </label>
            );
          })
        )}
      </div>

      <div className={styles.modalFoot}>
        <span className={styles.footHint}>已挑 {chosen.size} 条</span>
        <button
          className={`${styles.btn} ${styles.btnQuiet}`}
          onClick={onClose}
          type="button"
        >
          取消
        </button>
        <button
          className={`${styles.btn} ${styles.btnGo}`}
          disabled={busy || !data}
          onClick={() => void save()}
          type="button"
        >
          {busy ? "保存中…" : "保存"}
        </button>
      </div>
    </OverlayModal>
  );
}
