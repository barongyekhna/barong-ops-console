"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DashboardScene } from "@/components/dashboard-scene";
import {
  ActivityFeed,
  DashboardSkeleton,
  MetricCard,
  type ActivityFeedItem,
  type ModuleCardStatus,
} from "@/components/dashboard-ui";
import {
  ApiRequestAbortedError,
  isApiAbortError,
} from "@/lib/api";

import { getVpnStatus } from "./api";
import {
  formatBytes,
  formatStatusTime,
  isVpnOnline,
  totalTransferBytes,
  type VpnStatus,
} from "./status";

const POLL_INTERVAL_MS = 15_000;

const STATUS_LABELS: Record<ModuleCardStatus, string> = {
  active: "可用",
  disabled: "待开放",
  error: "异常",
};

type StageCardProps = {
  actionLabel: string;
  badge: string;
  description: string;
  name: string;
  status: ModuleCardStatus;
};

function StageCard({
  actionLabel,
  badge,
  description,
  name,
  status,
}: StageCardProps) {
  return (
    <article className="module-card">
      <div className="module-card-header">
        <div>
          <span className={`status-pill ${status}`}>
            <span aria-hidden="true" />
            {STATUS_LABELS[status]}
          </span>
          <h3>{name}</h3>
        </div>
        <span className="subtle-badge">{badge}</span>
      </div>
      <p>{description}</p>
      <button className="module-card-action" disabled type="button">
        {actionLabel}
      </button>
    </article>
  );
}

function statusErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "VPN 状态暂时无法读取。";
}

function buildActivityItems(
  status: VpnStatus | null,
  error: string,
  updatedAt: number | null,
): ActivityFeedItem[] {
  if (!status) {
    return [
      {
        badge: error ? "unavailable" : "connecting",
        detail: error || "正在建立控制台到新 VPN 的只读状态通道。",
        meta: updatedAt
          ? formatStatusTime(new Date(updatedAt).toISOString())
          : "等待首次同步",
        title: "控制台安全通道",
        tone: error ? "error" : "disabled",
      },
    ];
  }

  const online = isVpnOnline(status);
  const listenPort = status.vpn.listen_port;
  const expectedPort = status.vpn.expected_listen_port;
  const portReady =
    listenPort !== null &&
    (expectedPort === null || listenPort === expectedPort);
  const peers = status.vpn.peer_count ?? 0;
  const activePeers = status.vpn.recently_active_peer_count ?? 0;
  const items: ActivityFeedItem[] = [
    {
      badge: error ? "stale" : "encrypted",
      detail: error
        ? `当前显示上次成功结果：${error}`
        : "控制台已通过受限加密通道读取新 VPN 状态。",
      meta: updatedAt
        ? formatStatusTime(new Date(updatedAt).toISOString())
        : "刚刚",
      title: "控制台安全通道",
      tone: error ? "error" : "active",
    },
    {
      badge: status.vpn.interface,
      detail: online ? "新 VPN 服务正在运行。" : "新 VPN 服务状态需要检查。",
      meta: `启动于 ${formatStatusTime(status.vpn.service.active_since)}`,
      title: "VPN 服务",
      tone: online ? "active" : "error",
    },
    {
      badge: portReady ? "ready" : "mismatch",
      detail:
        listenPort === null
          ? "监听端口暂时不可见。"
          : `当前监听 UDP ${listenPort}。`,
      meta:
        expectedPort === null
          ? "未设置期望端口"
          : `期望端口 UDP ${expectedPort}`,
      title: "高速入口",
      tone: portReady ? "active" : "error",
    },
    {
      badge: activePeers > 0 ? "online" : "waiting",
      detail:
        peers > 0
          ? `已创建 ${peers} 台设备，近期在线 ${activePeers} 台。`
          : "尚未创建成员设备，下一阶段将开放逐设备接入。",
      meta: status.vpn.latest_handshake_at
        ? `最后握手 ${formatStatusTime(status.vpn.latest_handshake_at)}`
        : "暂无设备握手",
      title: "成员设备",
      tone: activePeers > 0 ? "active" : "disabled",
    },
  ];

  for (const warning of status.warnings.slice(0, 2)) {
    items.push({
      badge: "warning",
      detail: warning,
      meta: "新 VPN 状态代理",
      title: "状态提醒",
      tone: "error",
    });
  }
  return items;
}

