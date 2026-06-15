"use client";

import { Check, Loader2, X } from "lucide-react";
import { useState } from "react";

import styles from "./FeatureFlagPanel.module.css";
import type {
  FeatureFlag,
  FeatureFlagScope,
  UpdateFeatureFlagPayload,
} from "./types";
import { featureFlagScopes } from "./types";

type FeatureFlagEditorProps = {
  flag: FeatureFlag;
  isSaving: boolean;
  onCancel: () => void;
  onSave: (
    flagId: string,
    payload: UpdateFeatureFlagPayload,
  ) => Promise<void>;
};

export function FeatureFlagEditor({
  flag,
  isSaving,
  onCancel,
  onSave,
}: FeatureFlagEditorProps) {
  const [description, setDescription] = useState(flag.description);
  const [enabled, setEnabled] = useState(flag.enabled);
  const [fallbackValue, setFallbackValue] = useState(flag.fallback_value);
  const [scope, setScope] = useState<FeatureFlagScope>(flag.scope);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSave(flag.id, {
      description,
      enabled,
      fallback_value: fallbackValue,
      scope,
    });
  }

  return (
    <form
      className={styles.editor}
      onSubmit={(event) => void handleSubmit(event)}
    >
      <label className={styles.field}>
        <span>Description</span>
        <input
          onChange={(event) => setDescription(event.target.value)}
          type="text"
          value={description}
        />
      </label>

      <label className={styles.field}>
        <span>Scope</span>
        <select
          onChange={(event) => setScope(event.target.value as FeatureFlagScope)}
          value={scope}
        >
          {featureFlagScopes.map((nextScope) => (
            <option key={nextScope} value={nextScope}>
              {nextScope}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.field}>
        <span>Enabled</span>
        <select
          onChange={(event) => setEnabled(event.target.value === "true")}
          value={String(enabled)}
        >
          <option value="true">enabled</option>
          <option value="false">disabled</option>
        </select>
      </label>

      <label className={styles.field}>
        <span>Fallback</span>
        <select
          onChange={(event) => setFallbackValue(event.target.value === "true")}
          value={String(fallbackValue)}
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      </label>

      <div className={styles.editorActions}>
        <button
          aria-label="Save feature flag"
          className={styles.iconButton}
          disabled={isSaving}
          title="Save feature flag"
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
