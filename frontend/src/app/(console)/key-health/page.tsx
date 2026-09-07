"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { DashboardScene } from "@/components/dashboard-scene";
import { apiRequest } from "@/lib/api";
import { isOwnerRole } from "@/lib/roles";

import styles from "./KeyHealth.module.css";

type Run = {
  id: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  total_count: number;
  healthy_count: number;
  warning_count: number;
  failed_count: number;
};

type Binding = {
  module_id: string;
  key_alias: string;
};

type HealthItem = {
  key_id: string;
  key_name: string;
  key_hash_prefix: string;
  key_type: string;
  adapter: string | null;
  status: string;
  reason_code: string;
  last_checked_at: string | null;
  consecutive_failures: number;
  details: Record<string, unknown>;
  bindings: Binding[];
};

type Summary = {
  generated_at: string;
  interval_minutes: number;
  latest_run: Run | null;
  counts: {
    total: number;
    healthy: number;
    warning: number;
    failed: number;
    never_checked: number;
  };
  items: HealthItem[];
};

const statusLabels: Record<string, string> = {
  healthy: "正常",
  pending_review: "审核中",
  rate_limited: "限流",
  invalid: "无效",
  malformed: "配置异常",
  provider_error: "供应商异常",
  unreachable: "不可达",
  unsupported: "待配置检测",
  never_checked: "未检测",
};

const reasonLabels: Record<string, string> = {
  models_list_ok: "模型列表响应正常",
  minimal_search_ok: "最小搜索响应正常",
  token_status_ok: "令牌状态响应正常",
  account_status_ok: "账户状态响应正常",
  keyword_ideas_probe_ok: "关键词规划请求正常",
  basic_access_review_pending: "Google Ads Basic 权限审核中",
  credential_structure_and_gateway_ok: "凭据结构与官方网关正常",
  not_yet_checked: "等待首次检测",
  authentication_rejected: "认证被供应商拒绝",
  provider_rate_limited: "供应商当前限流",
  provider_network_error: "供应商网络不可达",
  required_4sapi_proxy_route_missing: "未使用规定的 4sapi 代理",
  probe_adapter_not_available: "尚无安全的只读检测适配器",
  non_mutating_probe_not_configured: "未配置无副作用检测端点",
  secret_decryption_failed: "密钥解密失败",
  access_token_expired: "访问令牌已过期",
  oauth_refresh_rejected: "OAuth 刷新失败",
  provider_credits_exhausted: "余额已耗尽（需充值）",
  provider_quota_exhausted: "套餐额度用完（业务调用回报）",
  runtime_call_ok: "业务调用已恢复正常",
};

function statusClass(status: string) {
  if (status === "healthy") return styles.healthy;
  if (status === "pending_review" || status === "rate_limited") {
    return styles.warning;
  }
  if (status === "never_checked") return styles.idle;
  return styles.failed;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "healthy") return <CheckCircle2 aria-hidden="true" />;
  if (status === "never_checked") return <Clock3 aria-hidden="true" />;
  return <AlertTriangle aria-hidden="true" />;
}

function formatTime(value: string | null) {
  if (!value) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "medium",
    hour12: false,
  }).format(new Date(value));
}

function detailNumber(item: HealthItem, key: string) {
  const value = item.details[key];
  return typeof value === "number" ? value : null;
}

// DeepSeek 探针附带的余额：{ currency, total_balance }。
function detailBalance(item: HealthItem) {
  const value = item.details.balance;
  if (!value || typeof value !== "object") return null;
  const record = value as { currency?: unknown; total_balance?: unknown };
  if (typeof record.total_balance !== "number") return null;
  const currency = typeof record.currency === "string" ? record.currency : "";
  return `${record.total_balance.toFixed(2)}${currency ? ` ${currency}` : ""}`;
}

// 业务 worker 回报的运行时事故（余额 0 / 套餐额度用完），探针看不见的那种。
function detailIncident(item: HealthItem) {
  const value = item.details.runtime_incident;
  if (!value || typeof value !== "object") return null;
  const record = value as { message?: unknown; source?: unknown; reported_at?: unknown };
  const message = typeof record.message === "string" ? record.message : "";
  if (!message) return null;
  const source = typeof record.source === "string" ? record.source : "worker";
  const reportedAt =
    typeof record.reported_at === "string" ? ` · ${formatTime(record.reported_at)}` : "";
  return `${source} 回报：${message}${reportedAt}`;
}

