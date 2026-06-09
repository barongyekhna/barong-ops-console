"use client";

import { Activity, LoaderCircle, Play, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  latestFoundationDemo,
  runFoundationDemo,
  type FoundationDemoSnapshot,
} from "@/lib/foundation-demo-api";

export function FoundationDemoPanel() {
  const [snapshot, setSnapshot] = useState<FoundationDemoSnapshot | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);

  const loadLatest = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      setSnapshot(await latestFoundationDemo());
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 404) {
        setSnapshot(null);
      } else {
        setError(
          requestError instanceof ApiError
            ? requestError.message
            : "The foundation demo API is unavailable.",
        );
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadLatest();
  }, [loadLatest]);

  async function handleRun() {
    setIsRunning(true);
    setError("");
    try {
      setSnapshot(await runFoundationDemo());
    } catch (requestError) {
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "The demo exercise could not be recorded.",
      );
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <section className="demo-panel" aria-labelledby="foundation-demo-title">
      <div className="demo-panel-heading">
        <div className="demo-heading-copy">
          <span className="demo-badge">Demo only</span>
          <div>
            <h3 id="foundation-demo-title">Foundation Demo</h3>
            <p>
              Exercises the console data loop without triggering real n8n,
              WooCommerce, MinIO/Filebrowser, or P-series tasks.
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
          {isRunning ? "Recording demo" : "Run Foundation Demo"}
        </button>
      </div>

      {isLoading ? (
        <div className="demo-state" aria-label="Loading latest demo">
          <LoaderCircle className="spin" aria-hidden="true" size={20} />
          Loading the latest demo record
        </div>
      ) : null}

      {!isLoading && error ? (
        <div className="demo-state demo-state-error" role="alert">
          <div>
            <strong>Demo API request failed</strong>
            <span>{error}</span>
          </div>
          <button
            className="icon-button"
            onClick={() => void loadLatest()}
            title="Retry latest demo"
            type="button"
          >
            <RotateCcw aria-hidden="true" size={17} />
          </button>
        </div>
      ) : null}

      {!isLoading && !error && !snapshot ? (
        <div className="demo-state">
          <Activity aria-hidden="true" size={20} />
          No demo exercise has been recorded.
        </div>
      ) : null}

      {!isLoading && !error && snapshot ? (
        <div className="demo-result" aria-label="Latest foundation demo">
          <div className="demo-result-heading">
            <span>Latest exercise</span>
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
              <dt>Events</dt>
              <dd>{snapshot.events_count}</dd>
            </div>
            <div>
              <dt>Artifact title</dt>
              <dd>{snapshot.artifact?.title ?? "Not recorded"}</dd>
            </div>
            <div>
              <dt>Review status</dt>
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
        </div>
      ) : null}
    </section>
  );
}
