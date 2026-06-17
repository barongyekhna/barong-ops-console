"use client";

import {
  Activity,
  Bell,
  CircleAlert,
  FileSearch,
  LoaderCircle,
  RotateCcw,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { CapabilityEmptyStateEngine } from "@/components/capability-empty-state";
import { ApiError, apiRequest } from "@/lib/api";

type ListResponse<T> = {
  items: T[];
  count: number;
  limit: number;
  offset: number;
};

type OperationLogRecord = {
  operation_id?: string;
  action?: string;
  target_type?: string;
  target_id?: string;
  job_id?: string | null;
  result?: string;
  error_code?: string | null;
  request_id?: string | null;
  details?: Record<string, unknown> | null;
  created_at?: string;
};

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value : null;
}

function traceKey(log: OperationLogRecord) {
  const details = log.details ?? {};
  return (
    stringValue(details.trace_id) ??
    stringValue(details.context_id) ??
    stringValue(log.request_id) ??
    stringValue(log.job_id) ??
    null
  );
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "Not recorded";
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

function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "C17 operation log API is unavailable.";
}

function isFailedLog(log: OperationLogRecord) {
  return log.result === "error" || Boolean(log.error_code);
}

function actionLabel(log: OperationLogRecord) {
  return log.action ?? log.target_type ?? "Unknown operation";
}

export function C17ObservabilityCenter() {
  const [result, setResult] = useState<ListResponse<OperationLogRecord> | null>(
    null,
  );
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      setResult(
        await apiRequest<ListResponse<OperationLogRecord>>(
          "/operation-logs?limit=24&offset=0",
          { method: "GET" },
        ),
      );
    } catch (requestError) {
      setResult(null);
      setError(errorMessage(requestError));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const logs = result?.items ?? [];
  const failedLogs = logs.filter(isFailedLog);
  const traces = useMemo(
    () =>
      Array.from(
        new Map(
          logs
            .map((log) => [traceKey(log), log] as const)
            .filter(([key]) => Boolean(key)),
        ).entries(),
      ),
    [logs],
  );
  const actionCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const log of logs) {
      const key = actionLabel(log);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .filter(([, count]) => count >= 3)
      .sort((left, right) => right[1] - left[1]);
  }, [logs]);
  const missingTraceCount = logs.filter((log) => !traceKey(log)).length;

  if (isLoading) {
    return (
      <section className="list-state" aria-label="Loading C17 observability">
        <LoaderCircle className="spin" aria-hidden="true" size={22} />
        <span>Loading C17 observability</span>
      </section>
    );
  }

  if (error) {
    return (
      <CapabilityEmptyStateEngine
        action={
          <button className="primary-button" onClick={() => void load()}>
            <RotateCcw aria-hidden="true" size={17} />
            Retry
          </button>
        }
        reason={error}
        required_execution_mode="Read-only C17 observability API."
        required_module_state="system.operation_logs sealed and visible."
        required_org_state="Active org context accepted by operation log API."
        required_permission="operation_logs.read"
        state="backend_unavailable"
        title="C17 observability unavailable"
        unlock_condition="Restore /operation-logs or grant operation_logs.read."
      />
    );
  }

  return (
    <section className="observability-workspace" aria-label="C17 observability">
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">C17 Observability</span>
          <h2>Logs, traces, alerts, and anomaly signals</h2>
          <p>
            Unified read surface for operation logs, trace correlation, alert
            candidates, and anomaly signals derived from the C17 log stream.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void load()}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={17} />
          Refresh
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>Operation logs</span>
          <strong>{result?.count ?? 0}</strong>
        </div>
        <div>
          <span>Trace groups</span>
          <strong>{traces.length}</strong>
        </div>
        <div>
          <span>Alerts</span>
          <strong>{failedLogs.length}</strong>
        </div>
        <div>
          <span>Anomaly signals</span>
          <strong>{actionCounts.length + (missingTraceCount > 0 ? 1 : 0)}</strong>
        </div>
      </div>

      <div className="observability-grid">
        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Operation logs</h3>
              <p>Recent durable operation records from the backend.</p>
            </div>
            <span className="ops-source">/operation-logs</span>
          </div>
          <ol className="ops-record-list">
            {logs.slice(0, 8).map((log) => (
              <li key={log.operation_id ?? `${log.action}-${log.created_at}`}>
                <span>{log.result ?? "unknown"}</span>
                <strong>{actionLabel(log)}</strong>
                <small>
                  {log.target_type ?? "target"} / {formatDate(log.created_at)}
                </small>
              </li>
            ))}
            {logs.length === 0 ? (
              <li>
                <span>empty</span>
                <strong>No operation logs recorded.</strong>
                <small>C17 returned zero records.</small>
              </li>
            ) : null}
          </ol>
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Traces</h3>
              <p>Trace groups derived from trace, context, request, or job IDs.</p>
            </div>
            <span className="ops-source">C17 correlation</span>
          </div>
          <div className="ops-trace-grid">
            {traces.slice(0, 8).map(([key, log]) => (
              <div key={key ?? log.operation_id}>
                <FileSearch aria-hidden="true" size={17} />
                <strong>{key}</strong>
                <span>{actionLabel(log)}</span>
              </div>
            ))}
            {traces.length === 0 ? (
              <div>
                <CircleAlert aria-hidden="true" size={17} />
                <strong>No trace groups found.</strong>
                <span>Logs need trace, context, request, or job IDs.</span>
              </div>
            ) : null}
          </div>
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Alerts</h3>
              <p>Alert candidates from failed operation records.</p>
            </div>
            <span className="ops-source">C17 alert projection</span>
          </div>
          <ol className="ops-record-list">
            {failedLogs.slice(0, 6).map((log) => (
              <li key={log.operation_id ?? `${log.action}-${log.error_code}`}>
                <span>{log.error_code ?? "error"}</span>
                <strong>{actionLabel(log)}</strong>
                <small>{traceKey(log) ?? "No trace ID"}</small>
              </li>
            ))}
            {failedLogs.length === 0 ? (
              <li>
                <span>clear</span>
                <strong>No alert candidates in the latest page.</strong>
                <small>Failed logs and error codes appear here.</small>
              </li>
            ) : null}
          </ol>
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Anomaly signals</h3>
              <p>Signals derived from repeated actions and missing trace data.</p>
            </div>
            <span className="ops-source">C17 anomaly projection</span>
          </div>
          <ol className="ops-record-list">
            {actionCounts.slice(0, 5).map(([action, count]) => (
              <li key={action}>
                <span>volume</span>
                <strong>{action}</strong>
                <small>{count} records in the latest page</small>
              </li>
            ))}
            {missingTraceCount > 0 ? (
              <li>
                <span>trace</span>
                <strong>Missing trace correlation</strong>
                <small>{missingTraceCount} records have no trace key.</small>
              </li>
            ) : null}
            {actionCounts.length === 0 && missingTraceCount === 0 ? (
              <li>
                <span>clear</span>
                <strong>No anomaly signals in the latest page.</strong>
                <small>Repeated actions and missing trace data appear here.</small>
              </li>
            ) : null}
          </ol>
        </article>
      </div>

      <div className="observability-band">
        <Bell aria-hidden="true" size={18} />
        <span>Operation logs</span>
        <Activity aria-hidden="true" size={18} />
        <span>Traces</span>
        <CircleAlert aria-hidden="true" size={18} />
        <span>Alerts</span>
        <FileSearch aria-hidden="true" size={18} />
        <span>Anomaly signals</span>
      </div>
    </section>
  );
}
