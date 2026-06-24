"use client";

import { Loader2, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import styles from "./KeywordPanel.module.css";
import type {
  CreateKeywordPayload,
  KeywordSource,
  KeywordStatus,
} from "./types";
import { keywordSources, keywordStatuses, sourceLabels } from "./types";

type KeywordInputProps = {
  isSaving: boolean;
  productId: string;
  onCreate: (payload: CreateKeywordPayload) => Promise<boolean>;
};

export function KeywordInput({
  isSaving,
  productId,
  onCreate,
}: KeywordInputProps) {
  const [keyword, setKeyword] = useState("");
  const [entryProductId, setEntryProductId] = useState(productId);
  const [source, setSource] = useState<KeywordSource>("manual");
  const [status, setStatus] = useState<KeywordStatus>("active");

  useEffect(() => {
    setEntryProductId(productId);
  }, [productId]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const created = await onCreate({
      keyword,
      product_id: entryProductId,
      source,
      status,
    });
    if (created) {
      setKeyword("");
    }
  }

  return (
    <form className={styles.inputBar} onSubmit={(event) => void handleSubmit(event)}>
      <label className={styles.field}>
        <span>Keyword</span>
        <input
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="keyword"
          type="text"
          value={keyword}
        />
      </label>

      <label className={styles.field}>
        <span>Product id</span>
        <input
          onChange={(event) => setEntryProductId(event.target.value)}
          placeholder="product id"
          type="text"
          value={entryProductId}
        />
      </label>

      <label className={styles.field}>
        <span>Source</span>
        <select
          onChange={(event) => setSource(event.target.value as KeywordSource)}
          value={source}
        >
          {keywordSources.map((keywordSource) => (
            <option key={keywordSource} value={keywordSource}>
              {sourceLabels[keywordSource]}
            </option>
          ))}
        </select>
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

      <button
        className={styles.iconTextButton}
        disabled={isSaving || !keyword.trim() || !entryProductId.trim()}
        type="submit"
      >
        {isSaving ? (
          <Loader2 aria-hidden="true" className="spin" size={16} />
        ) : (
          <Plus aria-hidden="true" size={16} />
        )}
        Add
      </button>
    </form>
  );
}