export default function KeyHealthPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isOwner = isOwnerRole(user?.role);

  const loadSummary = useCallback(async () => {
    try {
      const result = await apiRequest<Summary>("/key-health/summary", {
        bypassCache: true,
      });
      setSummary(result);
      setError(null);
    } catch {
      setError("检测结果暂时无法读取");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isOwner) return;
    void loadSummary();
    const timer = window.setInterval(() => void loadSummary(), 60_000);
    return () => window.clearInterval(timer);
  }, [isOwner, loadSummary]);

  const runNow = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      await apiRequest("/key-health/run", {
        method: "POST",
        timeoutMs: 180_000,
      });
      await loadSummary();
    } catch {
      setError("检测未能完成，请查看通知或稍后重试");
    } finally {
      setRunning(false);
    }
  }, [loadSummary]);

  const orderedItems = useMemo(() => {
    const priority: Record<string, number> = {
      invalid: 0,
      malformed: 0,
      provider_error: 0,
      unreachable: 0,
      unsupported: 0,
      pending_review: 1,
      rate_limited: 1,
      never_checked: 2,
      healthy: 3,
    };
    return [...(summary?.items ?? [])].sort(
      (left, right) =>
        (priority[left.status] ?? 2) - (priority[right.status] ?? 2) ||
        left.key_name.localeCompare(right.key_name, "zh-CN"),
    );
  }, [summary]);

  if (!isOwner) return null;

  return (
    <main className={`cc-dash ${styles.page}`}>
      <DashboardScene />
      <div className={styles.content}>
        <header className={styles.header}>
          <div className={styles.titleBlock}>
            <div className={styles.eyebrow}>
              <ShieldCheck aria-hidden="true" />
              OWNER SECURITY / KEY HEALTH
            </div>
            <h1>密钥检测</h1>
            <p>
              {summary?.latest_run
                ? `最近完成 ${formatTime(summary.latest_run.completed_at)}`
                : "等待首次检测"}
            </p>
          </div>
          <button
            className={styles.runButton}
            disabled={running}
            onClick={() => void runNow()}
            title="立即执行一次密钥检测"
            type="button"
          >
            <RefreshCw className={running ? styles.spinning : undefined} aria-hidden="true" />
            {running ? "检测中" : "立即检测"}
          </button>
        </header>

        <section className={styles.metrics} aria-label="检测概览">
          <div className={styles.metric}>
            <span>全部密钥</span>
            <strong>{summary?.counts.total ?? "--"}</strong>
          </div>
          <div className={`${styles.metric} ${styles.metricHealthy}`}>
            <span>正常</span>
            <strong>{summary?.counts.healthy ?? "--"}</strong>
          </div>
          <div className={`${styles.metric} ${styles.metricWarning}`}>
            <span>警告</span>
            <strong>{summary?.counts.warning ?? "--"}</strong>
          </div>
          <div className={`${styles.metric} ${styles.metricFailed}`}>
            <span>失败</span>
            <strong>{summary?.counts.failed ?? "--"}</strong>
          </div>
        </section>

        <div className={styles.scheduleLine}>
          <span className={styles.liveDot} />
          自动检测周期 {summary?.interval_minutes ?? 60} 分钟
          {summary?.generated_at ? ` · 刷新 ${formatTime(summary.generated_at)}` : ""}
        </div>

        {error ? <div className={styles.errorBanner}>{error}</div> : null}

        <section className={styles.keyList} aria-busy={loading || running}>
          {loading ? <div className={styles.empty}>正在读取检测状态...</div> : null}
          {!loading && orderedItems.length === 0 ? (
            <div className={styles.empty}>密钥库中没有启用的密钥</div>
          ) : null}
          {orderedItems.map((item) => {
            const latency = detailNumber(item, "latency_ms");
            const tokensLeft = detailNumber(item, "tokens_left");
            const balance = detailBalance(item);
            const incident = detailIncident(item);
            return (
              <article className={styles.keyRow} key={item.key_id}>
                <div className={styles.keyIdentity}>
                  <div className={styles.keyName}>{item.key_name}</div>
                  <div className={styles.keyMeta}>
                    <span>{item.key_type}</span>
                    <span>HASH {item.key_hash_prefix}</span>
                    {item.adapter ? <span>{item.adapter}</span> : null}
                  </div>
                </div>

                <div className={styles.bindings}>
                  {item.bindings.map((binding) => (
                    <span key={`${binding.module_id}:${binding.key_alias}`}>
                      {binding.module_id} / {binding.key_alias}
                    </span>
                  ))}
                </div>

                <div className={styles.resultMeta}>
                  <strong>{reasonLabels[item.reason_code] ?? item.reason_code}</strong>
                  <span>
                    {formatTime(item.last_checked_at)}
                    {latency !== null ? ` · ${latency} ms` : ""}
                    {tokensLeft !== null ? ` · ${tokensLeft} tokens` : ""}
                    {balance ? ` · 余额 ${balance}` : ""}
                  </span>
                  {incident ? <span className={styles.incidentNote}>{incident}</span> : null}
                </div>

                <div className={`${styles.status} ${statusClass(item.status)}`}>
                  <StatusIcon status={item.status} />
                  <span>{statusLabels[item.status] ?? item.status}</span>
                </div>
              </article>
            );
          })}
        </section>
      </div>
    </main>
  );
}
