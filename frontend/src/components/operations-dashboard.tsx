"use client";

import {
  Activity,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Database,
  FileSearch,
  GitBranch,
  LoaderCircle,
  RotateCcw,
  ShieldCheck,
  Split,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAdapterAccess } from "@/components/adapter-access-provider";
import { useAuth } from "@/components/auth-provider";
import { CapabilityEmptyState } from "@/components/capability-empty-state";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { useModuleAccess } from "@/components/module-access-provider";
import { ApiError, apiRequest } from "@/lib/api";

type HealthResponse = {
  status: string;
  service: string;
  version: string;
  environment: string;
  database: string;
  external_services: string;
};

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

type ApprovalRecord = {
  approval_id?: string;
  module_key?: string;
  action_key?: string;
  risk_level?: string;
  status?: string;
  workflow_state?: string | null;
  request_time?: string;
};

type DashboardData = {
  health: HealthResponse | null;
  operationLogs: ListResponse<OperationLogRecord> | null;
  approvals: ListResponse<ApprovalRecord> | null;
  healthError: string;
  logsError: string;
  approvalsError: string;
};

const EMPTY_DASHBOARD_DATA: DashboardData = {
  approvals: null,
  approvalsError: "",
  health: null,
  healthError: "",
  logsError: "",
  operationLogs: null,
};

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
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

function statusCount<T extends { status?: string }>(
  items: readonly T[],
  status: string,
) {
  return items.filter((item) => item.status === status).length;
}

function metricState(error: string, value: string) {
  return error ? "Blocked" : value;
}

