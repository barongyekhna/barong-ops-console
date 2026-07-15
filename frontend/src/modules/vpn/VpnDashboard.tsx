"use client";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { DashboardScene } from "@/components/dashboard-scene";
import {
  DashboardSkeleton,
  MetricCard,
  type ModuleCardStatus,
} from "@/components/dashboard-ui";
import { ApiRequestAbortedError, isApiAbortError } from "@/lib/api";

import {
  createVpnDevice,
  getVpnDevices,
  getVpnStatus,
  setVpnDeviceEnabled,
} from "./api";
import {
  platformLabel,
  type CreatedVpnDevice,
  type VpnDevice,
  type VpnDevicePlatform,
} from "./devices";
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

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function configurationFilename(device: VpnDevice): string {
  const safeName = device.name.replace(/[^\p{L}\p{N}._-]+/gu, "-");
  return `${safeName || "barong-vpn"}.conf`;
}

export function VpnDashboard() {
  const [status, setStatus] = useState<VpnStatus | null>(null);
  const [devices, setDevices] = useState<VpnDevice[]>([]);
  const [statusError, setStatusError] = useState("");
  const [deviceError, setDeviceError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isMutating, setIsMutating] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [deviceName, setDeviceName] = useState("");
  const [platform, setPlatform] = useState<VpnDevicePlatform>("windows");
  const [oneTimeDevice, setOneTimeDevice] =
    useState<CreatedVpnDevice | null>(null);
  const [copyMessage, setCopyMessage] = useState("");
  const requestGenerationRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const load = useCallback(
    async ({ silent = false }: { silent?: boolean } = {}) => {
      const previousController = abortControllerRef.current;
      if (previousController && !previousController.signal.aborted) {
        previousController.abort(
          new ApiRequestAbortedError("VPN request superseded."),
        );
      }
      const controller = new AbortController();
      const generation = requestGenerationRef.current + 1;
      requestGenerationRef.current = generation;
      abortControllerRef.current = controller;
      if (!silent) {
        setIsLoading(true);
      }

      const [statusResult, devicesResult] = await Promise.allSettled([
        getVpnStatus(controller.signal),
        getVpnDevices(controller.signal),
      ]);
      if (
        controller.signal.aborted ||
        requestGenerationRef.current !== generation
      ) {
        return;
      }

      if (statusResult.status === "fulfilled") {
        setStatus(statusResult.value);
        setStatusError("");
      } else if (!isApiAbortError(statusResult.reason)) {
        setStatusError(
          errorMessage(statusResult.reason, "VPN 状态暂时无法读取。"),
        );
      }
      if (devicesResult.status === "fulfilled") {
        setDevices(devicesResult.value);
        setDeviceError("");
      } else if (!isApiAbortError(devicesResult.reason)) {
        setDeviceError(
          errorMessage(devicesResult.reason, "我的 VPN 设备暂时无法读取。"),
        );
      }
      abortControllerRef.current = null;
      setIsLoading(false);
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
    const intervalId = window.setInterval(refreshWhenVisible, POLL_INTERVAL_MS);
    window.addEventListener("focus", refreshWhenVisible);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", refreshWhenVisible);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      requestGenerationRef.current += 1;
      const controller = abortControllerRef.current;
      if (controller && !controller.signal.aborted) {
        controller.abort(new ApiRequestAbortedError("VPN request canceled."));
      }
      abortControllerRef.current = null;
    };
  }, [load]);

  const openCreateDrawer = () => {
    setOneTimeDevice(null);
    setCopyMessage("");
    setDeviceError("");
    setDrawerOpen(true);
  };

  const closeDrawer = () => {
    setDrawerOpen(false);
    setOneTimeDevice(null);
    setCopyMessage("");
  };

  const submitDevice = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = deviceName.trim();
    if (!name) {
      setDeviceError("请填写设备名称。");
      return;
    }
    setIsMutating(true);
    setDeviceError("");
    try {
      const created = await createVpnDevice({ name, platform });
      setDevices((current) => [...current, created.device]);
      setOneTimeDevice(created);
      setDeviceName("");
      setCopyMessage("");
      void load({ silent: true });
    } catch (error) {
      setDeviceError(errorMessage(error, "设备创建失败，请稍后重试。"));
    } finally {
      setIsMutating(false);
    }
  };

  const toggleDevice = async (device: VpnDevice) => {
    setIsMutating(true);
    setDeviceError("");
    try {
      const updated = await setVpnDeviceEnabled(device.id, !device.enabled);
      setDevices((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      void load({ silent: true });
    } catch (error) {
      setDeviceError(errorMessage(error, "设备状态更新失败，请稍后重试。"));
    } finally {
      setIsMutating(false);
    }
  };

  const copyConfiguration = async () => {
    if (!oneTimeDevice) {
      return;
    }
    try {
      await navigator.clipboard.writeText(oneTimeDevice.configuration);
      setCopyMessage("配置已复制。请立即保存，关闭后无法再次查看。");
    } catch {
      setCopyMessage("浏览器未允许复制，请使用下载配置。");
    }
  };

  const downloadConfiguration = () => {
    if (!oneTimeDevice) {
      return;
    }
    const blob = new Blob([oneTimeDevice.configuration], {
      type: "text/plain;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = configurationFilename(oneTimeDevice.device);
    anchor.click();
    URL.revokeObjectURL(url);
    setCopyMessage("配置已下载。关闭后无法再次查看。");
  };

  const online = isVpnOnline(status);
  const peerCount = status?.vpn.peer_count;
  const activePeerCount = status?.vpn.recently_active_peer_count;
  const transfer = totalTransferBytes(status);
  const headerStatus =
    isLoading && !status
      ? "连接中"
      : statusError
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

      {isLoading && !status && !statusError ? (
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
              detail="所有成员设备总数"
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
              actionLabel="实时监控"
              badge="AWG0"
              description={
                !status
                  ? "控制台暂时无法读取新 VPN 服务状态。"
                  : online
                    ? `新 VPN 正在 UDP ${status.vpn.listen_port ?? "—"} 端口稳定运行。`
                    : "状态通道可用，但新 VPN 服务当前未达到在线条件。"
              }
              name="新 VPN 服务"
              status={online ? "active" : "error"}
            />
          </div>
          <div className="cc-card">
            <StageCard
              actionLabel={`${devices.length} 台我的设备`}
              badge="MULTI-USER"
              description="每位登录用户都能创建自己的独立设备，并且只能管理自己的设备。"
              name="多人设备接入"
              status={deviceError ? "error" : "active"}
            />
          </div>
          <div className="cc-card">
            <StageCard
              actionLabel="等待控制台 App"
              badge="NEXT STAGE"
              description="设备授权接口已经准备好，控制台 App 接入后即可实现内置一键连接。"
              name="一键连接"
              status="disabled"
            />
          </div>

          <div className="cc-card wide">
            <article className="module-card">
              <div className="module-card-header">
                <div>
                  <span className="status-pill active">
                    <span aria-hidden="true" />
                    本人可见
                  </span>
                  <h3>我的 VPN 设备</h3>
                </div>
                <span className="subtle-badge">{devices.length}/10</span>
              </div>
              <p>
                每台设备都有独立地址，可单独停用；其他用户无法查看或操作这些设备。
              </p>
              <button
                className="module-card-action"
                disabled={isMutating || devices.length >= 10}
                onClick={openCreateDrawer}
                type="button"
              >
                ＋ 添加设备
              </button>
              {deviceError ? (
                <div className="form-message" role="alert">
                  {deviceError}
                </div>
              ) : null}
              {devices.length === 0 ? (
                <button
                  className="cc-add"
                  disabled={isMutating}
                  onClick={openCreateDrawer}
                  type="button"
                >
                  <span className="cc-add-plus">＋</span>
                  创建第一台 VPN 设备
                </button>
              ) : (
                <div>
                  {devices.map((device) => (
                    <div className="cc-lib" key={device.id}>
                      <div>
                        <div className="cc-lib-name">{device.name}</div>
                        <div className="cc-lib-desc">
                          {platformLabel(device.platform)} · {device.address} ·{" "}
                          {device.last_handshake_at
                            ? `最后连接 ${formatStatusTime(device.last_handshake_at)}`
                            : "尚未连接"}
                        </div>
                      </div>
                      <span
                        className={`status-pill ${device.enabled ? "active" : "disabled"}`}
                      >
                        <span aria-hidden="true" />
                        {device.enabled ? "已启用" : "已停用"}
                      </span>
                      <button
                        className="module-card-action"
                        disabled={isMutating}
                        onClick={() => void toggleDevice(device)}
                        type="button"
                      >
                        {device.enabled ? "停用" : "重新启用"}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </article>
          </div>
        </div>
      )}

      {drawerOpen ? (
        <>
          <button
            aria-label="关闭设备面板"
            className="cc-scrim"
            onClick={closeDrawer}
            type="button"
          />
          <aside aria-label="添加 VPN 设备" className="cc-drawer">
            <div className="cc-drawer-head">
              <div>
                <h3>{oneTimeDevice ? "设备创建成功" : "添加 VPN 设备"}</h3>
                <span>
                  {oneTimeDevice ? "配置只显示这一次" : "只会加入新 VPN awg0"}
                </span>
              </div>
              <button
                aria-label="关闭"
                className="cc-drawer-close"
                onClick={closeDrawer}
                type="button"
              >
                ×
              </button>
            </div>
            <div className="cc-drawer-body">
              {oneTimeDevice ? (
                <div className="module-card">
                  <div className="module-card-header">
                    <div>
                      <span className="status-pill active">
                        <span aria-hidden="true" />
                        已启用
                      </span>
                      <h3>{oneTimeDevice.device.name}</h3>
                    </div>
                    <span className="subtle-badge">
                      {oneTimeDevice.device.address}
                    </span>
                  </div>
                  <p>
                    请立即复制或下载配置。出于安全原因，关闭此面板后私钥无法再次查看。
                  </p>
                  <span className="textarea-shell">
                    <textarea
                      aria-label="一次性 VPN 配置"
                      readOnly
                      value={oneTimeDevice.configuration}
                    />
                  </span>
                  <button
                    className="module-card-action"
                    onClick={() => void copyConfiguration()}
                    type="button"
                  >
                    复制配置
                  </button>
                  <button
                    className="module-card-action"
                    onClick={downloadConfiguration}
                    type="button"
                  >
                    下载配置
                  </button>
                  <div aria-live="polite" className="form-message">
                    {copyMessage}
                  </div>
                </div>
              ) : (
                <form className="module-card" onSubmit={submitDevice}>
                  <label className="field-group">
                    <span>设备名称</span>
                    <span className="input-shell">
                      <input
                        autoComplete="off"
                        maxLength={64}
                        onChange={(event) => setDeviceName(event.target.value)}
                        placeholder="例如：张三的办公电脑"
                        required
                        value={deviceName}
                      />
                    </span>
                  </label>
                  <label className="field-group">
                    <span>设备类型</span>
                    <select
                      className="select-shell"
                      onChange={(event) =>
                        setPlatform(event.target.value as VpnDevicePlatform)
                      }
                      value={platform}
                    >
                      <option value="windows">Windows 电脑</option>
                      <option value="macos">苹果电脑</option>
                      <option value="ios">苹果手机</option>
                      <option value="android">安卓手机</option>
                      <option value="other">其他设备</option>
                    </select>
                  </label>
                  <div aria-live="polite" className="form-message">
                    {deviceError}
                  </div>
                  <button
                    className="module-card-action"
                    disabled={isMutating}
                    type="submit"
                  >
                    {isMutating ? "正在创建…" : "创建设备"}
                  </button>
                </form>
              )}
            </div>
          </aside>
        </>
      ) : null}
    </div>
  );
}
