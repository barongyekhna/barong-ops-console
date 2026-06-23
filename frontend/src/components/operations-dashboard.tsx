"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import {
  ActivityFeed,
  DashboardSkeleton,
  MetricCard,
  ModuleCard,
  type ActivityFeedItem,
  type ModuleCardStatus,
} from "@/components/dashboard-ui";
import {
  ApiRequestAbortedError,
  apiRequest,
  isApiAbortError,
} from "@/lib/api";
import type { ProductCapabilityItem } from "@/lib/frontend-capability-state";

type HealthResponse = {
  status?: string | null;
};

type ListResponse<T> = {
  items?: Array<T | null | undefined> | null;
  count?: number | null;
};

type OperationLogRecord = {
  action?: string;
  target_type?: string;
  result?: string;
  error_code?: string | null;
  created_at?: string;
};

type ApprovalRecord = {
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

type BatchEntry<T> = {
  data?: T | null;
  ok?: boolean;
};

type DashboardOverviewResponse = {
  health?: BatchEntry<HealthResponse>;
  users?: BatchEntry<ListResponse<UserRecord>>;
};

type DashboardActivityResponse = {
  approvals?: BatchEntry<ListResponse<ApprovalRecord>>;
  operation_logs?: BatchEntry<ListResponse<OperationLogRecord>>;
};

const EMPTY_DASHBOARD_STATE: DashboardState = {
  approvals: null,
  approvalsError: "",
  health: null,
  healthError: "",
  operationLogs: null,
  logsError: "",
  users: null,
  usersError: "",
};

function textValue(value: unknown, fallback = "No data") {
  const text = typeof value === "string" ? value.trim() : "";
  return text.length > 0 ? text : fallback;
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

function batchData<T>(entry: BatchEntry<T> | null | undefined): T | null {
  return entry?.ok === true ? entry.data ?? null : null;
}

function batchError(entry: BatchEntry<unknown> | null | undefined) {
  return entry?.ok === true ? "" : "Data temporarily unavailable.";
}

function formatDate(value: unknown) {
  if (typeof value !== "string" || value.trim().length === 0) {
    return "No timestamp";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "No timestamp";
  }

  return new Intl.DateTimeFormat("zh-CN", {
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

function moduleStatus(item: ProductCapabilityItem): ModuleCardStatus {
  if (item.state === "allowed" && item.can_enter) {
    return "active";
  }
  if (item.state === "backend_unavailable" || item.state === "no_execution") {
    return "error";
  }
  return "disabled";
}

function moduleDescription(status: ModuleCardStatus) {
  if (status === "active") {
    return "Ready for workspace operations.";
  }
  if (status === "error") {
    return "Needs attention before it can run.";
  }
  return "Available after configuration or access is granted.";
}

function moduleActionLabel(status: ModuleCardStatus) {
  return status === "active" ? "Open module" : "Unavailable";
}

function moduleBadge(item: ProductCapabilityItem) {
  if (item.badge) {
    return item.badge.replaceAll("_", " ");
  }
  return item.nav_group;
}

function buildActivityFeed({
  logs,
  modules,
}: {
  logs: OperationLogRecord[];
  modules: ProductCapabilityItem[];
}): ActivityFeedItem[] {
  const executionItems: ActivityFeedItem[] = logs.slice(0, 4).map((log) => {
    const failed =
      optionalText(log.result).toLowerCase() === "error" ||
      optionalText(log.error_code).length > 0;

    return {
      badge: failed ? "error" : "execution",
      detail: failed
        ? "Execution completed with an issue."
        : "Execution completed successfully.",
      meta: formatDate(log.created_at),
      title: "Execution log",
      tone: failed ? "error" : "active",
    };
  });

  const moduleItems: ActivityFeedItem[] = modules.slice(0, 3).map((item) => {
    const status = moduleStatus(item);
    return {
      badge: status,
      detail: `${item.label} is ${status}.`,
      meta: item.nav_group,
      title: "Module activity",
      tone: status,
    };
  });

  const apiLog = logs.find((log) => {
    const value = `${optionalText(log.action)} ${optionalText(log.target_type)}`.toLowerCase();
    return value.includes("api") || value.includes("key");
  });
  const apiItem: ActivityFeedItem = {
    badge: "key_••••",
    detail: apiLog
      ? "Masked API key usage was recorded."
      : "No recent API key usage was recorded.",
    meta: apiLog ? formatDate(apiLog.created_at) : "masked",
    title: "API key usage",
    tone: apiLog ? "active" : "disabled",
  };

  const items = [...executionItems, ...moduleItems, apiItem];
  if (items.length > 1) {
    return items.slice(0, 8);
  }

  return [
    {
      badge: "ready",
      detail: "Workspace modules are ready for review.",
      meta: "system",
      title: "Module activity",
      tone: "active",
    },
    apiItem,
  ];
}

export function OperationsDashboard() {
  const capabilityState = useFrontendCapabilityState();
  const [state, setState] = useState<DashboardState>(EMPTY_DASHBOARD_STATE);
  const [isLoading, setIsLoading] = useState(false);
  const loadGenerationRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    const previousController = abortControllerRef.current;
    if (previousController && !previousController.signal.aborted) {
      previousController.abort(
        new ApiRequestAbortedError("Dashboard request superseded."),
      );
    }

    const controller = new AbortController();
    const generation = loadGenerationRef.current + 1;
    loadGenerationRef.current = generation;
    abortControllerRef.current = controller;
    let pendingRequests = 2;

    const applyState = (patch: DashboardState) => {
      if (
        controller.signal.aborted ||
        loadGenerationRef.current !== generation
      ) {
        return;
      }

      setState((current) => ({
        ...current,
        ...patch,
      }));
    };

    const markSettled = () => {
      pendingRequests -= 1;
      if (
        pendingRequests <= 0 &&
        abortControllerRef.current === controller
      ) {
        abortControllerRef.current = null;
        setIsLoading(false);
      }
    };

    const loadResource = async <T,>(
      request: Promise<T>,
      onSuccess: (value: T) => DashboardState,
      onError: () => DashboardState,
    ) => {
      try {
        const value = await request;
        applyState(onSuccess(value));
      } catch (error) {
        if (!isApiAbortError(error)) {
          applyState(onError());
        }
      } finally {
        markSettled();
      }
    };

    setIsLoading(true);

    void loadResource(
      apiRequest<DashboardOverviewResponse>("/dashboard/overview?limit=1&offset=0", {
        method: "GET",
        signal: controller.signal,
      }),
      (overview) => ({
        health: batchData(overview.health),
        healthError: batchError(overview.health),
        users: batchData(overview.users),
        usersError: batchError(overview.users),
      }),
      () => ({
        health: null,
        healthError: "Data temporarily unavailable.",
        users: null,
        usersError: "Data temporarily unavailable.",
      }),
    );

    void loadResource(
      apiRequest<DashboardActivityResponse>(
        "/dashboard/activity?log_limit=8&log_offset=0&approval_limit=50&approval_offset=0",
        {
          method: "GET",
          signal: controller.signal,
        },
      ),
      (activity) => ({
        approvals: batchData(activity.approvals),
        approvalsError: batchError(activity.approvals),
        logsError: batchError(activity.operation_logs),
        operationLogs: batchData(activity.operation_logs),
      }),
      () => ({
        approvals: null,
        approvalsError: "Data temporarily unavailable.",
        logsError: "Data temporarily unavailable.",
        operationLogs: null,
      }),
    );
  }, []);

  useEffect(() => {
    void load();

    return () => {
      const controller = abortControllerRef.current;
      if (controller && !controller.signal.aborted) {
        controller.abort(new ApiRequestAbortedError("Dashboard request canceled."));
      }
      abortControllerRef.current = null;
    };
  }, [load]);

  const logs = safeItems(state.operationLogs);
  const approvalItems = safeItems(state.approvals);
  const failedLogs = failedLogCount(logs);
  const executionCount = safeNumber(state.operationLogs?.count, logs.length);
  const successRate =
    logs.length > 0
      ? Math.round(((logs.length - failedLogs) / logs.length) * 100)
      : 0;
  const pendingApprovals = statusCount(approvalItems, "pending");
  const modules = capabilityState.sidebarItems.slice(0, 8);
  const activeModules = modules.filter(
    (item) => moduleStatus(item) === "active",
  ).length;
  const moduleCards = modules.map((item) => {
    const status = moduleStatus(item);
    return {
      actionHref: item.href,
      actionLabel: moduleActionLabel(status),
      badge: moduleBadge(item),
      description: moduleDescription(status),
      name: item.label,
      status,
    };
  });
  const activityItems = useMemo(
    () => buildActivityFeed({ logs, modules }),
    [logs, modules],
  );

  return (
    <div className="dashboard-page">
      <section className="metrics-row" aria-label="Dashboard metrics">
        <MetricCard
          detail={`${capabilityState.sidebarItems.length} visible modules`}
          label="Active Modules"
          value={activeModules}
        />
        <MetricCard
          detail={state.logsError ? "Data sync pending" : "Recent executions"}
          label="Executions"
          value={executionCount}
        />
        <MetricCard
          detail={`${failedLogs} issues in latest logs`}
          label="Success Rate"
          value={`${successRate}%`}
        />
        <MetricCard
          detail={state.approvalsError ? "Review sync pending" : "Awaiting action"}
          label="Pending Reviews"
          value={pendingApprovals}
        />
      </section>

      <section className="dashboard-main-grid" aria-label="Workspace overview">
        <div className="modules-section">
          <div className="dashboard-section-heading">
            <div>
              <span className="eyebrow">Modules</span>
              <h2>Module grid</h2>
            </div>
            <span>{isLoading ? "Syncing" : "Ready"}</span>
          </div>

          {isLoading && moduleCards.length === 0 ? (
            <DashboardSkeleton />
          ) : (
            <div className="module-card-grid">
              {moduleCards.map((module) => (
                <ModuleCard key={module.name} {...module} />
              ))}
            </div>
          )}
        </div>

        <ActivityFeed items={activityItems} />
      </section>
    </div>
  );
}
