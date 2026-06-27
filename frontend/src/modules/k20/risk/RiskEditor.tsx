"use client";

import { Check, CircleSlash, Loader2, ShieldCheck, X } from "lucide-react";
import { useState } from "react";

import styles from "./RiskPanel.module.css";
import type { RiskStatus, RiskTerm, UpdateRiskPayload } from "./types";
import { riskStatuses, riskStatusLabels } from "./types";

type RiskEditorProps = {
  entry: RiskTerm;
  isSaving: boolean;
  onCancel: () => void;
  onSave: (riskId: string, payload: UpdateRiskPayload) => Promise<void>;
  onIgnore: (riskId: string) => Promise<void>;
  onResolve: (riskId: string) => Promise<void>;
};

export function RiskEditor({
  entry,
  isSaving,
  onCancel,
  onIgnore,
  onResolve,
  onSave,
}: RiskEditorProps) {
  const [status, setStatus] = useState<RiskStatus>(entry.status);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSave(entry.id, { status });
  }

  return (
    <form className={styles.editor} onSubmit={(event) => void handleSubmit(event)}>
      <label className={styles.field}>
        <span>状态</span>
        <select
          onChange={(event) => setStatus(event.target.value as RiskStatus)}
          value={status}
        >
          {riskStatuses.map((riskStatus) => (
            <option key={riskStatus} value={riskStatus}>
              {riskStatusLabels[riskStatus]}
            </option>
          ))}
        </select>
      </label>

      <div className={styles.editorActions}>
        <button
          aria-label="保存风险状态"
          className={styles.iconButton}
          disabled={isSaving}
          title="保存风险状态"
          type="submit"
        >
          {isSaving ? (
            <Loader2 aria-hidden="true" className="spin" size={16} />
          ) : (
            <Check aria-hidden="true" size={16} />
          )}
        </button>
        <button
          aria-label="处理风险词"
          className={styles.iconButton}
          disabled={isSaving || entry.status === "resolved"}
          onClick={() => void onResolve(entry.id)}
          title="处理风险词"
          type="button"
        >
          <ShieldCheck aria-hidden="true" size={16} />
        </button>
        <button
          aria-label="忽略风险词"
          className={styles.iconButtonSecondary}
          disabled={isSaving || entry.status === "ignored"}
          onClick={() => void onIgnore(entry.id)}
          title="忽略风险词"
          type="button"
        >
          <CircleSlash aria-hidden="true" size={16} />
        </button>
        <button
          aria-label="取消编辑"
          className={styles.iconButtonSecondary}
          disabled={isSaving}
          onClick={onCancel}
          title="取消编辑"
          type="button"
        >
          <X aria-hidden="true" size={16} />
        </button>
      </div>
    </form>
  );
}
