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
    null
  );
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "未记录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError && error.status === 401) {
    return "请重新登录后再操作。";
  }
  if (error instanceof ApiError && error.status === 403) {
    return "当前账号无权访问。";
  }
  return "加载失败，请稍后重试。";
}

function isFailedLog(log: OperationLogRecord) {
  return log.result === "error" || Boolean(log.error_code);
}

function actionLabel(log: OperationLogRecord) {
  void log;
  return "操作记录";
}

export function OperationLogsCenter() {
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
      <section className="list-state" aria-label="正在加载操作记录">
        <LoaderCircle className="spin" aria-hidden="true" size={22} />
        <span>正在加载</span>
      </section>
    );
  }

  if (error) {
    return (
      <CapabilityEmptyStateEngine
        action={
          <button className="primary-button" onClick={() => void load()}>
            <RotateCcw aria-hidden="true" size={17} />
            重试
          </button>
        }
        reason={error}
        required_execution_mode="可查看。"
        required_module_state="功能区可用。"
        required_org_state="组织状态正常。"
        required_permission="operation_logs.read"
        state="missing_feature"
        title="加载失败，请稍后重试"
        unlock_condition="稍后重试。"
      />
    );
  }

  return (
    <section className="observability-workspace" aria-label="操作记录">
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">系统</span>
          <h2>操作记录</h2>
          <p>
            查看最近操作的整体状态，不展示内部请求标识。
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void load()}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={17} />
          刷新
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>操作记录</span>
          <strong>{result?.count ?? 0}</strong>
        </div>
        <div>
          <span>关联组</span>
          <strong>{traces.length}</strong>
        </div>
        <div>
          <span>异常</span>
          <strong>{failedLogs.length}</strong>
        </div>
        <div>
          <span>风险信号</span>
          <strong>{actionCounts.length + (missingTraceCount > 0 ? 1 : 0)}</strong>
        </div>
      </div>

      <div className="observability-grid">
        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>最近操作</h3>
              <p>仅展示业务状态和时间。</p>
            </div>
            <span className="ops-source">当前页</span>
          </div>
          <ol className="ops-record-list">
            {logs.slice(0, 8).map((log) => (
              <li key={log.operation_id ?? `${log.action}-${log.created_at}`}>
                <span>{isFailedLog(log) ? "异常" : "完成"}</span>
                <strong>操作记录</strong>
                <small>{formatDate(log.created_at)}</small>
              </li>
            ))}
            {logs.length === 0 ? (
              <li>
                <span>暂无</span>
                <strong>暂无数据</strong>
                <small>有操作后会显示在这里。</small>
              </li>
            ) : null}
          </ol>
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>关联分组</h3>
              <p>按可用关联信息统计。</p>
            </div>
            <span className="ops-source">已汇总</span>
          </div>
          <div className="ops-trace-grid">
            {traces.slice(0, 8).map(([key, log]) => (
              <div key={key ?? log.operation_id}>
                <FileSearch aria-hidden="true" size={17} />
                <strong>关联记录</strong>
                <span>{formatDate(log.created_at)}</span>
              </div>
            ))}
            {traces.length === 0 ? (
              <div>
                <CircleAlert aria-hidden="true" size={17} />
                <strong>暂无数据</strong>
                <span>当前没有可显示的关联分组。</span>
              </div>
            ) : null}
          </div>
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>异常</h3>
              <p>来自失败操作的待关注记录。</p>
            </div>
            <span className="ops-source">待关注</span>
          </div>
          <ol className="ops-record-list">
            {failedLogs.slice(0, 6).map((log) => (
              <li key={log.operation_id ?? `${log.action}-${log.error_code}`}>
                <span>异常</span>
                <strong>操作失败</strong>
                <small>{formatDate(log.created_at)}</small>
              </li>
            ))}
            {failedLogs.length === 0 ? (
              <li>
                <span>正常</span>
                <strong>暂无异常</strong>
                <small>失败操作会显示在这里。</small>
              </li>
            ) : null}
          </ol>
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>风险信号</h3>
              <p>根据重复操作和缺失关联信息汇总。</p>
            </div>
            <span className="ops-source">已汇总</span>
          </div>
          <ol className="ops-record-list">
            {actionCounts.slice(0, 5).map(([actionKey, count]) => (
              <li key={actionKey}>
                <span>频次</span>
                <strong>重复操作</strong>
                <small>当前页 {count} 条</small>
              </li>
            ))}
            {missingTraceCount > 0 ? (
              <li>
                <span>关联</span>
                <strong>缺少关联信息</strong>
                <small>{missingTraceCount} 条记录缺少关联信息。</small>
              </li>
            ) : null}
            {actionCounts.length === 0 && missingTraceCount === 0 ? (
              <li>
                <span>正常</span>
                <strong>暂无风险信号</strong>
                <small>重复操作或缺失关联信息会显示在这里。</small>
              </li>
            ) : null}
          </ol>
        </article>
      </div>

      <div className="observability-band">
        <Bell aria-hidden="true" size={18} />
        <span>操作记录</span>
        <Activity aria-hidden="true" size={18} />
        <span>关联</span>
        <CircleAlert aria-hidden="true" size={18} />
        <span>异常</span>
        <FileSearch aria-hidden="true" size={18} />
        <span>信号</span>
      </div>
    </section>
  );
}
