"use client";

/**
 * 给一个成品挂工序。整体替换,照库存那边编辑配件清单的路子。
 *
 * `per_batch` 是调机、开模摊销这类不随件数走的钱:1000 件和 100 件摊下来天差地别,
 * 这一项直接决定小单能不能接,所以在界面上必须让人一眼看出选的是哪种。
 */

import { useState } from "react";

import base from "../inventory/Inventory.module.css";
import { Dialog } from "../inventory/Dialog";
import styles from "./Cost.module.css";
import { type LaborLine, type LaborMode, type LaborProcess } from "./api";

type Draft = { process_id: string; mode: LaborMode; qty: string };

export function LaborEditor({
  lines,
  processes,
  onSave,
  onClose,
}: {
  lines: LaborLine[];
  processes: LaborProcess[];
  onSave: (lines: Draft[]) => Promise<void>;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<Draft[]>(
    lines.map((line) => ({
      mode: line.mode,
      process_id: line.process_id,
      qty: line.qty,
    })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const available = processes.filter(
    (process) =>
      !process.is_archived &&
      !draft.some((row) => row.process_id === process.id),
  );

  const add = (processId: string) => {
    setDraft((current) => [
      ...current,
      { mode: "per_unit", process_id: processId, qty: "1" },
    ]);
  };

  const update = (index: number, patch: Partial<Draft>) => {
    setDraft((current) =>
      current.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  };

  const remove = (index: number) => {
    setDraft((current) => current.filter((_, i) => i !== index));
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave(draft);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
      setBusy(false);
    }
  };

  const nameOf = (processId: string) =>
    processes.find((process) => process.id === processId)?.name ?? processId;

  return (
    <Dialog onClose={onClose} title="编辑工序">
      <div className={base.form}>
        {error ? <p className={base.error}>{error}</p> : null}

        {draft.length ? (
          <div className={base.lineList}>
            {draft.map((row, index) => (
              <div className={base.line} key={row.process_id}>
                <span>{nameOf(row.process_id)}</span>
                <select
                  className={base.select}
                  onChange={(event) =>
                    update(index, { mode: event.target.value as LaborMode })
                  }
                  value={row.mode}
                >
                  <option value="per_unit">每件</option>
                  <option value="per_batch">每批（摊销）</option>
                </select>
                <input
                  className={base.inputSm}
                  inputMode="decimal"
                  onChange={(event) => update(index, { qty: event.target.value })}
                  value={row.qty}
                />
                <button
                  className={base.btnGhost}
                  onClick={() => remove(index)}
                  type="button"
                >
                  移除
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className={base.empty}>还没挂工序。</p>
        )}

        {available.length ? (
          <div className={base.field}>
            <span className={base.label}>加一道工序</span>
            <div className={styles.processChips}>
              {available.map((process) => (
                <button
                  className={base.btnGhost}
                  key={process.id}
                  onClick={() => add(process.id)}
                  type="button"
                >
                  + {process.name}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div className={base.footer}>
          <button
            className={base.btnPrimary}
            disabled={busy}
            onClick={save}
            type="button"
          >
            保存
          </button>
        </div>
      </div>
    </Dialog>
  );
}
