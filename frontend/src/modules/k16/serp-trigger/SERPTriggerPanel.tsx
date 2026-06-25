"use client";

import { Globe2, Loader2 } from "lucide-react";
import { useState } from "react";

import { runSERPSearch } from "./api";
import styles from "./SERPTriggerPanel.module.css";
import type { SERPResult, SERPTriggerState } from "./types";

const statusFlow: SERPTriggerState[] = [
  "idle",
  "loading",
  "completed",
  "failed",
];

const productOptions = [
  {
    label: "K-series product knowledge 001",
    value: "k-series-product-knowledge-001",
  },
  {
    label: "Manual product id",
    value: "manual-product-id",
  },
];

const marketOptions = ["amazon", "shopify", "tiktok_shop", "general"];

export function SERPTriggerPanel() {
  const [productId, setProductId] = useState(productOptions[0].value);
  const [market, setMarket] = useState(marketOptions[0]);
  const [query, setQuery] = useState("kids stainless steel water bottle");
  const [state, setState] = useState<SERPTriggerState>("idle");
  const [serpResult, setSerpResult] = useState<SERPResult | null>(null);
  const [error, setError] = useState("");

  async function handleRunSearch() {
    const normalizedProductId = productId.trim();
    const normalizedQuery = query.trim();

    if (!normalizedProductId || !normalizedQuery) {
      setState("failed");
      setError("Product and query are required to run a SERP search.");
      return;
    }

    setState("loading");
    setSerpResult(null);
    setError("");

    try {
      const result = await runSERPSearch({
        product_id: normalizedProductId,
        market,
        query: normalizedQuery,
      });
      setSerpResult(result);
      setState("completed");
    } catch (caught) {
      setState("failed");
      setError(
        caught instanceof Error ? caught.message : "SERP search could not run.",
      );
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="serp-trigger">
      <div className={styles.heading}>
        <div>
          <span className="section-index">SERP</span>
          <h3 id="serp-trigger">SERP Search Trigger</h3>
          <p>
            Select a product and market, then run a market search request for
            the future SERP result pipeline.
          </p>
        </div>
      </div>

      <div className={styles.form}>
        <label className={styles.field}>
          <span>Product</span>
          <select
            onChange={(event) => setProductId(event.target.value)}
            value={productId}
          >
            {productOptions.map((product) => (
              <option key={product.value} value={product.value}>
                {product.label}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>Market</span>
          <select
            onChange={(event) => setMarket(event.target.value)}
            value={market}
          >
            {marketOptions.map((marketOption) => (
              <option key={marketOption} value={marketOption}>
                {marketOption}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>Query</span>
          <input
            onChange={(event) => setQuery(event.target.value)}
            placeholder="market query"
            type="text"
            value={query}
          />
        </label>

        <button
          className="primary-button"
          disabled={state === "loading"}
          onClick={() => void handleRunSearch()}
          type="button"
        >
          {state === "loading" ? (
            <Loader2 aria-hidden="true" className="spin" size={16} />
          ) : (
            <Globe2 aria-hidden="true" size={16} />
          )}
          Run SERP Search
        </button>
      </div>

      <ol className={styles.statusRail} aria-label="SERP trigger state flow">
        {statusFlow.map((status) => (
          <li className={getStatusClass(status, state)} key={status}>
            {status}
          </li>
        ))}
      </ol>

      {serpResult ? <SERPResultSummary serpResult={serpResult} /> : null}

      <p className={`${styles.message} ${error ? styles.error : ""}`}>
        {error || statusMessageFor(state)}
      </p>
    </section>
  );
}

function SERPResultSummary({ serpResult }: { serpResult: SERPResult }) {
  return (
    <div className={styles.result}>
      <dl className={styles.resultGrid}>
        <div>
          <dt>Result id</dt>
          <dd>{serpResult.id}</dd>
        </div>
        <div>
          <dt>Market</dt>
          <dd>{serpResult.market}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{formatTimestamp(serpResult.updated_at)}</dd>
        </div>
      </dl>

      <TagGroup label="Keywords" values={serpResult.keywords} />
      <TagGroup label="Competitor Links" values={serpResult.competitor_links} />
    </div>
  );
}

function TagGroup({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) {
    return null;
  }

  return (
    <div className={styles.tagGroup}>
      <span>{label}</span>
      <div>
        {values.map((value) => (
          <strong key={value}>{value}</strong>
        ))}
      </div>
    </div>
  );
}

function getStatusClass(
  status: SERPTriggerState,
  currentStatus: SERPTriggerState,
) {
  if (status === currentStatus) {
    return `${styles.statusStep} ${
      status === "failed" ? styles.statusStepFailed : styles.statusStepActive
    }`;
  }

  const statusIndex = statusFlow.indexOf(status);
  const currentIndex = statusFlow.indexOf(currentStatus);

  if (currentStatus !== "failed" && statusIndex < currentIndex) {
    return `${styles.statusStep} ${styles.statusStepComplete}`;
  }

  return styles.statusStep;
}

function statusMessageFor(status: SERPTriggerState) {
  if (status === "loading") {
    return "SERP search request is running.";
  }

  if (status === "completed") {
    return "SERP result has been received.";
  }

  if (status === "failed") {
    return "SERP search failed.";
  }

  return "Idle. No SERP search has been run.";
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
