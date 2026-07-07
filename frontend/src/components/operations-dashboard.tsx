"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { ConsoleArcade } from "@/components/console-arcade";
import { DashboardScene } from "@/components/dashboard-scene";
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
import { getModuleDisplayName } from "@/lib/i18n";

const DASH_STORAGE_KEY = "barong-dash-cards-v1";
const DEFAULT_DASH_CARDS = ["m-modules", "m-approvals", "activity"];

type DashCard = {
  desc: string;
  group: "指标" | "模块" | "动态";
  id: string;
  name: string;
  node: ReactNode;
  wide?: boolean;
};

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

function textValue(value: unknown, fallback = "暂无数据") {
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
  return entry?.ok === true ? "" : "数据暂时不可用。";
}

function formatDate(value: unknown) {
  if (typeof value !== "string" || value.trim().length === 0) {
    return "暂无时间";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "暂无时间";
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
    return "可进入工作台操作。";
  }
  if (status === "error") {
    return "运行前需要处理异常。";
  }
  return "完成配置或授权后可用。";
}

function moduleActionLabel(status: ModuleCardStatus) {
  return status === "active" ? "打开模块" : "暂不可用";
}

function moduleBadge(item: ProductCapabilityItem) {
  if (item.badge) {
    const badgeLabels: Record<string, string> = {
      adapter_pending: "配置中",
      backend_unavailable: "后端不可用",
      locked: "受限",
      mock: "预览",
      no_execution: "待配置",
      read_only: "部分可用",
    };
    return badgeLabels[item.badge] ?? "状态待确认";
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
        ? "执行完成但存在异常。"
        : "执行已成功完成。",
      meta: formatDate(log.created_at),
      title: "执行记录",
      tone: failed ? "error" : "active",
    };
  });

  const moduleItems: ActivityFeedItem[] = modules.slice(0, 3).map((item) => {
    const status = moduleStatus(item);
    return {
      badge: status,
      detail: `${getModuleDisplayName(item.module_key, item.label)}状态：${moduleDescription(status)}`,
      meta: item.nav_group,
      title: "模块动态",
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
      ? "已记录脱敏API密钥使用。"
      : "暂无近期API密钥使用记录。",
    meta: apiLog ? formatDate(apiLog.created_at) : "已脱敏",
    title: "API密钥使用",
    tone: apiLog ? "active" : "disabled",
  };

  const items = [...executionItems, ...moduleItems, apiItem];
  if (items.length > 1) {
    return items.slice(0, 8);
  }

  return [
    {
      badge: "ready",
      detail: "工作台模块可供查看。",
      meta: "系统",
      title: "模块动态",
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
        healthError: "数据暂时不可用。",
        users: null,
        usersError: "数据暂时不可用。",
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
        approvalsError: "数据暂时不可用。",
        logsError: "数据暂时不可用。",
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
      name: getModuleDisplayName(item.module_key, item.label),
      status,
    };
  });
  const activityItems = useMemo(
    () => buildActivityFeed({ logs, modules }),
    [logs, modules],
  );

  const [visible, setVisible] = useState<string[]>(DEFAULT_DASH_CARDS);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(DASH_STORAGE_KEY);
      if (stored) {
        const parsed: unknown = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.every((item) => typeof item === "string")) {
          setVisible(parsed as string[]);
        }
      }
    } catch {
      /* localStorage 不可用时忽略 */
    }
  }, []);

  const persist = (next: string[]) => {
    setVisible(next);
    try {
      window.localStorage.setItem(DASH_STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* 忽略持久化失败 */
    }
  };

  const setCardVisible = (id: string, on: boolean) => {
    persist(
      on
        ? visible.includes(id)
          ? visible
          : [...visible, id]
        : visible.filter((value) => value !== id),
    );
  };

  const cards: DashCard[] = [
    {
      desc: "活跃模块数",
      group: "指标",
      id: "m-modules",
      name: "可用模块",
      node: (
        <MetricCard
          detail={`${capabilityState.sidebarItems.length} 个可见模块`}
          label="可用模块"
          value={activeModules}
        />
      ),
    },
    {
      desc: "近期执行数",
      group: "指标",
      id: "m-exec",
      name: "执行记录",
      node: (
        <MetricCard
          detail={state.logsError ? "数据等待同步" : "近期执行记录"}
          label="执行记录"
          value={executionCount}
        />
      ),
    },
    {
      desc: "执行成功比例",
      group: "指标",
      id: "m-success",
      name: "成功率",
      node: (
        <MetricCard
          detail={`最近记录中 ${failedLogs} 条异常`}
          label="成功率"
          value={`${successRate}%`}
        />
      ),
    },
    {
      desc: "等待处理的审核",
      group: "指标",
      id: "m-approvals",
      name: "待处理审核",
      node: (
        <MetricCard
          detail={state.approvalsError ? "审核数据等待同步" : "等待处理"}
          label="待处理审核"
          value={pendingApprovals}
        />
      ),
    },
    ...moduleCards.map((module, index) => ({
      desc: module.badge,
      group: "模块" as const,
      id: `mod-${modules[index]?.module_key ?? index}`,
      name: module.name,
      node: <ModuleCard {...module} />,
    })),
    {
      desc: "实时执行 / 事件流",
      group: "动态",
      id: "activity",
      name: "活动动态",
      node: <ActivityFeed items={activityItems} />,
      wide: true,
    },
  ];

  const visibleCards = cards.filter((card) => visible.includes(card.id));
  const groups: Array<DashCard["group"]> = ["指标", "模块", "动态"];

  return (
    <div className="dashboard-page cc-dash">
      <DashboardScene />

      <div className="cc-head">
        <div>
          <span className="eyebrow">工作台</span>
          <h2>控制台概览</h2>
        </div>
        <div className="cc-head-right">
          <span className="cc-status">{isLoading ? "同步中" : "就绪"}</span>
          <button className="cc-customize" onClick={() => setDrawerOpen(true)} type="button">
            ⚙ 定制
          </button>
        </div>
      </div>

      {isLoading && cards.length === 0 ? (
        <DashboardSkeleton />
      ) : visibleCards.length === 0 ? (
        <div className="cc-empty">
          <b>工作台是空的 ✨</b>
          <span>点右上「⚙ 定制」把你需要的卡片调出来</span>
          <button className="cc-customize" onClick={() => setDrawerOpen(true)} type="button">
            ⚙ 打开卡片库
          </button>
        </div>
      ) : (
        <div className="cc-grid">
          {visibleCards.map((card) => (
            <div className={card.wide ? "cc-card wide" : "cc-card"} key={card.id}>
              <button
                aria-label={`收起「${card.name}」`}
                className="cc-hide"
                onClick={() => setCardVisible(card.id, false)}
                type="button"
              >
                ×
              </button>
              {card.node}
            </div>
          ))}
          <button className="cc-add" onClick={() => setDrawerOpen(true)} type="button">
            <span className="cc-add-plus">＋</span>
            <span>添加卡片</span>
          </button>
        </div>
      )}

      <ConsoleArcade />

      {drawerOpen ? (
        <>
          <button
            aria-label="关闭卡片库"
            className="cc-scrim"
            onClick={() => setDrawerOpen(false)}
            type="button"
          />
          <aside aria-label="卡片库" className="cc-drawer">
            <div className="cc-drawer-head">
              <div>
                <h3>卡片库</h3>
                <span>开关任意卡片 · 选择会被记住</span>
              </div>
              <button
                aria-label="关闭"
                className="cc-drawer-close"
                onClick={() => setDrawerOpen(false)}
                type="button"
              >
                ×
              </button>
            </div>
            <div className="cc-drawer-body">
              {groups.map((group) => {
                const groupCards = cards.filter((card) => card.group === group);
                if (groupCards.length === 0) {
                  return null;
                }
                return (
                  <div key={group}>
                    <div className="cc-group">{group}</div>
                    {groupCards.map((card) => {
                      const on = visible.includes(card.id);
                      return (
                        <div className="cc-lib" key={card.id}>
                          <div>
                            <div className="cc-lib-name">{card.name}</div>
                            <div className="cc-lib-desc">{card.desc}</div>
                          </div>
                          <button
                            aria-label={on ? `隐藏「${card.name}」` : `显示「${card.name}」`}
                            aria-pressed={on}
                            className={on ? "cc-switch on" : "cc-switch"}
                            onClick={() => setCardVisible(card.id, !on)}
                            type="button"
                          />
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
            <div className="cc-drawer-foot">
              <button onClick={() => persist(DEFAULT_DASH_CARDS)} type="button">
                恢复默认
              </button>
              <button onClick={() => persist([])} type="button">
                全部收起
              </button>
            </div>
          </aside>
        </>
      ) : null}
    </div>
  );
}
