"use client";

import { Activity, LoaderCircle, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  latestN8nTest,
  type N8nTestSnapshot,
} from "@/lib/n8n-test-api";

const POLLING_STATUSES = new Set(["pending", "running"]);

export function N8nTestPanel() {
  const [snapshot, setSnapshot] = useState<N8nTestSnapshot | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  const loadLatest = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setIsLoading(true);
    }
    setError("");
    try {
      setSnapshot(await latestN8nTest());
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 404) {
        setSnapshot(null);
      } else {
        setError(
          requestError instanceof ApiError
            ? requestError.message
            : "The diagnostic status API is unavailable.",
        );
      }
    } finally {
      if (showLoading) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadLatest();
  }, [loadLatest]);

  useEffect(() => {
    if (!snapshot || !POLLING_STATUSES.has(snapshot.job.status)) {
      return;
    }
    const timer = window.setTimeout(() => {
      void loadLatest(false);
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [loadLatest, snapshot]);

  return (
    <section className="diagnostic-panel" aria-labelledby="n8n-test-title">
      <div className="diagnostic-panel-heading">
        <div className="diagnostic-heading-copy">
          <span className="diagnostic-badge">Internal</span>
          <div>
            <h3 id="n8n-test-title">Bridge diagnostic status</h3>
            <p>
              Read-only diagnostic status. Product navigation does not expose
              this route and this panel cannot create execution results.
            </p>
          </div>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void loadLatest()}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={17} />
          Refresh status
        </button>
      </div>

      {isLoading ? (
        <div className="diagnostic-state" aria-label="Loading latest diagnostic status">
          <LoaderCircle className="spin" aria-hidden="true" size={20} />
          Loading diagnostic status
        </div>
      ) : null}

      {!isLoading && error ? (
        <div className="diagnostic-state diagnostic-state-error" role="alert">
          <div>
            <strong>Diagnostic status request failed</strong>
            <span>{error}</span>
          </div>
          <button
            className="icon-button"
            onClick={() => void loadLatest()}
            title="Retry diagnostic status"
            type="button"
          >
            <RotateCcw aria-hidden="true" size={17} />
          </button>
        </div>
      ) : null}

      {!isLoading && !error && !snapshot ? (
        <div className="diagnostic-state">
          <Activity aria-hidden="true" size={20} />
          No diagnostic status has been recorded.
        </div>
      ) : null}

      {!isLoading && !error && snapshot ? (
        <div className="diagnostic-result" aria-label="Latest diagnostic bridge status">
          <div className="diagnostic-result-heading">
            <span>Latest diagnostic record</span>
            <strong>{snapshot.job.status}</strong>
          </div>
          <dl className="diagnostic-result-grid">
            <div>
              <dt>Job ID</dt>
              <dd>{snapshot.job.job_id}</dd>
            </div>
            <div>
              <dt>Job status</dt>
              <dd>{snapshot.job.status}</dd>
            </div>
            <div>
              <dt>Latest event</dt>
              <dd>{snapshot.latest_event?.event_type ?? "Not recorded"}</dd>
            </div>
            <div>
              <dt>Artifact</dt>
              <dd>{snapshot.artifact?.title ?? "Not recorded"}</dd>
            </div>
            <div>
              <dt>Review</dt>
              <dd>{snapshot.review?.status ?? "Not recorded"}</dd>
            </div>
            <div>
              <dt>Operation logs</dt>
              <dd>{snapshot.operation_log_count}</dd>
            </div>
          </dl>
          <div className="diagnostic-memory">
            <span>Memory event summary</span>
            <p>{snapshot.memory_event?.summary ?? "Not recorded"}</p>
          </div>
          {snapshot.error ? (
            <div className="diagnostic-memory diagnostic-error-summary">
              <span>Test error</span>
              <p>
                {snapshot.error.error_code}: {snapshot.error.message}
              </p>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