export function VpnDashboard() {
  const [status, setStatus] = useState<VpnStatus | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const requestGenerationRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const load = useCallback(
    async ({ silent = false }: { silent?: boolean } = {}) => {
      const previousController = abortControllerRef.current;
      if (previousController && !previousController.signal.aborted) {
        previousController.abort(
          new ApiRequestAbortedError("VPN status request superseded."),
        );
      }

      const controller = new AbortController();
      const generation = requestGenerationRef.current + 1;
      requestGenerationRef.current = generation;
      abortControllerRef.current = controller;
      if (!silent) {
        setIsLoading(true);
      }

      try {
        const nextStatus = await getVpnStatus(controller.signal);
        if (
          !controller.signal.aborted &&
          requestGenerationRef.current === generation
        ) {
          setStatus(nextStatus);
          setError("");
          setUpdatedAt(Date.now());
        }
      } catch (loadError) {
        if (
          !isApiAbortError(loadError) &&
          requestGenerationRef.current === generation
        ) {
          setError(statusErrorMessage(loadError));
        }
      } finally {
        if (requestGenerationRef.current === generation) {
          abortControllerRef.current = null;
          setIsLoading(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    void load();

    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") {
        void load({ silent: true });
      }
    };
    const intervalId = window.setInterval(
      refreshWhenVisible,
      POLL_INTERVAL_MS,
    );
    window.addEventListener("focus", refreshWhenVisible);
    document.addEventListener("visibilitychange", refreshWhenVisible);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", refreshWhenVisible);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      requestGenerationRef.current += 1;
      const controller = abortControllerRef.current;
      if (controller && !controller.signal.aborted) {
        controller.abort(
          new ApiRequestAbortedError("VPN status request canceled."),
        );
      }
      abortControllerRef.current = null;
    };
  }, [load]);

  const online = isVpnOnline(status);
  const peerCount = status?.vpn.peer_count;
  const activePeerCount = status?.vpn.recently_active_peer_count;
  const transfer = totalTransferBytes(status);
  const activityItems = useMemo(
    () => buildActivityItems(status, error, updatedAt),
    [error, status, updatedAt],
  );

  const headerStatus =
    isLoading && !status
      ? "连接中"
      : error
        ? "读取异常"
        : online
          ? "服务在线"
          : "服务异常";

  return (
    <div className="dashboard-page cc-dash">
      <DashboardScene />

      <div className="cc-head">
        <div>
          <span className="eyebrow">VPN CONTROL</span>
          <h2>VPN 连接中心</h2>
        </div>
        <div className="cc-head-right">
          <span className="cc-status">{headerStatus}</span>
          <button
            className="cc-customize"
            disabled={isLoading}
            onClick={() => void load()}
            type="button"
          >
            {isLoading ? "↻ 同步中" : "↻ 刷新"}
          </button>
        </div>
      </div>

      {isLoading && !status && !error ? (
        <DashboardSkeleton />
      ) : (
        <div className="cc-grid">
          <div className="cc-card">
            <MetricCard
              detail={`${status?.vpn.interface ?? "awg0"} · ${status?.vpn.address ?? "地址待同步"}`}
              label="新 VPN 服务"
              value={online ? "在线" : "异常"}
            />
          </div>
          <div className="cc-card">
            <MetricCard
              detail="每台设备使用独立配置"
              label="成员设备"
              value={peerCount ?? "—"}
            />
          </div>
          <div className="cc-card">
            <MetricCard
              detail={
                status?.vpn.latest_handshake_at
                  ? `最后握手 ${formatStatusTime(status.vpn.latest_handshake_at)}`
                  : "暂无设备握手"
              }
              label="近期在线"
              value={activePeerCount ?? "—"}
            />
          </div>
          <div className="cc-card">
            <MetricCard
              detail={`接收 ${formatBytes(status?.vpn.transfer.received_bytes)} · 发送 ${formatBytes(status?.vpn.transfer.sent_bytes)}`}
              label="累计流量"
              value={formatBytes(transfer)}
            />
          </div>

          <div className="cc-card">
            <StageCard
              actionLabel="只读监控"
              badge="AWG0"
              description={
                !status
                  ? "控制台暂时无法读取新 VPN 服务状态。"
                  : online
                  ? `新 VPN 正在 UDP ${status?.vpn.listen_port ?? "—"} 端口稳定运行。`
                  : "状态通道可用，但新 VPN 服务当前未达到在线条件。"
              }
              name="新 VPN 服务"
              status={online ? "active" : "error"}
            />
          </div>
          <div className="cc-card">
            <StageCard
              actionLabel={peerCount ? `${peerCount} 台设备` : "尚未创建设备"}
              badge="MULTI-USER"
              description="下一阶段为每位成员创建独立设备配置，彼此可单独停用。"
              name="多人设备接入"
              status={peerCount && peerCount > 0 ? "active" : "disabled"}
            />
          </div>
          <div className="cc-card">
            <StageCard
              actionLabel="尚未开放"
              badge="NEXT STAGE"
              description="控制台内的一键连接与断开需要下一阶段的设备授权接口。"
              name="一键连接"
              status="disabled"
            />
          </div>

          <div className="cc-card wide">
            <ActivityFeed items={activityItems} />
          </div>
        </div>
      )}
    </div>
  );
}
