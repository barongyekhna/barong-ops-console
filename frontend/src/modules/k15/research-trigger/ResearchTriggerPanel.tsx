"use client";

import { Loader2, Search } from "lucide-react";
import { useState } from "react";

import { startKeywordResearch } from "./api";
import styles from "./ResearchTriggerPanel.module.css";
import type { ResearchRun, ResearchTriggerUiState } from "./types";

const statusFlow: ResearchTriggerUiState[] = [
  "idle",
  "pending",
  "running",
  "completed",
];

const defaultProductId = "k-series-product-knowledge-001";

export function ResearchTriggerPanel() {
  const [productId, setProductId] = useState(defaultProductId);
  const [uiState, setUiState] = useState<ResearchTriggerUiState>("idle");
  const [researchRun, setResearchRun] = useState<ResearchRun | null>(null);
  const [error, setError] = useState("");

  async function handleStartResearch() {
    const normalizedProductId = productId.trim();

    if (!normalizedProductId) {
      setError("Product id is required to start keyword research.");
      return;
    }

    setError("");
    setResearchRun(null);
    setUiState("pending");

    try {
      setUiState("running");
      const run = await startKeywordResearch(normalizedProductId);
      setResearchRun(run);
      setUiState("completed");
    } catch (caught) {
      setUiState("idle");
      setError(
        caught instanceof Error
          ? caught.message
          : "Keyword research could not be started.",
      );
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="research-trigger">
      <div className={styles.heading}>
        <div>
          <span className="section-index">Research</span>
          <h3 id="research-trigger">Keyword Research Trigger</h3>
          <p>
            Start a keyword research run for a product record and track the
            latest run state.
          </p>
        </div>
      </div>

      <div className={styles.form}>
        <label className={styles.field}>
          <span>Product id</span>
          <input
            onChange={(event) => setProductId(event.target.value)}
            placeholder="product uuid or product key"
            type="text"
            value={productId}
          />
        </label>

        <button
          className="primary-button"
          disabled={uiState === "pending" || uiState === "running"}
          onClick={() => void handleStartResearch()}
          type="button"
        >
          {uiState === "pending" || uiState === "running" ? (
            <Loader2 aria-hidden="true" className="spin" size={16} />
          ) : (
            <Search aria-hidden="true" size={16} />
          )}
          Start Keyword Research
        </button>
      </div>

      <ol className={styles.statusRail} aria-label="Keyword research state flow">
        {statusFlow.map((status) => (
          <li className={getStatusClass(status, uiState)} key={status}>
            {status}
          </li>
        ))}
      </ol>

      {researchRun ? <ResearchRunSummary researchRun={researchRun} /> : null}

      <p className={`${styles.message} ${error ? styles.error : ""}`}>
        {error || statusMessageFor(uiState)}
      </p>
    </section>
  );
}

function ResearchRunSummary({ researchRun }: { researchRun: ResearchRun }) {
  return (
    <dl className={styles.resultGrid}>
      <div>
        <dt>Run id</dt>
        <dd>{researchRun.id}</dd>
      </div>
      <div>
        <dt>Status</dt>
        <dd>{researchRun.status}</dd>
      </div>
      <div>
        <dt>Timestamp</dt>
        <dd>{formatTimestamp(researchRun.updated_at)}</dd>
      </div>
    </dl>
  );
}

function getStatusClass(
  status: ResearchTriggerUiState,
  currentStatus: ResearchTriggerUiState,
) {
  const statusIndex = statusFlow.indexOf(status);
  const currentIndex = statusFlow.indexOf(currentStatus);

  if (status === currentStatus) {
    return `${styles.statusStep} ${styles.statusStepActive}`;
  }

  if (statusIndex < currentIndex) {
    return `${styles.statusStep} ${styles.statusStepComplete}`;
  }

  return styles.statusStep;
}

function statusMessageFor(status: ResearchTriggerUiState) {
  if (status === "pending") {
    return "Keyword research start request is pending.";
  }

  if (status === "running") {
    return "Keyword research run is being created.";
  }

  if (status === "completed") {
    return "Keyword research run has completed.";
  }

  return "Idle. No keyword research run has been started.";
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
