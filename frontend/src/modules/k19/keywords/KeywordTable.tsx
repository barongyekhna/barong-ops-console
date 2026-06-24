"use client";

import { Archive, Edit3, Loader2, RefreshCw, Search } from "lucide-react";

import { KeywordEditor } from "./KeywordEditor";
import styles from "./KeywordPanel.module.css";
import type { KeywordEntry, UpdateKeywordPayload } from "./types";
import { sourceLabels } from "./types";

type KeywordTableProps = {
  editingId: string | null;
  entries: KeywordEntry[];
  isDeletingId: string | null;
  isLoading: boolean;
  isSavingEditor: boolean;
  productId: string;
  onArchive: (keywordId: string) => Promise<void>;
  onEdit: (keywordId: string) => void;
  onEditorCancel: () => void;
  onEditorSave: (
    keywordId: string,
    payload: UpdateKeywordPayload,
  ) => Promise<void>;
  onProductIdChange: (productId: string) => void;
  onRefresh: () => Promise<void>;
};

export function KeywordTable({
  editingId,
  entries,
  isDeletingId,
  isLoading,
  isSavingEditor,
  productId,
  onArchive,
  onEdit,
  onEditorCancel,
  onEditorSave,
  onProductIdChange,
  onRefresh,
}: KeywordTableProps) {
  return (
    <div className={styles.tableSection}>
      <div className={styles.tableToolbar}>
        <label className={styles.filterField}>
          <span>Product filter</span>
          <div>
            <Search aria-hidden="true" size={15} />
            <input
              onChange={(event) => onProductIdChange(event.target.value)}
              placeholder="product id"
              type="text"
              value={productId}
            />
          </div>
        </label>

        <button
          aria-label="Refresh keywords"
          className={styles.iconButtonSecondary}
          disabled={isLoading || !productId.trim()}
          onClick={() => void onRefresh()}
          title="Refresh keywords"
          type="button"
        >
          {isLoading ? (
            <Loader2 aria-hidden="true" className="spin" size={16} />
          ) : (
            <RefreshCw aria-hidden="true" size={16} />
          )}
        </button>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Keyword</th>
              <th>Status</th>
              <th>Source</th>
              <th>Product id</th>
              <th>Updated</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 ? (
              <tr>
                <td className={styles.emptyCell} colSpan={6}>
                  {isLoading ? "Loading keywords." : "No keywords for this product."}
                </td>
              </tr>
            ) : (
              entries.map((entry) => (
                <tr key={entry.id}>
                  <td className={styles.keywordCell}>
                    {editingId === entry.id ? (
                      <KeywordEditor
                        entry={entry}
                        isSaving={isSavingEditor}
                        onCancel={onEditorCancel}
                        onSave={onEditorSave}
                      />
                    ) : (
                      <span>{entry.keyword}</span>
                    )}
                  </td>
                  <td>
                    <span className={`${styles.statusBadge} ${styles[entry.status]}`}>
                      {entry.status}
                    </span>
                  </td>
                  <td>
                    <span className={`${styles.sourceBadge} ${sourceClass(entry.source)}`}>
                      {sourceLabels[entry.source]}
                    </span>
                  </td>
                  <td className={styles.monoCell}>{entry.product_id}</td>
                  <td>{formatTimestamp(entry.updated_at)}</td>
                  <td>
                    <div className={styles.rowActions}>
                      <button
                        aria-label={`Edit ${entry.keyword}`}
                        className={styles.iconButton}
                        disabled={editingId !== null || entry.status === "archived"}
                        onClick={() => onEdit(entry.id)}
                        title="Edit keyword"
                        type="button"
                      >
                        <Edit3 aria-hidden="true" size={15} />
                      </button>
                      <button
                        aria-label={`Archive ${entry.keyword}`}
                        className={styles.iconButtonSecondary}
                        disabled={entry.status === "archived" || isDeletingId === entry.id}
                        onClick={() => void onArchive(entry.id)}
                        title="Archive keyword"
                        type="button"
                      >
                        {isDeletingId === entry.id ? (
                          <Loader2 aria-hidden="true" className="spin" size={15} />
                        ) : (
                          <Archive aria-hidden="true" size={15} />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function sourceClass(source: KeywordEntry["source"]) {
  if (source === "K15") {
    return styles.sourceK15;
  }
  if (source === "K16") {
    return styles.sourceK16;
  }
  if (source === "K17") {
    return styles.sourceK17;
  }
  if (source === "K18") {
    return styles.sourceK18;
  }
  return styles.sourceManual;
}

function formatTimestamp(value: string) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
