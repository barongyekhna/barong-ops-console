"use client";

import { Loader2, Plus, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { createRisk, deleteRisk, getRisks, updateRisk } from "./api";
import styles from "./RiskPanel.module.css";
import { RiskTable } from "./RiskTable";
import type {
  CreateRiskPayload,
  RiskCategory,
  RiskLevel,
  RiskSource,
  RiskStatus,
  RiskTerm,
  UpdateRiskPayload,
} from "./types";
import {
  riskCategories,
  riskLevels,
  riskSources,
  riskStatuses,
  sourceLabels,
} from "./types";

const defaultProductId = "k-series-product-knowledge-001";

type RiskFilterValue<T extends string> = T | "all";

export function RiskPanel() {
  const [entries, setEntries] = useState<RiskTerm[]>([]);
  const [term, setTerm] = useState("");
  const [productId, setProductId] = useState(defaultProductId);
  const [riskLevel, setRiskLevel] = useState<RiskLevel>("low");
  const [category, setCategory] = useState<RiskCategory>("marketing");
  const [source, setSource] = useState<RiskSource>("manual");
  const [status, setStatus] = useState<RiskStatus>("active");
  const [levelFilter, setLevelFilter] =
    useState<RiskFilterValue<RiskLevel>>("all");
  const [categoryFilter, setCategoryFilter] =
    useState<RiskFilterValue<RiskCategory>>("all");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isSavingEditor, setIsSavingEditor] = useState(false);
  const [isResolvingId, setIsResolvingId] = useState<string | null>(null);
  const [isIgnoringId, setIsIgnoringId] = useState<string | null>(null);
  const [message, setMessage] = useState("Ready.");
  const [error, setError] = useState("");

  useEffect(() => {
    void loadRisks();
  }, []);

  const filteredEntries = useMemo(
    () =>
      entries.filter((entry) => {
        if (levelFilter !== "all" && entry.risk_level !== levelFilter) {
          return false;
        }
        if (categoryFilter !== "all" && entry.category !== categoryFilter) {
          return false;
        }
        return true;
      }),
    [categoryFilter, entries, levelFilter],
  );

  async function loadRisks() {
    setIsLoading(true);
    setError("");

    try {
      const response = await getRisks();
      setEntries(response.risk_terms);
      setMessage(`${response.risk_terms.length} risk terms loaded.`);
    } catch (caught) {
      setEntries([]);
      setError(caught instanceof Error ? caught.message : "Risks could not be loaded.");
      setMessage("");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const payload: CreateRiskPayload = {
      category,
      product_id: productId,
      risk_level: riskLevel,
      source,
      status,
      term,
    };

    setIsCreating(true);
    setError("");

    try {
      const response = await createRisk(payload);
      setEntries((currentEntries) =>
        upsertEntry(currentEntries, response.risk_term),
      );
      setTerm("");
      setProductId(response.risk_term.product_id);
      setMessage("Risk term created.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Risk could not be created.");
      setMessage("");
    } finally {
      setIsCreating(false);
    }
  }

  async function handleEditorSave(
    riskId: string,
    payload: UpdateRiskPayload,
  ) {
    setIsSavingEditor(true);
    setError("");

    try {
      const response = await updateRisk(riskId, payload);
      setEntries((currentEntries) =>
        upsertEntry(currentEntries, response.risk_term),
      );
      setEditingId(null);
      setMessage("Risk term updated.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Risk could not be updated.");
      setMessage("");
    } finally {
      setIsSavingEditor(false);
    }
  }

  async function handleResolve(riskId: string) {
    setIsResolvingId(riskId);
    setError("");

    try {
      const response = await updateRisk(riskId, { status: "resolved" });
      setEntries((currentEntries) =>
        upsertEntry(currentEntries, response.risk_term),
      );
      setEditingId(null);
      setMessage("Risk term resolved.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Risk could not be resolved.");
      setMessage("");
    } finally {
      setIsResolvingId(null);
    }
  }

  async function handleIgnore(riskId: string) {
    setIsIgnoringId(riskId);
    setError("");

    try {
      const response = await deleteRisk(riskId);
      setEntries((currentEntries) =>
        upsertEntry(currentEntries, response.risk_term),
      );
      setEditingId(null);
      setMessage("Risk term ignored.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Risk could not be ignored.");
      setMessage("");
    } finally {
      setIsIgnoringId(null);
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="k20-risk-panel">
      <div className={styles.heading}>
        <div className={styles.headingTitle}>
          <ShieldAlert aria-hidden="true" size={20} />
          <div>
            <span className="section-index">K20</span>
            <h3 id="k20-risk-panel">Risk Governance</h3>
          </div>
        </div>
        <div className={styles.summary}>
          <strong>{filteredEntries.length}</strong>
          <span>visible</span>
        </div>
      </div>

      <form className={styles.inputBar} onSubmit={(event) => void handleCreate(event)}>
        <label className={styles.field}>
          <span>Term</span>
          <input
            onChange={(event) => setTerm(event.target.value)}
            placeholder="risk term"
            type="text"
            value={term}
          />
        </label>

        <label className={styles.field}>
          <span>Product id</span>
          <input
            onChange={(event) => setProductId(event.target.value)}
            placeholder="product id"
            type="text"
            value={productId}
          />
        </label>

        <label className={styles.field}>
          <span>Risk level</span>
          <select
            onChange={(event) => setRiskLevel(event.target.value as RiskLevel)}
            value={riskLevel}
          >
            {riskLevels.map((nextRiskLevel) => (
              <option key={nextRiskLevel} value={nextRiskLevel}>
                {nextRiskLevel}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>Category</span>
          <select
            onChange={(event) => setCategory(event.target.value as RiskCategory)}
            value={category}
          >
            {riskCategories.map((nextCategory) => (
              <option key={nextCategory} value={nextCategory}>
                {nextCategory}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>Source</span>
          <select
            onChange={(event) => setSource(event.target.value as RiskSource)}
            value={source}
          >
            {riskSources.map((nextSource) => (
              <option key={nextSource} value={nextSource}>
                {sourceLabels[nextSource]}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>Status</span>
          <select
            onChange={(event) => setStatus(event.target.value as RiskStatus)}
            value={status}
          >
            {riskStatuses.map((nextStatus) => (
              <option key={nextStatus} value={nextStatus}>
                {nextStatus}
              </option>
            ))}
          </select>
        </label>

        <button
          className={styles.iconTextButton}
          disabled={isCreating || !term.trim() || !productId.trim()}
          type="submit"
        >
          {isCreating ? (
            <Loader2 aria-hidden="true" className="spin" size={16} />
          ) : (
            <Plus aria-hidden="true" size={16} />
          )}
          Add
        </button>
      </form>

      <RiskTable
        categoryFilter={categoryFilter}
        editingId={editingId}
        entries={filteredEntries}
        isIgnoringId={isIgnoringId}
        isLoading={isLoading}
        isResolvingId={isResolvingId}
        isSavingEditor={isSavingEditor}
        levelFilter={levelFilter}
        onCategoryFilterChange={setCategoryFilter}
        onEdit={setEditingId}
        onEditorCancel={() => setEditingId(null)}
        onEditorSave={handleEditorSave}
        onIgnore={handleIgnore}
        onLevelFilterChange={setLevelFilter}
        onRefresh={loadRisks}
        onResolve={handleResolve}
      />

      <p className={`${styles.message} ${error ? styles.error : ""}`}>
        {isLoading ? (
          <>
            <Loader2 aria-hidden="true" className="spin" size={14} />
            Loading risks.
          </>
        ) : (
          error || message
        )}
      </p>
    </section>
  );
}

function upsertEntry(entries: RiskTerm[], nextEntry: RiskTerm) {
  const existingIndex = entries.findIndex((entry) => entry.id === nextEntry.id);

  if (existingIndex === -1) {
    return [nextEntry, ...entries];
  }

  return entries.map((entry, index) =>
    index === existingIndex ? nextEntry : entry,
  );
}
