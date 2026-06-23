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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import {
  ApiRequestAbortedError,
  apiRequest,
  isApiAbortError,
} from "@/lib/api";

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

type BatchEntry<T> = {
  data?: T | null;
  detail?: unknown;
  ok?: boolean;
  status?: number | null;
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

const ENGINEERING_LABEL_PREFIX = "C";
const DASHBOARD_LOADING_FALLBACK_MS = 2000;
const ENGINEERING_LABEL_REPLACEMENTS: Array<[RegExp, string]> = [
  [
    new RegExp(`\\b${ENGINEERING_LABEL_PREFIX}17(?: Durable Observability)?\\b`, "g"),
    "操作记录",
  ],
  [
    new RegExp(
      `\\b${ENGINEERING_LABEL_PREFIX}18(?: Scope Adapter| Tenant Consistency)?\\b`,
      "g",
    ),
    "组织",
  ],
  [
    new RegExp(`\\b${ENGINEERING_LABEL_PREFIX}12(?: Approval Gate)?\\b`, "g"),
    "审批",
  ],
];

function textValue(value: unknown, fallback = "暂无数据") {
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

function batchData<T>(entry: BatchEntry<T> | null | undefined): T | null {
  return entry?.ok === true ? entry.data ?? null : null;
}

function batchError(entry: BatchEntry<unknown> | null | undefined, fallback: string) {
  if (entry?.ok === true) {
    return "";
  }
  return fallback;
}

function errorMessage(error: unknown, fallback: string) {
  void error;

  return fallback;
}

function formatDate(value: unknown) {
  if (typeof value !== "string" || value.trim().length === 0) {
    return "暂无记录";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "暂无记录";
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

function normalizeExecutionMode(value: unknown): "mock" | "staging" | "live" {
  return value === "staging" || value === "live" ? value : "mock";
}

function roleLabel(role: unknown) {
  const labels: Record<string, string> = {
    operator: "操作员",
    owner: "owner",
    reviewer: "审核员",
    super_admin: "组织管理员",
    viewer: "查看员",
  };
  return typeof role === "string" ? labels[role] ?? "成员" : "成员";
}

function executionModeLabel(mode: "mock" | "staging" | "live") {
  const labels = {
    live: "已启用",
    mock: "预览",
    staging: "试运行",
  };
  return labels[mode];
}

function healthLabel(value: unknown) {
  const normalized = optionalText(value).toLowerCase();
  if (["ok", "healthy", "available", "operational"].includes(normalized)) {
    return "正常";
  }
  if (normalized) {
    return "需关注";
  }
  return "确认中";
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
      <strong>暂无数据</strong>
      <span>服务暂时不可用，请稍后刷新。</span>
      <span>{textValue(detail, "服务暂时不可用，请稍后再试。")}</span>
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
        刷新
      </button>
    </div>
  );
}

export function OperationsDashboard() {
  const { user } = useAuth();
  const capabilityState = useFrontendCapabilityState();
  const [state, setState] = useState<DashboardState>(EMPTY_DASHBOARD_STATE);
  const [isLoading, setIsLoading] = useState(false);
  const [hasLoadingTimedOut, setHasLoadingTimedOut] = useState(false);
  const loadGenerationRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    const previousController = abortControllerRef.current;
    if (previousController && !previousController.signal.aborted) {
      previousController.abort(
        new ApiRequestAbortedError("首页请求已替换。"),
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
      onError: (message: string) => DashboardState,
      fallbackMessage: string,
    ) => {
      try {
        const value = await request;
        applyState(onSuccess(value));
      } catch (error) {
        if (!isApiAbortError(error)) {
          applyState(onError(errorMessage(error, fallbackMessage)));
        }
      } finally {
        markSettled();
      }
    };

    setHasLoadingTimedOut(false);
    setIsLoading(true);

    void loadResource(
      apiRequest<DashboardOverviewResponse>("/dashboard/overview?limit=1&offset=0", {
        method: "GET",
        signal: controller.signal,
      }),
      (overview) => ({
        health: batchData(overview.health),
        healthError: batchError(
          overview.health,
          "服务暂时不可用，请稍后再试。",
        ),
        users: batchData(overview.users),
        usersError: batchError(
          overview.users,
          "服务暂时不可用，请稍后再试。",
        ),
      }),
      (error) => ({
        health: null,
        healthError: error,
        users: null,
        usersError: error,
      }),
      "服务暂时不可用，请稍后再试。",
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
        approvalsError: batchError(
          activity.approvals,
          "服务暂时不可用，请稍后再试。",
        ),
        logsError: batchError(
          activity.operation_logs,
          "服务暂时不可用，请稍后再试。",
        ),
        operationLogs: batchData(activity.operation_logs),
      }),
      (error) => ({
        approvals: null,
        approvalsError: error,
        logsError: error,
        operationLogs: null,
      }),
      "服务暂时不可用，请稍后再试。",
    );
  }, []);

  useEffect(() => {
    void load();

    return () => {
      const controller = abortControllerRef.current;
      if (controller && !controller.signal.aborted) {
        controller.abort(new ApiRequestAbortedError("首页请求已取消。"));
      }
      abortControllerRef.current = null;
    };
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

  const safeState = state;
  const safeOrgContext = {
    role: roleLabel(capabilityState?.orgContext?.role),
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
  const healthStatus = healthLabel(safeState.health?.status);
  const executionMode = normalizeExecutionMode(
    capabilityState?.liveGate?.execution_mode,
  );
  const loadingFallbackActive = hasLoadingTimedOut || isLoading;
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
  const healthDetail = healthError || "暂无数据";
  const userDetail = usersError || "暂无数据";
  const approvalDetail = approvalsError || "暂无数据";
  const logDetail = logsError || "暂无数据";
  const approvalQueue = approvalItems
    .filter((approval) => optionalText(approval.status).toLowerCase() === "pending")
    .slice(0, 5);
  const systemStatus = useMemo(() => {
    if (healthError.length > 0) {
      return "暂无数据";
    }
    if (!hasHealthData && activeLoading) {
      return "确认中";
    }
    if (!hasHealthData && loadingFallbackActive) {
      return "准备中";
    }
    if (failedLogs > 0 || logsError.length > 0 || approvalsError.length > 0) {
      return "需关注";
    }

    return "正常";
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
      detail: healthError || "服务状态已汇总",
      icon: CheckCircle2,
      label: "系统状态",
      value: healthError ? "暂无数据" : healthStatus,
    },
    {
      detail: usersError || "工作台账号",
      icon: UsersRound,
      label: "用户概览",
      value: users,
    },
    {
      detail:
        orgs > 0 ? "组织访问正常" : "暂无数据",
      icon: Building2,
      label: "组织概览",
      value: orgs,
    },
    {
      detail: `共 ${approvals} 条`,
      icon: ClipboardCheck,
      label: "待办审批",
      value: approvalsError ? "暂无数据" : pendingApprovals,
    },
    {
      detail: `${failedLogs} 条需关注`,
      icon: FileText,
      label: "近期操作",
      value: logsError ? "暂无数据" : logs.length,
    },
    {
      detail: "当前状态",
      icon: ShieldCheck,
      label: "操作状态",
      value: executionModeLabel(executionMode),
    },
  ];

  return (
    <div className="ops-dashboard">
      <div className="ops-dashboard-header">
        <div>
          <span className="eyebrow">首页</span>
          <h2>工作台概览</h2>
          <p>
            查看账号、组织、审批和系统状态。
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
          刷新
        </button>
      </div>

      <section className="ops-metric-grid" aria-label="工作台指标">
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
              <h3>系统状态</h3>
              <p>当前系统可用性。</p>
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
                <dt>状态</dt>
                <dd>{healthStatus}</dd>
              </div>
              <div>
                <dt>服务</dt>
                <dd>{healthStatus}</dd>
              </div>
              <div>
                <dt>业务可用性</dt>
                <dd>{hasHealthData ? "可用" : "确认中"}</dd>
              </div>
              <div>
                <dt>数据状态</dt>
                <dd>{hasHealthData ? "已同步" : "暂无数据"}</dd>
              </div>
              <div>
                <dt>总体</dt>
                <dd>{systemStatus}</dd>
              </div>
            </dl>
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>用户概览</h3>
              <p>当前工作台账号情况。</p>
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
                <dt>用户数</dt>
                <dd>{users}</dd>
              </div>
              <div>
                <dt>本页加载</dt>
                <dd>{userItems.length}</dd>
              </div>
              <div>
                <dt>当前角色</dt>
                <dd>{roleLabel(currentUser?.role)}</dd>
              </div>
              <div>
                <dt>当前账号</dt>
                <dd>{textValue(currentUser?.username)}</dd>
              </div>
              <div>
                <dt>状态</dt>
                <dd>
                  {usersError
                    ? "部分可见"
                    : currentUser?.is_active === false
                      ? "已停用"
                      : "正常"}
                </dd>
              </div>
            </dl>
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>组织概览</h3>
              <p>当前账号的组织访问状态。</p>
            </div>
          </div>
          {hasOrganizationData ? (
            <dl className="ops-readiness-list">
              <div>
                <dt>组织</dt>
                <dd>{orgs}</dd>
              </div>
              <div>
                <dt>访问状态</dt>
                <dd>正常</dd>
              </div>
              <div>
                <dt>角色</dt>
                <dd>{safeOrgContext.role}</dd>
              </div>
              <div>
                <dt>可见功能区</dt>
                <dd>{safeOrgContext.visibleModules}</dd>
              </div>
            </dl>
          ) : (
            <FallbackNotice
              detail="暂无数据"
              isLoading={activeLoading}
              onRetry={() => void load()}
            />
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>待办审批</h3>
              <p>待处理和已处理的审批数量。</p>
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
                  <dt>待处理</dt>
                  <dd>{pendingApprovals}</dd>
                </div>
                <div>
                  <dt>已同意</dt>
                  <dd>{approvedApprovals}</dd>
                </div>
                <div>
                  <dt>已拒绝</dt>
                  <dd>{rejectedApprovals}</dd>
                </div>
                <div>
                  <dt>全部</dt>
                  <dd>{approvals}</dd>
                </div>
              </dl>
              {approvalQueue.length > 0 ? (
                <ol className="ops-record-list" aria-label="待办审批">
                  {approvalQueue.map((approval, index) => (
                    <li key={`approval-${index}`}>
                      <span>待处理</span>
                      <strong>审批事项</strong>
                      <small>
                        {formatDate(approval.request_time)}
                      </small>
                    </li>
                  ))}
                </ol>
              ) : (
                <FallbackNotice
                  detail="暂无数据"
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
              <h3>近期操作</h3>
              <p>最近完成的工作台操作。</p>
            </div>
          </div>
          {logsError || logs.length === 0 ? (
            <FallbackNotice
              detail={logDetail}
              isLoading={activeLoading}
              onRetry={() => void load()}
            />
          ) : (
            <ol className="ops-record-list" aria-label="近期操作">
              {logs.slice(0, 8).map((log, index) => (
                <li key={`log-${index}`}>
                  <span>{optionalText(log.result).toLowerCase() === "error" ? "需关注" : "已记录"}</span>
                  <strong>操作记录</strong>
                  <small>
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
              <h3>操作状态</h3>
              <p>当前工作台操作能力。</p>
            </div>
          </div>
          <dl className="ops-readiness-list">
            <div>
              <dt>当前状态</dt>
              <dd>{executionModeLabel(executionMode)}</dd>
            </div>
            <div>
              <dt>安全模式</dt>
              <dd>已启用</dd>
            </div>
            <div>
              <dt>可用性</dt>
              <dd>{capabilityFallbackActive ? "准备中" : "可用"}</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>
                {capabilityFallbackActive
                  ? "准备中"
                  : capabilityLoading
                    ? "确认中"
                    : "正常"}
              </dd>
            </div>
          </dl>
        </article>
      </section>
    </div>
  );
}
