"use client";

import {
  Building2,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  LoaderCircle,
  RotateCcw,
  ShieldCheck,
  UsersRound,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { ApiError, apiRequest } from "@/lib/api";

type HealthResponse = {
  status?: string | null;
  service?: string | null;
  version?: string | null;
  environment?: string | null;
  database?: string | null;
  external_services?: string | null;
};

type ListResponse<T> = {
  items?: Array<T | null | undefined> | null;
  count?: number | null;
  limit?: number | null;
  offset?: number | null;
};

type OperationLogRecord = {
  action?: string;
  target_type?: string;
  result?: string;
  error_code?: string | null;
  created_at?: string;
};

type ApprovalRecord = {
  risk_level?: string;
  status?: string;
  request_time?: string;
};

type UserRecord = {
  id?: number;
  username?: string;
  role?: string;
  status?: string;
};

type DashboardState = {
  approvals?: ListResponse<ApprovalRecord> | null;
  approvalsError?: string | null;
  health?: HealthResponse | null;
  healthError?: string | null;
  operationLogs?: ListResponse<OperationLogRecord> | null;
  logsError?: string | null;
  users?: ListResponse<UserRecord> | null;
  usersError?: string | null;
};

const ENGINEERING_LABEL_PREFIX = "C";
const DASHBOARD_LOADING_FALLBACK_MS = 2000;
const ENGINEERING_LABEL_REPLACEMENTS: Array<[RegExp, string]> = [
  [
    new RegExp(`\\b${ENGINEERING_LABEL_PREFIX}17(?: Durable Observability)?\\b`, "g"),
    "Logs",
  ],
  [
    new RegExp(
      `\\b${ENGINEERING_LABEL_PREFIX}18(?: Scope Adapter| Tenant Consistency)?\\b`,
      "g",
    ),
    "Organizations",
  ],
  [
    new RegExp(`\\b${ENGINEERING_LABEL_PREFIX}12(?: Approval Gate)?\\b`, "g"),
    "Approvals",
  ],
];

function textValue(value: unknown, fallback = "Unknown") {
  const text = typeof value === "string" ? value.trim() : "";
  const safeText = text.length > 0 ? text : fallback;

  return ENGINEERING_LABEL_REPLACEMENTS.reduce(
    (label, [pattern, replacement]) => label.replace(pattern, replacement),
    safeText,
  );
}

function optionalText(value: unknown) {
  return typeof value === "string" ? textValue(value, "") : "";
}

function safeNumber(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, value)
    : fallback;
}

function safeItems<T>(response: ListResponse<T> | null | undefined): T[] {
  return Array.isArray(response?.items)
    ? response.items.filter((item): item is T => item !== null && item !== undefined)
    : [];
}

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError || error instanceof Error) {
    return textValue(error.message, fallback);
  }

  return fallback;
}

