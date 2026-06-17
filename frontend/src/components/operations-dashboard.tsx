"use client";

import {
  CheckCircle2,
  Clock3,
  FileText,
  LoaderCircle,
  RotateCcw,
  ShieldCheck,
  UsersRound,
  Building2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
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

type UserRecord = {
  id?: number;
  username?: string;
  role?: string;
  status?: string;
};

type DashboardData = {
  approvals: ListResponse<ApprovalRecord> | null;
  approvalsError: string;
  health: HealthResponse | null;
  healthError: string;
  operationLogs: ListResponse<OperationLogRecord> | null;
  logsError: string;
  users: ListResponse<UserRecord> | null;
  usersError: string;
};

const EMPTY_DASHBOARD_DATA: DashboardData = {
  approvals: null,
  approvalsError: "",
  health: null,
  healthError: "",
  logsError: "",
  operationLogs: null,
  users: null,
  usersError: "",
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

function statusCount<T extends { status?: string }>(
  items: readonly T[],
  status: string,
) {
  return items.filter((item) => item.status === status).length;
}

function failedOperationCount(items: readonly OperationLogRecord[]) {
  return items.filter((log) => log.result === "error" || Boolean(log.error_code))
    .length;
}

function displayStatus(value: string | null | undefined) {
  return value?.trim() || "Unknown";
}

export function OperationsDashboard() {
  const { user } = useAuth();
  const { orgContext, refresh: refreshCapabilityState } =
    useFrontendCapabilityState();
  const [data, setData] = useState<DashboardData>(EMPTY_DASHBOARD_DATA);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    await refreshCapabilityState();
    const [health, operationLogs, approvals, users] = await Promise.allSettled([
      apiRequest<HealthResponse>("/health", { method: "GET" }),
      apiRequest<ListResponse<OperationLogRecord>>(
        "/operation-logs?limit=8&offset=0",
        { method: "GET" },
      ),
      apiRequest<ListResponse<ApprovalRecord>>(
        "/approval/list?limit=50&offset=0",
        { method: "GET" },
      ),
      apiRequest<ListResponse<UserRecord>>("/users?limit=1&offset=0", {
        method: "GET",
      }),
    ]);

    setData({
      approvals: approvals.status === "fulfilled" ? approvals.value : null,
      approvalsError:
        approvals.status === "rejected"
          ? errorMessage(approvals.reason, "Approvals are unavailable.")
          : "",
      health: health.status === "fulfilled" ? health.value : null,
      healthError:
        health.status === "rejected"
          ? errorMessage(health.reason, "System health is unavailable.")
          : "",
      operationLogs:
        operationLogs.status === "fulfilled" ? operationLogs.value : null,
      logsError:
        operationLogs.status === "rejected"
          ? errorMessage(operationLogs.reason, "Recent operations are unavailable.")
          : "",
      users: users.status === "fulfilled" ? users.value : null,
      usersError:
        users.status === "rejected"
          ? errorMessage(users.reason, "User count is unavailable.")
          : "",
    });
    setIsLoading(false);
  }, [refreshCapabilityState]);

  useEffect(() => {
    void load();
  }, [load]);

  const logs = data.operationLogs?.items ?? [];
  const approvals = data.approvals?.items ?? [];
  const pendingApprovals = statusCount(approvals, "pending");
  const failedOperations = failedOperationCount(logs);
  const userCount = data.users?.count ?? (user ? 1 : 0);
  const orgCount = orgContext.state === "active" ? 1 : 0;
  const healthStatus = displayStatus(data.health?.status);
  const systemStatus = useMemo(() => {
    if (data.healthError) {
      return "Needs attention";
    }
    if (failedOperations > 0 || data.logsError || data.approvalsError) {
      return "Review";
    }
    return "Operational";
  }, [data.approvalsError, data.healthError, data.logsError, failedOperations]);

  return (
    <div className="ops-dashboard">
      <div className="ops-dashboard-header">
        <div>
          <span className="eyebrow">Operations Hub</span>
          <h2>Workspace operations at a glance</h2>
          <p>
            Monitor service health, people, organizations, approvals, recent
            activity, and overall system status from one product view.
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

      <section className="ops-metric-grid" aria-label="Operations metrics">
        <article className="ops-metric-card">
          <CheckCircle2 aria-hidden="true" size={19} />
          <span>System health</span>
          <strong>{data.healthError ? "Unavailable" : healthStatus}</strong>
          <small>{data.health?.database ?? "Health check pending"}</small>
        </article>
        <article className="ops-metric-card">
          <UsersRound aria-hidden="true" size={19} />
          <span>Users</span>
          <strong>{userCount}</strong>
          <small>{data.usersError ? "Current user shown" : "Workspace accounts"}</small>
        </article>
        <article className="ops-metric-card">
          <Building2 aria-hidden="true" size={19} />
          <span>Organizations</span>
          <strong>{orgCount}</strong>
          <small>{orgContext.state === "active" ? "Active workspace" : "Not selected"}</small>
        </article>
        <article className="ops-metric-card">
          <Clock3 aria-hidden="true" size={19} />
          <span>Pending approvals</span>
          <strong>{data.approvalsError ? "Unavailable" : pendingApprovals}</strong>
          <small>{data.approvals?.count ?? 0} total requests</small>
        </article>
        <article className="ops-metric-card">
          <FileText aria-hidden="true" size={19} />
          <span>Recent operations</span>
          <strong>{data.logsError ? "Unavailable" : logs.length}</strong>
          <small>{failedOperations} need review</small>
        </article>
        <article className="ops-metric-card">
          <ShieldCheck aria-hidden="true" size={19} />
          <span>System status</span>
          <strong>{systemStatus}</strong>
          <small>{data.health?.environment ?? "Environment pending"}</small>
        </article>
      </section>

      <section className="ops-dashboard-grid">
        <article className="ops-panel ops-panel-wide">
          <div className="ops-panel-heading">
            <div>
              <h3>Recent operations</h3>
              <p>Latest activity across jobs, approvals, and system changes.</p>
            </div>
          </div>
          {data.logsError ? (
            <p className="ops-warning">{data.logsError}</p>
          ) : (
            <ol className="ops-record-list">
              {logs.slice(0, 8).map((log) => (
                <li key={log.operation_id ?? `${log.action}-${log.created_at}`}>
                  <span>{log.result ?? "recorded"}</span>
                  <strong>{log.action ?? "Operation recorded"}</strong>
                  <small>
                    {log.target_type ?? "Workspace"} / {formatDate(log.created_at)}
                  </small>
                </li>
              ))}
              {logs.length === 0 ? (
                <li>
                  <span>ready</span>
                  <strong>No recent operations yet.</strong>
                  <small>Activity will appear here as work is completed.</small>
                </li>
              ) : null}
            </ol>
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>System status</h3>
              <p>Current service availability and runtime environment.</p>
            </div>
          </div>
          {data.healthError ? (
            <p className="ops-warning">{data.healthError}</p>
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
                <dt>Database</dt>
                <dd>{data.health?.database ?? "Unknown"}</dd>
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
              <h3>Approvals</h3>
              <p>Requests waiting for review and completed decisions.</p>
            </div>
          </div>
          {data.approvalsError ? (
            <p className="ops-warning">{data.approvalsError}</p>
          ) : (
            <dl className="ops-readiness-list">
              <div>
                <dt>Pending</dt>
                <dd>{pendingApprovals}</dd>
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
              <h3>People</h3>
              <p>User access and account coverage for this workspace.</p>
            </div>
          </div>
          <dl className="ops-readiness-list">
            <div>
              <dt>User count</dt>
              <dd>{userCount}</dd>
            </div>
            <div>
              <dt>Current role</dt>
              <dd>{user?.role ?? "Unknown"}</dd>
            </div>
            <div>
              <dt>Account</dt>
              <dd>{user?.username ?? "Unknown"}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{data.usersError ? "Limited view" : "Available"}</dd>
            </div>
          </dl>
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Organizations</h3>
              <p>Workspace organization access and visibility status.</p>
            </div>
          </div>
          <dl className="ops-readiness-list">
            <div>
              <dt>Org count</dt>
              <dd>{orgCount}</dd>
            </div>
            <div>
              <dt>Access</dt>
              <dd>{orgContext.state === "active" ? "Active" : "Unknown"}</dd>
            </div>
            <div>
              <dt>Role</dt>
              <dd>{orgContext.role || "Unknown"}</dd>
            </div>
            <div>
              <dt>Visible areas</dt>
              <dd>{orgContext.visible_modules}</dd>
            </div>
          </dl>
        </article>
      </section>
    </div>
  );
}