export function OperationsDashboard() {
  const { status: authStatus, user } = useAuth();
  const {
    executionState,
    liveGateErrors,
    liveGateReports,
    orgContext,
    refresh: refreshCapabilityState,
  } = useFrontendCapabilityState();
  const {
    error: moduleAccessError,
    items: moduleAccessItems,
    moduleAccessUnknown,
  } = useModuleAccess();
  const {
    accessItems: adapterAccessItems,
    adapterAccessUnknown,
    error: adapterAccessError,
    executionProviderAccessItems,
    executionProviderAccessUnknown,
    executionProviderError,
  } = useAdapterAccess();
  const [data, setData] = useState<DashboardData>(EMPTY_DASHBOARD_DATA);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    await refreshCapabilityState();
    const [health, operationLogs, approvals] = await Promise.allSettled([
      apiRequest<HealthResponse>("/health", { method: "GET" }),
      apiRequest<ListResponse<OperationLogRecord>>(
        "/operation-logs?limit=12&offset=0",
        { method: "GET" },
      ),
      apiRequest<ListResponse<ApprovalRecord>>(
        "/approval/list?limit=50&offset=0",
        { method: "GET" },
      ),
    ]);

    setData({
      approvals:
        approvals.status === "fulfilled" ? approvals.value : null,
      approvalsError:
        approvals.status === "rejected"
          ? errorMessage(approvals.reason, "Approvals API is unavailable.")
          : "",
      health: health.status === "fulfilled" ? health.value : null,
      healthError:
        health.status === "rejected"
          ? errorMessage(health.reason, "System health API is unavailable.")
          : "",
      operationLogs:
        operationLogs.status === "fulfilled" ? operationLogs.value : null,
      logsError:
        operationLogs.status === "rejected"
          ? errorMessage(operationLogs.reason, "Operation logs API is unavailable.")
          : "",
    });
    setIsLoading(false);
  }, [refreshCapabilityState]);

  useEffect(() => {
    void load();
  }, [load]);

  const logs = data.operationLogs?.items ?? [];
  const approvals = data.approvals?.items ?? [];
  const traceGroups = useMemo(
    () => new Set(logs.map(traceKey).filter(Boolean)).size,
    [logs],
  );
  const failedLogs = logs.filter(
    (log) => log.result === "error" || Boolean(log.error_code),
  ).length;
  const actionAnomalySignals = useMemo(() => {
    const counts = new Map<string, number>();
    for (const log of logs) {
      const key = log.action ?? log.target_type ?? "unknown";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .filter(([, count]) => count >= 3)
      .sort((left, right) => right[1] - left[1]);
  }, [logs]);
  const missingTraceCount = logs.filter((log) => !traceKey(log)).length;
  const moduleCounts = useMemo(
    () => ({
      allowed: moduleAccessItems.filter(
        (item) => item.access_state === "available",
      ).length,
      hidden: moduleAccessItems.filter((item) => item.hidden).length,
      locked: moduleAccessItems.filter((item) => item.locked).length,
      partial: moduleAccessItems.filter((item) => item.unavailable).length,
    }),
    [moduleAccessItems],
  );
  const executionCounts = useMemo(
    () => ({
      adapterPending: adapterAccessItems.filter(
        (item) => item.adapter_access_state === "adapter_pending",
      ).length,
      adapters: adapterAccessItems.length,
      noExecute: executionProviderAccessItems.filter(
        (item) => !item.can_request_execution || !item.executable,
      ).length,
      providers: executionProviderAccessItems.length,
    }),
    [adapterAccessItems, executionProviderAccessItems],
  );
  const permissionCount = user?.permissions?.permission_keys.length ?? 0;
  const ownerMode = user?.permissions?.is_owner_full_access === true;

  return (
    <div className="ops-dashboard">
      <div className="ops-dashboard-header">
        <div>
          <span className="eyebrow">System Operations Control Center</span>
          <h2>Operational capability status</h2>
          <p>
            Backend health, C17 observability, C12 approvals, C18 module
            readiness, C05 permission snapshot, PRE20-Q live gate, and
            execution readiness.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void load()}
          type="button"
        >
          {isLoading ? (
            <LoaderCircle className="spin" aria-hidden="true" size={17} />
          ) : (
            <RotateCcw aria-hidden="true" size={17} />
          )}
          Refresh
        </button>
      </div>

      <section className="ops-metric-grid" aria-label="Operational metrics">
        <article className="ops-metric-card">
          <CheckCircle2 aria-hidden="true" size={19} />
          <span>System health</span>
          <strong>{metricState(data.healthError, data.health?.status ?? "Unknown")}</strong>
          <small>Source: /health</small>
        </article>
        <article className="ops-metric-card">
          <Database aria-hidden="true" size={19} />
          <span>C17 logs</span>
          <strong>{metricState(data.logsError, String(data.operationLogs?.count ?? 0))}</strong>
          <small>{failedLogs} failed in latest page</small>
        </article>
        <article className="ops-metric-card">
          <GitBranch aria-hidden="true" size={19} />
          <span>Traces overview</span>
          <strong>{metricState(data.logsError, String(traceGroups))}</strong>
          <small>Grouped by trace, context, request, or job ID</small>
        </article>
        <article className="ops-metric-card">
          <Clock3 aria-hidden="true" size={19} />
          <span>Approvals</span>
          <strong>{metricState(data.approvalsError, String(data.approvals?.count ?? 0))}</strong>
          <small>{statusCount(approvals, "pending")} pending</small>
        </article>
        <article className="ops-metric-card">
          <Split aria-hidden="true" size={19} />
          <span>Module readiness</span>
          <strong>{moduleAccessUnknown ? "Blocked" : String(moduleAccessItems.length)}</strong>
          <small>{moduleCounts.allowed} allowed, {moduleCounts.locked} locked</small>
        </article>
        <article className="ops-metric-card">
          <Activity aria-hidden="true" size={19} />
          <span>Execution readiness</span>
          <strong>
            {adapterAccessUnknown || executionProviderAccessUnknown
              ? "Blocked"
              : `${executionCounts.providers}/${executionCounts.adapters}`}
          </strong>
          <small>{executionCounts.noExecute} no-execute providers</small>
        </article>
        <article className="ops-metric-card">
          <ShieldCheck aria-hidden="true" size={19} />
          <span>PRE20-Q gate</span>
          <strong>{executionState.live_gate_status}</strong>
          <small>{executionState.execution_mode} mode</small>
        </article>
        <article className="ops-metric-card">
          <ShieldCheck aria-hidden="true" size={19} />
          <span>Permission snapshot</span>
          <strong>{ownerMode ? "Owner" : String(permissionCount)}</strong>
          <small>Source: current C05 snapshot</small>
        </article>
      </section>

      <section className="ops-dashboard-grid">
        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>C17 logs overview</h3>
              <p>Recent operation records from the backend observability store.</p>
            </div>
            <span className="ops-source">/operation-logs</span>
          </div>
          {data.logsError ? (
            <CapabilityEmptyState
              reason={data.logsError}
              required_execution_mode="Read-only C17 log API."
              required_module_state="system.operation_logs sealed and visible."
              required_org_state="Active org context accepted by operation log API."
              required_permission="operation_logs.read"
              state="backend_unavailable"
              title="C17 logs unavailable"
              unlock_condition="Restore the operation logs backend API or permission."
            />
          ) : (
            <ol className="ops-record-list">
              {logs.slice(0, 6).map((log) => (
                <li key={log.operation_id ?? `${log.action}-${log.created_at}`}>
                  <span>{log.result ?? "unknown"}</span>
                  <strong>{log.action ?? "Unknown action"}</strong>
                  <small>
                    {log.target_type ?? "target"} / {formatDate(log.created_at)}
                  </small>
                </li>
              ))}
              {logs.length === 0 ? (
                <li>
                  <span>empty</span>
                  <strong>No operation logs match the current filters.</strong>
                  <small>Source returned zero records.</small>
                </li>
              ) : null}
            </ol>
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Execution readiness</h3>
              <p>C08 adapter and C09 provider states. No live action is implied.</p>
            </div>
            <span className="ops-source">/module-adapters/me + /execution-providers/me</span>
          </div>
          <dl className="ops-readiness-list">
            <div>
              <dt>Adapters</dt>
              <dd>{adapterAccessUnknown ? "Unavailable" : adapterAccessItems.length}</dd>
            </div>
            <div>
              <dt>Adapter pending</dt>
              <dd>{executionCounts.adapterPending}</dd>
            </div>
            <div>
              <dt>Providers</dt>
              <dd>
                {executionProviderAccessUnknown
                  ? "Unavailable"
                  : executionProviderAccessItems.length}
              </dd>
            </div>
            <div>
              <dt>No-execute providers</dt>
              <dd>{executionCounts.noExecute}</dd>
            </div>
          </dl>
          {adapterAccessError || executionProviderError ? (
            <p className="ops-warning">
              {adapterAccessError?.message ?? executionProviderError?.message}
            </p>
          ) : null}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>PRE20-Q execution gate</h3>
              <p>Live gate, canary, approval, execution mode, and block reason.</p>
            </div>
            <span className="ops-source">/live-gate/*</span>
          </div>
          <dl className="ops-readiness-list">
            <div>
              <dt>Live gate</dt>
              <dd>{executionState.live_gate_status}</dd>
            </div>
            <div>
              <dt>Canary</dt>
              <dd>{executionState.canary_state}</dd>
            </div>
            <div>
              <dt>Approval</dt>
              <dd>{executionState.approval_state}</dd>
            </div>
            <div>
              <dt>Mode</dt>
              <dd>{executionState.execution_mode}</dd>
            </div>
            <div>
              <dt>Policies</dt>
              <dd>{liveGateReports.policies.length}</dd>
            </div>
            <div>
              <dt>Rollout</dt>
              <dd>{executionState.rollout_percentage}%</dd>
            </div>
          </dl>
          <p className="ops-warning">{executionState.blocked_reason}</p>
          {liveGateErrors.readiness ||
          liveGateErrors.productionReadiness ||
          liveGateErrors.policies ? (
            <p className="ops-warning">
              {liveGateErrors.readiness?.message ??
                liveGateErrors.productionReadiness?.message ??
                liveGateErrors.policies?.message}
            </p>
          ) : null}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>C12 approvals</h3>
              <p>Approval requests are governance records, not execution success.</p>
            </div>
            <span className="ops-source">/approval/list</span>
          </div>
          {data.approvalsError ? (
            <CapabilityEmptyState
              reason={data.approvalsError}
              required_execution_mode="No execution mode required."
              required_module_state="C12 approval API reachable."
              required_org_state="Active org context accepted by approval API."
              required_permission="GOVERNANCE read permission."
              state="backend_unavailable"
              title="Approvals unavailable"
              unlock_condition="Restore approval API access or permission."
            />
          ) : (
            <dl className="ops-readiness-list">
              <div>
                <dt>Pending</dt>
                <dd>{statusCount(approvals, "pending")}</dd>
              </div>
              <div>
                <dt>Approved</dt>
                <dd>{statusCount(approvals, "approved")}</dd>
              </div>
              <div>
                <dt>Rejected</dt>
                <dd>{statusCount(approvals, "rejected")}</dd>
              </div>
              <div>
                <dt>Total</dt>
                <dd>{data.approvals?.count ?? 0}</dd>
              </div>
            </dl>
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>C18 module readiness</h3>
              <p>Module visibility, permission state, and lifecycle readiness.</p>
            </div>
            <span className="ops-source">/modules/me</span>
          </div>
          <dl className="ops-readiness-list">
            <div>
              <dt>Allowed</dt>
              <dd>{moduleCounts.allowed}</dd>
            </div>
            <div>
              <dt>Locked</dt>
              <dd>{moduleCounts.locked}</dd>
            </div>
            <div>
              <dt>Hidden</dt>
              <dd>{moduleCounts.hidden}</dd>
            </div>
            <div>
              <dt>Partial</dt>
              <dd>{moduleCounts.partial}</dd>
            </div>
            <div>
              <dt>Org state</dt>
              <dd>{orgContext.state}</dd>
            </div>
            <div>
              <dt>Org role</dt>
              <dd>{orgContext.role || "Unknown"}</dd>
            </div>
          </dl>
          {moduleAccessError ? (
            <p className="ops-warning">{moduleAccessError.message}</p>
          ) : null}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>C05 permission snapshot</h3>
              <p>Current actor permission facts used by the capability UI.</p>
            </div>
            <span className="ops-source">/auth/me</span>
          </div>
          <dl className="ops-readiness-list">
            <div>
              <dt>Session</dt>
              <dd>{authStatus}</dd>
            </div>
            <div>
              <dt>Role</dt>
              <dd>{user?.role ?? "Unknown"}</dd>
            </div>
            <div>
              <dt>Owner full access</dt>
              <dd>{ownerMode ? "yes" : "no"}</dd>
            </div>
            <div>
              <dt>Permission keys</dt>
              <dd>{permissionCount}</dd>
            </div>
          </dl>
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>System health</h3>
              <p>Backend reachability and declared service environment.</p>
            </div>
            <span className="ops-source">/health</span>
          </div>
          {data.healthError ? (
            <CapabilityEmptyState
              reason={data.healthError}
              required_execution_mode="No execution mode required."
              required_module_state="Public health route reachable."
              required_org_state="No org context required."
              required_permission="Authenticated session for console shell."
              state="backend_unavailable"
              title="System health unavailable"
              unlock_condition="Restore backend API reachability."
            />
          ) : (
            <dl className="ops-readiness-list">
              <div>
                <dt>Service</dt>
                <dd>{data.health?.service ?? "Unknown"}</dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{data.health?.version ?? "Unknown"}</dd>
              </div>
              <div>
                <dt>Environment</dt>
                <dd>{data.health?.environment ?? "Unknown"}</dd>
              </div>
              <div>
                <dt>External services</dt>
                <dd>{data.health?.external_services ?? "Unknown"}</dd>
              </div>
            </dl>
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>C17 alerts and anomalies</h3>
              <p>Derived from recent operation logs without inventing backend state.</p>
            </div>
            <span className="ops-source">C17 projection</span>
          </div>
          <dl className="ops-readiness-list">
            <div>
              <dt>Alert candidates</dt>
              <dd>{failedLogs}</dd>
            </div>
            <div>
              <dt>Repeated actions</dt>
              <dd>{actionAnomalySignals.length}</dd>
            </div>
            <div>
              <dt>Missing trace keys</dt>
              <dd>{missingTraceCount}</dd>
            </div>
            <div>
              <dt>Signals</dt>
              <dd>{actionAnomalySignals.length + (missingTraceCount > 0 ? 1 : 0)}</dd>
            </div>
          </dl>
        </article>

        <article className="ops-panel ops-panel-wide">
          <div className="ops-panel-heading">
            <div>
              <h3>Traces overview</h3>
              <p>C17 trace overview is derived from recent backend log correlation IDs.</p>
            </div>
            <span className="ops-source">C17 logs correlation</span>
          </div>
          <div className="ops-trace-grid">
            {Array.from(
              new Map(
                logs
                  .map((log) => [traceKey(log), log] as const)
                  .filter(([key]) => Boolean(key)),
              ).entries(),
            )
              .slice(0, 6)
              .map(([key, log]) => (
                <div key={key ?? log.operation_id}>
                  <FileSearch aria-hidden="true" size={17} />
                  <strong>{key}</strong>
                  <span>{log.action ?? "Unknown action"}</span>
                </div>
              ))}
            {traceGroups === 0 ? (
              <div>
                <CircleAlert aria-hidden="true" size={17} />
                <strong>No trace groups in the latest log page.</strong>
                <span>Trace grouping unlocks when logs include trace, context, request, or job IDs.</span>
              </div>
            ) : null}
          </div>
        </article>
      </section>
    </div>
  );
}
