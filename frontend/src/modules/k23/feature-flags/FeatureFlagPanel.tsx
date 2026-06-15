"use client";

import { Loader2, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getFeatureFlags, updateFeatureFlag } from "./api";
import styles from "./FeatureFlagPanel.module.css";
import { FeatureFlagTable } from "./FeatureFlagTable";
import type {
  FeatureFlag,
  FeatureFlagFilterValue,
  FeatureFlagModule,
  FeatureFlagScope,
  UpdateFeatureFlagPayload,
} from "./types";

export function FeatureFlagPanel() {
  const [flags, setFlags] = useState<FeatureFlag[]>([]);
  const [moduleFilter, setModuleFilter] =
    useState<FeatureFlagFilterValue<FeatureFlagModule>>("all");
  const [scopeFilter, setScopeFilter] =
    useState<FeatureFlagFilterValue<FeatureFlagScope>>("all");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSavingEditor, setIsSavingEditor] = useState(false);
  const [isTogglingId, setIsTogglingId] = useState<string | null>(null);
  const [message, setMessage] = useState("Ready.");
  const [error, setError] = useState("");

  useEffect(() => {
    void loadFeatureFlags();
  }, []);

  const filteredFlags = useMemo(
    () =>
      flags.filter((flag) => {
        if (moduleFilter !== "all" && flag.module !== moduleFilter) {
          return false;
        }
        if (scopeFilter !== "all" && flag.scope !== scopeFilter) {
          return false;
        }
        return true;
      }),
    [flags, moduleFilter, scopeFilter],
  );

  const enabledCount = useMemo(
    () => filteredFlags.filter((flag) => flag.enabled).length,
    [filteredFlags],
  );

  async function loadFeatureFlags() {
    setIsLoading(true);
    setError("");

    try {
      const response = await getFeatureFlags();
      setFlags(response.feature_flags);
      setMessage(`${response.feature_flags.length} feature flags loaded.`);
    } catch (caught) {
      setFlags([]);
      setError(
        caught instanceof Error
          ? caught.message
          : "Feature flags could not be loaded.",
      );
      setMessage("");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleToggle(flag: FeatureFlag) {
    setIsTogglingId(flag.id);
    setError("");

    try {
      const response = await updateFeatureFlag(flag.id, {
        enabled: !flag.enabled,
      });
      setFlags((currentFlags) =>
        upsertFlag(currentFlags, response.feature_flag),
      );
      setMessage("Feature flag updated.");
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Feature flag could not be updated.",
      );
      setMessage("");
    } finally {
      setIsTogglingId(null);
    }
  }

  async function handleEditorSave(
    flagId: string,
    payload: UpdateFeatureFlagPayload,
  ) {
    setIsSavingEditor(true);
    setError("");

    try {
      const response = await updateFeatureFlag(flagId, payload);
      setFlags((currentFlags) =>
        upsertFlag(currentFlags, response.feature_flag),
      );
      setEditingId(null);
      setMessage("Feature flag metadata updated.");
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Feature flag could not be updated.",
      );
      setMessage("");
    } finally {
      setIsSavingEditor(false);
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="k23-feature-flag-panel">
      <div className={styles.heading}>
        <div className={styles.headingTitle}>
          <SlidersHorizontal aria-hidden="true" size={20} />
          <div>
            <span className="section-index">K23</span>
            <h3 id="k23-feature-flag-panel">Feature Flags</h3>
          </div>
        </div>
        <div className={styles.summary}>
          <strong>{enabledCount}</strong>
          <span>{filteredFlags.length} visible</span>
        </div>
      </div>

      <FeatureFlagTable
        editingId={editingId}
        flags={filteredFlags}
        isLoading={isLoading}
        isSavingEditor={isSavingEditor}
        isTogglingId={isTogglingId}
        moduleFilter={moduleFilter}
        onEdit={setEditingId}
        onEditorCancel={() => setEditingId(null)}
        onEditorSave={handleEditorSave}
        onModuleFilterChange={setModuleFilter}
        onRefresh={loadFeatureFlags}
        onScopeFilterChange={setScopeFilter}
        onToggle={handleToggle}
        scopeFilter={scopeFilter}
      />

      <p className={`${styles.message} ${error ? styles.error : ""}`}>
        {isLoading ? (
          <>
            <Loader2 aria-hidden="true" className="spin" size={14} />
            Loading feature flags.
          </>
        ) : (
          error || message
        )}
      </p>
    </section>
  );
}

function upsertFlag(flags: FeatureFlag[], nextFlag: FeatureFlag) {
  const existingIndex = flags.findIndex((flag) => flag.id === nextFlag.id);

  if (existingIndex === -1) {
    return [nextFlag, ...flags];
  }

  return flags.map((flag, index) =>
    index === existingIndex ? nextFlag : flag,
  );
}
