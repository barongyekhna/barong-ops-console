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
  enrollNativeVpnDevice,
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
  getNativeVpnBridge,
  normalizeNativeVpnIdentity,
  normalizeNativeVpnStatus,
  type NativeVpnStatus,
} from "./native";
import {
  formatBytes,
  formatStatusTime,
  isVpnOnline,
  totalTransferBytes,
  type VpnStatus,
} from "./status";

const POLL_INTERVAL_MS = 15_000;
// Served by nginx under /api/backend so the session cookie travels with the
// navigation; a same-origin navigation (not fetch) keeps the browser's native
// download flow and cookie handling.
const WINDOWS_APP_DOWNLOAD_PATH = "/api/backend/vpn/downloads/windows";

function downloadWindowsApp() {
  window.location.assign(WINDOWS_APP_DOWNLOAD_PATH);
}

const STATUS_LABELS: Record<ModuleCardStatus, string> = {
  active: "可用",
  disabled: "待开放",
  error: "异常",
};

type StageCardProps = {
  actionLabel: string;
  badge: string;
  description: string;
  disabled?: boolean;
  name: string;
  onAction?: () => void;
  status: ModuleCardStatus;
};

function StageCard({
  actionLabel,
  badge,
  description,
  disabled = false,
  name,
  onAction,
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
      <button
        className="module-card-action"
        disabled={disabled || !onAction}
        onClick={onAction}
        type="button"
      >
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
  const [nativeStatus, setNativeStatus] = useState<NativeVpnStatus | null>(null);
  const [nativeError, setNativeError] = useState("");
  const [nativeBusy, setNativeBusy] = useState(false);
  const requestGenerationRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const loadNative = useCallback(async () => {
    const bridge = getNativeVpnBridge();
    if (!bridge) {
      setNativeStatus(null);
      setNativeError("");
      return;
    }
    try {
      const nextStatus = normalizeNativeVpnStatus(await bridge.status());
      if (!nextStatus) {
        throw new Error("本机 VPN 状态格式异常。");
      }
      setNativeStatus(nextStatus);
      setNativeError("");
    } catch (error) {
      setNativeError(errorMessage(error, "本机 VPN 状态暂时无法读取。"));
    }
  }, []);

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
    void loadNative();
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") {
        void load({ silent: true });
        void loadNative();
      }
    };
    const refreshWhenNativeReady = () => {
      void loadNative();
    };
    const intervalId = window.setInterval(refreshWhenVisible, POLL_INTERVAL_MS);
    window.addEventListener("focus", refreshWhenVisible);
    window.addEventListener("barong-vpn-ready", refreshWhenNativeReady);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", refreshWhenVisible);
      window.removeEventListener("barong-vpn-ready", refreshWhenNativeReady);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      requestGenerationRef.current += 1;
      const controller = abortControllerRef.current;
      if (controller && !controller.signal.aborted) {
        controller.abort(new ApiRequestAbortedError("VPN request canceled."));
      }
      abortControllerRef.current = null;
    };
  }, [load, loadNative]);

  const controlNativeVpn = async () => {
    const bridge = getNativeVpnBridge();
    if (!bridge) {
      setNativeError("请在控制台 App 中使用一键连接。");
      return;
    }
    setNativeBusy(true);
    setNativeError("");
    try {
      let current = nativeStatus;
      if (!current?.installed) {
        const installed = normalizeNativeVpnStatus(await bridge.install());
        if (!installed?.installed) {
          throw new Error("VPN 组件尚未完成安装，请允许管理员权限后重试。");
        }
        current = installed;
      }
      if (!current.provisioned) {
        const identity = normalizeNativeVpnIdentity(await bridge.enrollment());
        if (!identity) {
          throw new Error("本机设备身份格式异常。");
        }
        const enrollment = await enrollNativeVpnDevice(identity);
        await bridge.provision(enrollment.provisioning);
        setDevices((devicesBeforeEnrollment) => {
          const withoutCurrent = devicesBeforeEnrollment.filter(
            (device) => device.id !== enrollment.device.id,
          );
          return [...withoutCurrent, enrollment.device];
        });
        await bridge.connect();
      } else if (current.connected || current.desired_connected) {
        await bridge.disconnect();
      } else {
        await bridge.connect();
      }
      await Promise.all([load({ silent: true }), loadNative()]);
    } catch (error) {
      const message = errorMessage(error, "本机 VPN 操作失败，请稍后重试。");
      await loadNative();
      setNativeError(message);
    } finally {
      setNativeBusy(false);
    }
  };

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
  const nativeBridgeAvailable = getNativeVpnBridge() !== null;
  const nativePlatform = nativeStatus?.platform ?? "windows";
  const nativeBadge = nativeBridgeAvailable
    ? {
        android: "ANDROID APP",
        ios: "IPHONE APP",
        macos: "MAC APP",
        windows: "WINDOWS APP",
      }[nativePlatform]
    : "APP REQUIRED";
  const nativeActionLabel = !nativeBridgeAvailable
    ? "下载 Windows 控制台 App"
    : nativeBusy
      ? "正在处理…"
      : !nativeStatus?.installed
        ? "安装并启用"
        : !nativeStatus.provisioned
          ? "启用本机 VPN"
          : nativeStatus.connected || nativeStatus.desired_connected
            ? "断开 VPN"
            : "连接 VPN";
  const nativeDescription = !nativeBridgeAvailable
    ? "普通浏览器没有本机系统权限。先下载并安装 Windows 控制台 App，再在 App 里打开本页点一键连接。"
    : nativeError
      ? nativeError
      : nativeStatus?.connected
        ? `本机已通过 ${nativeStatus.address ?? "专属地址"} 连接；关闭控制台不会断开。`
        : nativeStatus?.desired_connected
          ? "本机正在建立安全连接；关闭控制台不会取消连接。"
        : nativeStatus?.provisioned
          ? "本机 VPN 已配置完成，可以直接连接。"
          : nativePlatform === "android"
            ? "第一次启用会申请一次 Android 系统 VPN 权限，并自动登记本机。"
            : "第一次启用会申请一次管理员权限，并自动安装和登记 VPN 组件。";

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
            onClick={() => void Promise.all([load(), loadNative()])}
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
              detail="已启用的隧道设备(停用/未连接的不计入)"
              label="在线隧道设备"
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
              actionLabel={nativeActionLabel}
              badge={nativeBadge}
              description={nativeDescription}
              disabled={nativeBusy}
              name="一键连接"
              onAction={
                nativeBridgeAvailable
                  ? () => void controlNativeVpn()
                  : downloadWindowsApp
              }
              status={nativeError ? "error" : "active"}
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
