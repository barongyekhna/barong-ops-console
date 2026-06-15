"use client";

import { Edit3, Loader2, RefreshCw, ToggleLeft, ToggleRight } from "lucide-react";

import { FeatureFlagBadge } from "./FeatureFlagBadge";
import { FeatureFlagEditor } from "./FeatureFlagEditor";
import styles from "./FeatureFlagPanel.module.css";
import type {
  FeatureFlag,
  FeatureFlagFilterValue,
  FeatureFlagModule,
  FeatureFlagScope,
  UpdateFeatureFlagPayload,
} from "./types";
import {
  featureFlagModules,
  featureFlagScopes,
  moduleLabels,
} from "./types";

type FeatureFlagTableProps = {
  editingId: string | null;
  flags: FeatureFlag[];
  isLoading: boolean;
  isSavingEditor: boolean;
  isTogglingId: string | null;
  moduleFilter: FeatureFlagFilterValue<FeatureFlagModule>;
  onEdit: (flagId: string) => void;
  onEditorCancel: () => void;
  onEditorSave: (
    flagId: string,
    payload: UpdateFeatureFlagPayload,
  ) => Promise<void>;
  onModuleFilterChange: (
    module: FeatureFlagFilterValue<FeatureFlagModule>,
  ) => void;
  onRefresh: () => Promise<void>;
  onScopeFilterChange: (
    scope: FeatureFlagFilterValue<FeatureFlagScope>,
  ) => void;
  onToggle: (flag: FeatureFlag) => Promise<void>;
  scopeFilter: FeatureFlagFilterValue<FeatureFlagScope>;
};

export function FeatureFlagTable({
  editingId,
  flags,
  isLoading,
  isSavingEditor,
  isTogglingId,
  moduleFilter,
  onEdit,
  onEditorCancel,
  onEditorSave,
  onModuleFilterChange,
  onRefresh,
  onScopeFilterChange,
  onToggle,
  scopeFilter,
}: FeatureFlagTableProps) {
  return (
    <div className={styles.tableSection}>
      <div className={styles.tableToolbar}>
        <div className={styles.filterGroup}>
          <label className={styles.filterField}>
            <span>Module</span>
            <select
              onChange={(event) =>
                onModuleFilterChange(
                  event.target.value as FeatureFlagFilterValue<FeatureFlagModule>,
                )
              }
              value={moduleFilter}
            >
              <option value="all">all</option>
              {featureFlagModules.map((module) => (
                <option key={module} value={module}>
                  {module}
                </option>
              ))}
            </select>
          </label>

          <label className={styles.filterField}>
            <span>Scope</span>
            <select
              onChange={(event) =>
                onScopeFilterChange(
                  event.target.value as FeatureFlagFilterValue<FeatureFlagScope>,
                )
              }
              value={scopeFilter}
            >
              <option value="all">all</option>
              {featureFlagScopes.map((scope) => (
                <option key={scope} value={scope}>
                  {scope}
                </option>
              ))}
            </select>
          </label>
        </div>

        <button
          aria-label="Refresh feature flags"
          className={styles.iconButtonSecondary}
          disabled={isLoading}
          onClick={() => void onRefresh()}
          title="Refresh feature flags"
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
              <th>Key</th>
              <th>Enabled</th>
              <th>Module</th>
              <th>Scope</th>
              <th>Fallback</th>
              <th>Description</th>
              <th>Updated</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {flags.length === 0 ? (
              <tr>
                <td className={styles.emptyCell} colSpan={8}>
                  {isLoading ? "Loading flags." : "No feature flags."}
                </td>
              </tr>
            ) : (
              flags.map((flag) => (
                <tr key={flag.id}>
                  <td className={styles.keyCell}>
                    <span>{flag.key}</span>
                    {editingId === flag.id ? (
                      <FeatureFlagEditor
                        flag={flag}
                        isSaving={isSavingEditor}
                        onCancel={onEditorCancel}
                        onSave={onEditorSave}
                      />
                    ) : null}
                  </td>
                  <td>
                    <FeatureFlagBadge enabled={flag.enabled} />
                  </td>
                  <td>
                    <span className={styles.moduleBadge} title={moduleLabels[flag.module]}>
                      {flag.module}
                    </span>
                  </td>
                  <td>
                    <span className={styles.scopeBadge}>{flag.scope}</span>
                  </td>
                  <td>
                    <span
                      className={`${styles.booleanBadge} ${
                        flag.fallback_value ? styles.enabled : styles.disabled
                      }`}
                    >
                      {String(flag.fallback_value)}
                    </span>
                  </td>
                  <td className={styles.descriptionCell}>{flag.description}</td>
                  <td>{formatTimestamp(flag.updated_at)}</td>
                  <td>
                    <div className={styles.rowActions}>
                      <button
                        aria-label={`Toggle ${flag.key}`}
                        className={styles.iconButton}
                        disabled={isTogglingId === flag.id}
                        onClick={() => void onToggle(flag)}
                        title="Toggle feature flag"
                        type="button"
                      >
                        {isTogglingId === flag.id ? (
                          <Loader2 aria-hidden="true" className="spin" size={15} />
                        ) : flag.enabled ? (
                          <ToggleRight aria-hidden="true" size={15} />
                        ) : (
                          <ToggleLeft aria-hidden="true" size={15} />
                        )}
                      </button>
                      <button
                        aria-label={`Edit ${flag.key}`}
                        className={styles.iconButtonSecondary}
                        disabled={editingId !== null}
                        onClick={() => onEdit(flag.id)}
                        title="Edit feature flag"
                        type="button"
                      >
                        <Edit3 aria-hidden="true" size={15} />
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

function formatTimestamp(value: string) {
  if (!value) {
    return "not set";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
