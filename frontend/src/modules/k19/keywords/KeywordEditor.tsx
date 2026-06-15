"use client";

import { Check, Loader2, X } from "lucide-react";
import { useState } from "react";

import styles from "./KeywordPanel.module.css";
import type { KeywordEntry, KeywordStatus, UpdateKeywordPayload } from "./types";
import { keywordStatuses } from "./types";

type KeywordEditorProps = {
  entry: KeywordEntry;
  isSaving: boolean;
  onCancel: () => void;
  onSave: (keywordId: string, payload: UpdateKeywordPayload) => Promise<void>;
};

export function KeywordEditor({
  entry,
  isSaving,
  onCancel,
  onSave,
}: KeywordEditorProps) {
  const [keyword, setKeyword] = useState(entry.keyword);
  const [status, setStatus] = useState<KeywordStatus>(entry.status);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    await onSave(entry.id, {
      keyword,
      status,
    });
  }

  return (
    <form className={styles.editor} onSubmit={(event) => void handleSubmit(event)}>
      <label className={styles.field}>
        <span>Keyword</span>
        <input
          onChange={(event) => setKeyword(event.target.value)}
          type="text"
          value={keyword}
        />
      </label>

      <label className={styles.field}>
        <span>Status</span>
        <select
          onChange={(event) => setStatus(event.target.value as KeywordStatus)}
          value={status}
        >
          {keywordStatuses.map((keywordStatus) => (
            <option key={keywordStatus} value={keywordStatus}>
              {keywordStatus}
            </option>
          ))}
        </select>
      </label>

      <div className={styles.editorActions}>
        <button
          aria-label="Save keyword"
          className={styles.iconButton}
          disabled={isSaving || !keyword.trim()}
          title="Save keyword"
          type="submit"
        >
          {isSaving ? (
            <Loader2 aria-hidden="true" className="spin" size={16} />
          ) : (
            <Check aria-hidden="true" size={16} />
          )}
        </button>
        <button
          aria-label="Cancel edit"
          className={styles.iconButtonSecondary}
          disabled={isSaving}
          onClick={onCancel}
          title="Cancel edit"
          type="button"
        >
          <X aria-hidden="true" size={16} />
        </button>
      </div>
    </form>
  );
}
