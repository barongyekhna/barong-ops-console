"use client";

import {
  CircleSlash,
  Edit3,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import { RiskBadge } from "./RiskBadge";
import { RiskEditor } from "./RiskEditor";
import styles from "./RiskPanel.module.css";
import type {
  RiskCategory,
  RiskLevel,
  RiskTerm,
  UpdateRiskPayload,
} from "./types";
import { riskCategories, riskLevels, sourceLabels } from "./types";

type RiskFilterValue<T extends string> = T | "all";

type RiskTableProps = {
  categoryFilter: RiskFilterValue<RiskCategory>;
  editingId: string | null;
  entries: RiskTerm[];
  isIgnoringId: string | null;
  isLoading: boolean;
  isResolvingId: string | null;
  isSavingEditor: boolean;
  levelFilter: RiskFilterValue<RiskLevel>;
  onCategoryFilterChange: (category: RiskFilterValue<RiskCategory>) => void;
  onEdit: (riskId: string) => void;
  onEditorCancel: () => void;
  onEditorSave: (riskId: string, payload: UpdateRiskPayload) => Promise<void>;
  onIgnore: (riskId: string) => Promise<void>;
  onLevelFilterChange: (level: RiskFilterValue<RiskLevel>) => void;
  onRefresh: () => Promise<void>;
  onResolve: (riskId: string) => Promise<void>;
};

export function RiskTable({
  categoryFilter,
  editingId,
  entries,
  isIgnoringId,
  isLoading,
  isResolvingId,
  isSavingEditor,
  levelFilter,
  onCategoryFilterChange,
  onEdit,
  onEditorCancel,
  onEditorSave,
  onIgnore,
  onLevelFilterChange,
  onRefresh,
  onResolve,
}: RiskTableProps) {
  return (
    <div className={styles.tableSection}>
      <div className={styles.tableToolbar}>
        <div className={styles.filterGroup}>
          <label className={styles.filterField}>
            <span>Severity</span>
            <select
              onChange={(event) =>
                onLevelFilterChange(event.target.value as RiskFilterValue<RiskLevel>)
              }
              value={levelFilter}
            >
              <option value="all">all</option>
              {riskLevels.map((riskLevel) => (
                <option key={riskLevel} value={riskLevel}>
                  {riskLevel}
                </option>
              ))}
            </select>
          </label>

          <label className={styles.filterField}>
            <span>Category</span>
            <select
              onChange={(event) =>
                onCategoryFilterChange(
                  event.target.value as RiskFilterValue<RiskCategory>,
                )
              }
              value={categoryFilter}
            >
              <option value="all">all</option>
              {riskCategories.map((riskCategory) => (
                <option key={riskCategory} value={riskCategory}>
                  {riskCategory}
                </option>
              ))}
            </select>
          </label>
        </div>

        <button
          aria-label="Refresh risks"
          className={styles.iconButtonSecondary}
          disabled={isLoading}
          onClick={() => void onRefresh()}
          title="Refresh risks"
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
              <th>Term</th>
              <th>Risk level</th>
              <th>Category</th>
              <th>Source</th>
              <th>Status</th>
              <th>Product id</th>
              <th>Updated</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 ? (
              <tr>
                <td className={styles.emptyCell} colSpan={8}>
                  {isLoading ? "Loading risks." : "No risk terms."}
                </td>
              </tr>
            ) : (
              entries.map((entry) => (
                <tr key={entry.id}>
                  <td className={styles.termCell}>
                    <span>{entry.term}</span>
                    {editingId === entry.id ? (
                      <RiskEditor
                        entry={entry}
                        isSaving={isSavingEditor}
                        onCancel={onEditorCancel}
                        onIgnore={onIgnore}
                        onResolve={onResolve}
                        onSave={onEditorSave}
                      />
                    ) : null}
                  </td>
                  <td>
                    <RiskBadge level={entry.risk_level} />
                  </td>
                  <td>
                    <span className={styles.categoryBadge}>{entry.category}</span>
                  </td>
                  <td>
                    <span className={`${styles.sourceBadge} ${sourceClass(entry.source)}`}>
                      {sourceLabels[entry.source]}
                    </span>
                  </td>
                  <td>
                    <span className={`${styles.statusBadge} ${styles[entry.status]}`}>
                      {entry.status}
                    </span>
                  </td>
                  <td className={styles.monoCell}>{entry.product_id}</td>
                  <td>{formatTimestamp(entry.updated_at)}</td>
                  <td>
                    <div className={styles.rowActions}>
                      <button
                        aria-label={`Edit ${entry.term}`}
                        className={styles.iconButton}
                        disabled={editingId !== null || entry.status === "ignored"}
                        onClick={() => onEdit(entry.id)}
                        title="Edit risk"
                        type="button"
                      >
                        <Edit3 aria-hidden="true" size={15} />
                      </button>
                      <button
                        aria-label={`Resolve ${entry.term}`}
                        className={styles.iconButton}
                        disabled={
                          entry.status === "resolved" || isResolvingId === entry.id
                        }
                        onClick={() => void onResolve(entry.id)}
                        title="Resolve risk"
                        type="button"
                      >
                        {isResolvingId === entry.id ? (
                          <Loader2 aria-hidden="true" className="spin" size={15} />
                        ) : (
                          <ShieldCheck aria-hidden="true" size={15} />
                        )}
                      </button>
                      <button
                        aria-label={`Ignore ${entry.term}`}
                        className={styles.iconButtonSecondary}
                        disabled={entry.status === "ignored" || isIgnoringId === entry.id}
                        onClick={() => void onIgnore(entry.id)}
                        title="Ignore risk"
                        type="button"
                      >
                        {isIgnoringId === entry.id ? (
                          <Loader2 aria-hidden="true" className="spin" size={15} />
                        ) : (
                          <CircleSlash aria-hidden="true" size={15} />
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

function sourceClass(source: RiskTerm["source"]) {
  if (source === "K13") {
    return styles.sourceK13;
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
