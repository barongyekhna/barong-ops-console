"use client";

import { Activity, LoaderCircle, Play, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  latestN8nTest,
  runN8nTest,
  type N8nTestSnapshot,
} from "@/lib/n8n-test-api";

const POLLING_STATUSES = new Set(["pending", "running", "waiting_callback"]);

export function N8nTestPanel() {
  const [snapshot, setSnapshot] = useState<N8nTestSnapshot | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);

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
            : "The n8n test bridge API is unavailable.",
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

  async function handleRun() {
    setIsRunning(true);
    setError("");
    try {
      setSnapshot(await runN8nTest());
    } catch (requestError) {
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "The n8n test webhook could not be called.",
      );
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <section className="demo-panel" aria-labelledby="n8n-test-title">
      <div className="demo-panel-heading">
        <div className="demo-heading-copy">
          <span className="demo-badge">Test only</span>
          <div>
            <h3 id="n8n-test-title">n8n Test Webhook Bridge</h3>
            <p>
              Test bridge only. Does not run real n8n production workflows. It sends no real product or commerce payloads and triggers no downstream business work.
            </p>
          </div>
        </div>
        <button
          className="primary-button"
          disabled={isLoading || isRunning}
          onClick={() => void handleRun()}
          type="button"
        >
          {isRunning ? (
            <LoaderCircle className="spin" aria-hidden="true" size={17} />
          ) : (
            <Play aria-hidden="true" size={17} />
          )}
          {isRunning ? "Calling test webhook" : "Run n8n Test"}
        </button>
      </div>

      {isLoading ? (
        <div className="demo-state" aria-label="Loading latest n8n test">
          <LoaderCircle className="spin" aria-hidden="true" size={20} />
          Loading the latest n8n test run
        </div>
      ) : null}

      {!isLoading && error ? (
        <div className="demo-state demo-state-error" role="alert">
          <div>
            <strong>n8n test bridge request failed</strong>
            <span>{error}</span>
          </div>
          <button
            className="icon-button"
            onClick={() => void loadLatest()}
            title="Retry latest n8n test"
            type="button"
          >
            <RotateCcw aria-hidden="true" size={17} />
          </button>
        </div>
      ) : null}

      {!isLoading && !error && !snapshot ? (
        <div className="demo-state">
          <Activity aria-hidden="true" size={20} />
          No n8n test bridge run has been recorded.
        </div>
      ) : null}

      {!isLoading && !error && snapshot ? (
        <div className="demo-result" aria-label="Latest n8n test bridge run">
          <div className="demo-result-heading">
            <span>Latest test run</span>
            <strong>{snapshot.job.status}</strong>
          </div>
          <dl className="demo-result-grid">
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
          <div className="demo-memory">
            <span>Memory event summary</span>
            <p>{snapshot.memory_event?.summary ?? "Not recorded"}</p>
          </div>
          {snapshot.error ? (
            <div className="demo-memory demo-error-summary">
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