function formatDate(value: unknown) {
  if (typeof value !== "string" || value.trim().length === 0) {
    return "Not recorded";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return textValue(value, "Not recorded");
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function statusCount<T extends { status?: string | null | undefined }>(
  items: readonly T[],
  status: string,
) {
  return items.filter(
    (item) => optionalText(item.status).toLowerCase() === status,
  ).length;
}

function failedLogCount(items: readonly OperationLogRecord[]) {
  return items.filter((log) => {
    const result = optionalText(log.result).toLowerCase();

    return result === "error" || optionalText(log.error_code).length > 0;
  }).length;
}

function normalizeExecutionMode(value: unknown): "mock" | "staging" | "live" {
  return value === "staging" || value === "live" ? value : "mock";
}

function FallbackNotice({
  detail,
  isLoading,
  onRetry,
}: {
  detail?: string;
  isLoading: boolean;
  onRetry: () => void;
}) {
  return (
    <div aria-live="polite" className="ops-empty-state" role="status">
      <strong>System initializing</strong>
      <span>Fallback mode active</span>
      <span>{textValue(detail, "System initializing")}</span>
      <button
        className="secondary-button"
        disabled={isLoading}
        onClick={onRetry}
        type="button"
      >
        {isLoading ? (
          <LoaderCircle aria-hidden="true" className="spin" size={15} />
        ) : (
          <RotateCcw aria-hidden="true" size={15} />
        )}
        Try refresh
      </button>
    </div>
  );
}

export function OperationsDashboard() {
  const { user } = useAuth();
  const capabilityState = useFrontendCapabilityState();
  const [state, setState] = useState<DashboardState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasLoadingTimedOut, setHasLoadingTimedOut] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);

    try {
      const [health, operationLogs, approvals, users] =
        await Promise.allSettled([
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

      setState({
        approvals: approvals.status === "fulfilled" ? approvals.value ?? null : null,
        approvalsError:
          approvals.status === "rejected"
            ? errorMessage(approvals.reason, "Approvals are unavailable.")
            : "",
        health: health.status === "fulfilled" ? health.value ?? null : null,
        healthError:
          health.status === "rejected"
            ? errorMessage(health.reason, "System health is unavailable.")
            : "",
        operationLogs:
          operationLogs.status === "fulfilled"
            ? operationLogs.value ?? null
            : null,
        logsError:
          operationLogs.status === "rejected"
            ? errorMessage(operationLogs.reason, "Logs are unavailable.")
            : "",
        users: users.status === "fulfilled" ? users.value ?? null : null,
        usersError:
          users.status === "rejected"
            ? errorMessage(users.reason, "Users are unavailable.")
            : "",
      });
    } catch (error) {
      const message = errorMessage(error, "Dashboard data is unavailable.");

      setState({
        approvals: null,
        approvalsError: message,
        health: null,
        healthError: message,
        operationLogs: null,
        logsError: message,
        users: null,
        usersError: message,
      });
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!isLoading) {
      setHasLoadingTimedOut(false);
      return;
    }

    const timer = window.setTimeout(() => {
      setHasLoadingTimedOut(true);
    }, DASHBOARD_LOADING_FALLBACK_MS);

    return () => {
      window.clearTimeout(timer);
    };
  }, [isLoading]);

  const safeState = state ?? {};
  const safeOrgContext = {
    role: textValue(capabilityState?.orgContext?.role, "Unknown"),
    state: textValue(capabilityState?.orgContext?.state, "unknown"),
    visibleModules: safeNumber(capabilityState?.orgContext?.visible_modules, 0),
  };

  const currentUser = user ?? null;
  const logs = safeItems(safeState.operationLogs);
  const approvalItems = safeItems(safeState.approvals);
  const userItems = safeItems(safeState.users);
  const users = safeNumber(
    safeState.users?.count,
    safeState.users?.items?.length ?? 0,
  );
  const orgs = safeOrgContext.state === "active" ? 1 : 0;
  const approvals = safeNumber(
    safeState.approvals?.count,
    safeState.approvals?.items?.length ?? 0,
  );
  const pendingApprovals = statusCount(approvalItems, "pending");
  const approvedApprovals = statusCount(approvalItems, "approved");
  const rejectedApprovals = statusCount(approvalItems, "rejected");
  const failedLogs = failedLogCount(logs);
  const healthError = optionalText(safeState.healthError);
  const usersError = optionalText(safeState.usersError);
  const approvalsError = optionalText(safeState.approvalsError);
  const logsError = optionalText(safeState.logsError);
  const healthStatus = textValue(safeState.health?.status, "System initializing");
  const executionMode = normalizeExecutionMode(
    capabilityState?.liveGate?.execution_mode,
  );
  const loadingFallbackActive = hasLoadingTimedOut || state === null;
  const activeLoading = isLoading && !hasLoadingTimedOut;
  const capabilityLoading =
    capabilityState?.isLoading === true &&
    capabilityState?.uiState !== "fallback";
  const capabilityFallbackActive =
    capabilityState?.uiState === "fallback" || capabilityState?.isFallbackMode;
  const hasHealthData = safeState.health !== null && safeState.health !== undefined;
  const hasUsersData = safeState.users !== null && safeState.users !== undefined;
  const hasApprovalData =
    safeState.approvals !== null && safeState.approvals !== undefined;
  const hasOrganizationData = safeOrgContext.state === "active";
  const healthDetail = healthError || "System initializing";
  const userDetail = usersError || "System initializing";
  const approvalDetail = approvalsError || "System initializing";
  const logDetail = logsError || "System initializing";
  const approvalQueue = approvalItems
    .filter((approval) => optionalText(approval.status).toLowerCase() === "pending")
    .slice(0, 5);
  const systemStatus = useMemo(() => {
    if (healthError.length > 0) {
      return "No data available";
    }
    if (!hasHealthData && activeLoading) {
      return "System initializing";
    }
    if (!hasHealthData && loadingFallbackActive) {
      return "Fallback mode active";
    }
    if (failedLogs > 0 || logsError.length > 0 || approvalsError.length > 0) {
      return "Review";
    }

    return "Operational";
  }, [
    approvalsError,
    activeLoading,
    failedLogs,
    hasHealthData,
    healthError,
    loadingFallbackActive,
    logsError,
  ]);
  const metricCards = [
    {
      detail: healthError || textValue(safeState.health?.database, "System initializing"),
      icon: CheckCircle2,
      label: "System Health",
      value: healthError ? "No data available" : healthStatus,
    },
    {
      detail: usersError || "Workspace accounts",
      icon: UsersRound,
      label: "Users Overview",
      value: users,
    },
    {
      detail:
        orgs > 0 ? "Active workspace" : "No data available",
      icon: Building2,
      label: "Organizations Overview",
      value: orgs,
    },
    {
      detail: `${approvals} total requests`,
      icon: ClipboardCheck,
      label: "Approvals Queue",
      value: approvalsError ? "No data available" : pendingApprovals,
    },
    {
      detail: `${failedLogs} need review`,
      icon: FileText,
      label: "Logs",
      value: logsError ? "No data available" : logs.length,
    },
    {
      detail: "Current mode",
      icon: ShieldCheck,
      label: "Execution Status",
      value: executionMode,
    },
  ];

  return (
    <div className="ops-dashboard">
      <div className="ops-dashboard-header">
        <div>
          <span className="eyebrow">Operations Hub</span>
          <h2>Product operations hub</h2>
          <p>
            Monitor System Health, Users Overview, Organizations Overview,
            Approvals Queue, Logs, and Execution Status from one stable view.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={activeLoading}
          onClick={() => void load()}
          type="button"
        >
          {activeLoading ? (
            <LoaderCircle className="spin" aria-hidden="true" size={17} />
          ) : (
            <RotateCcw aria-hidden="true" size={17} />
          )}
          Refresh
        </button>
      </div>

      <section className="ops-metric-grid" aria-label="Operations metrics">
        {metricCards.map(({ detail, icon: Icon, label, value }) => (
          <article className="ops-metric-card" key={label}>
            <Icon aria-hidden="true" size={19} />
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{detail}</small>
          </article>
        ))}
      </section>

      <section className="ops-dashboard-grid">
        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>System Health Card</h3>
              <p>Current service availability and product readiness.</p>
            </div>
          </div>
          {healthError || !hasHealthData ? (
            <FallbackNotice
              detail={healthDetail}
              isLoading={activeLoading}
              onRetry={() => void load()}
            />
          ) : (
            <dl className="ops-readiness-list">
              <div>
                <dt>Status</dt>
                <dd>{healthStatus}</dd>
              </div>
              <div>
                <dt>Service</dt>
                <dd>{textValue(safeState.health?.service)}</dd>
              </div>
              <div>
                <dt>Database</dt>
                <dd>{textValue(safeState.health?.database)}</dd>
              </div>
              <div>
                <dt>External services</dt>
                <dd>{textValue(safeState.health?.external_services)}</dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{textValue(safeState.health?.version)}</dd>
              </div>
              <div>
                <dt>Overall</dt>
                <dd>{systemStatus}</dd>
              </div>
            </dl>
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Users Overview</h3>
              <p>User access and account coverage for this workspace.</p>
            </div>
          </div>
          {usersError && !hasUsersData && !currentUser ? (
            <FallbackNotice
              detail={userDetail}
              isLoading={activeLoading}
              onRetry={() => void load()}
            />
          ) : (
            <dl className="ops-readiness-list">
              <div>
                <dt>Users</dt>
                <dd>{users}</dd>
              </div>
              <div>
                <dt>Loaded</dt>
                <dd>{userItems.length}</dd>
              </div>
              <div>
                <dt>Current role</dt>
                <dd>{textValue(currentUser?.role)}</dd>
              </div>
              <div>
                <dt>Account</dt>
                <dd>{textValue(currentUser?.username)}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>
                  {usersError
                    ? "Limited view"
                    : currentUser?.is_active === false
                      ? "Inactive"
                      : "Available"}
                </dd>
              </div>
            </dl>
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Organizations Overview</h3>
              <p>Workspace organization access and visibility status.</p>
            </div>
          </div>
          {hasOrganizationData ? (
            <dl className="ops-readiness-list">
              <div>
                <dt>Organizations</dt>
                <dd>{orgs}</dd>
              </div>
              <div>
                <dt>Access</dt>
                <dd>Active</dd>
              </div>
              <div>
                <dt>Role</dt>
                <dd>{safeOrgContext.role}</dd>
              </div>
              <div>
                <dt>Visible areas</dt>
                <dd>{safeOrgContext.visibleModules}</dd>
              </div>
            </dl>
          ) : (
            <FallbackNotice
              detail="System initializing"
              isLoading={activeLoading}
              onRetry={() => void load()}
            />
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Approvals Queue</h3>
              <p>Requests waiting for review and completed decisions.</p>
            </div>
          </div>
          {approvalsError || !hasApprovalData ? (
            <FallbackNotice
              detail={approvalDetail}
              isLoading={activeLoading}
              onRetry={() => void load()}
            />
          ) : (
            <>
              <dl className="ops-readiness-list">
                <div>
                  <dt>Pending</dt>
                  <dd>{pendingApprovals}</dd>
                </div>
                <div>
                  <dt>Approved</dt>
                  <dd>{approvedApprovals}</dd>
                </div>
                <div>
                  <dt>Rejected</dt>
                  <dd>{rejectedApprovals}</dd>
                </div>
                <div>
                  <dt>Total</dt>
                  <dd>{approvals}</dd>
                </div>
              </dl>
              {approvalQueue.length > 0 ? (
                <ol className="ops-record-list" aria-label="Approvals queue">
                  {approvalQueue.map((approval, index) => (
                    <li key={`approval-${index}`}>
                      <span>{textValue(approval.status, "pending")}</span>
                      <strong>Approval request</strong>
                      <small>
                        {textValue(approval.risk_level, "Standard risk")} /{" "}
                        {formatDate(approval.request_time)}
                      </small>
                    </li>
                  ))}
                </ol>
              ) : (
                <FallbackNotice
                  detail="System initializing"
                  isLoading={activeLoading}
                  onRetry={() => void load()}
                />
              )}
            </>
          )}
        </article>

        <article className="ops-panel ops-panel-wide">
          <div className="ops-panel-heading">
            <div>
              <h3>Logs</h3>
              <p>Recent product activity and completed work.</p>
            </div>
          </div>
          {logsError || logs.length === 0 ? (
            <FallbackNotice
              detail={logDetail}
              isLoading={activeLoading}
              onRetry={() => void load()}
            />
          ) : (
            <ol className="ops-record-list" aria-label="Recent logs">
              {logs.slice(0, 8).map((log, index) => (
                <li key={`log-${index}`}>
                  <span>{textValue(log.result, "recorded")}</span>
                  <strong>{textValue(log.action, "Log entry")}</strong>
                  <small>
                    {textValue(log.target_type, "Workspace")} /{" "}
                    {formatDate(log.created_at)}
                  </small>
                </li>
              ))}
            </ol>
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Execution Status</h3>
              <p>Current product execution mode exposed to operators.</p>
            </div>
          </div>
          <dl className="ops-readiness-list">
            <div>
              <dt>Current mode</dt>
              <dd>{executionMode}</dd>
            </div>
            <div>
              <dt>Safe fallback</dt>
              <dd>mock</dd>
            </div>
            <div>
              <dt>Available modes</dt>
              <dd>mock / staging / live</dd>
            </div>
            <div>
              <dt>State</dt>
              <dd>
                {capabilityFallbackActive
                  ? "Fallback mode active"
                  : capabilityLoading
                    ? "System initializing"
                    : "Available"}
              </dd>
            </div>
          </dl>
        </article>
      </section>
    </div>
  );
}
