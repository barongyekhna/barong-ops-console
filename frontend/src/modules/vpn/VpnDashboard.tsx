"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DashboardScene } from "@/components/dashboard-scene";
import { DashboardSkeleton } from "@/components/dashboard-ui";
import { ApiRequestAbortedError, isApiAbortError } from "@/lib/api";

import {
  enrollNativeVpnDevice,
  getVpnDevices,
  getVpnNodes,
  setVpnDeviceEnabled,
  VPN_DOWNLOADS,
} from "./api";
import {
  ConnectionBar,
  type ConnectionPhase,
  type ConnectionRates,
} from "./ConnectionBar";
import { DeviceList } from "./DeviceList";
import type { VpnDevice } from "./devices";
import {
  getNativeVpnBridge,
  normalizeNativeVpnIdentity,
  normalizeNativeVpnStatus,
  type NativeVpnStatus,
} from "./native";
import { NodePanel } from "./NodePanel";
import { isNodeOnline, type VpnNode } from "./nodes";

// Live view: poll every 5s while the tab is visible so rates and the lamp
// track reality; hidden tabs stop polling entirely.
const POLL_INTERVAL_MS = 5_000;
// After asking the native agent to connect, watch its status for up to 20s
// before calling the attempt failed. The tunnel service needs a few seconds.
const CONNECT_SETTLE_ATTEMPTS = 20;
const CONNECT_SETTLE_INTERVAL_MS = 1_000;

type Sample = { at: number; received: number; sent: number };

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function sleep(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms));
}

function sumBytes(devices: VpnDevice[], key: "received_bytes" | "sent_bytes"): number | null {
  const values = devices.map((device) => device[key]).filter((v): v is number => v !== null);
  return values.length === 0 ? null : values.reduce((a, b) => a + b, 0);
}

export function VpnDashboard() {
  const [nodes, setNodes] = useState<VpnNode[]>([]);
  const [devices, setDevices] = useState<VpnDevice[]>([]);
  const [unavailableNodes, setUnavailableNodes] = useState<string[]>([]);
  const [nodeError, setNodeError] = useState("");
  const [deviceError, setDeviceError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isMutating, setIsMutating] = useState(false);
  const [nativeStatus, setNativeStatus] = useState<NativeVpnStatus | null>(null);
  const [nativeError, setNativeError] = useState("");
  const [nativeBusy, setNativeBusy] = useState<"connect" | "disconnect" | "switch" | null>(null);
  const [switchingNodeId, setSwitchingNodeId] = useState<string | null>(null);
  const [rates, setRates] = useState<ConnectionRates>({
    down_bytes_per_second: null,
    up_bytes_per_second: null,
  });
  const requestGenerationRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const lastSampleRef = useRef<Sample | null>(null);
  const nativeStatusRef = useRef<NativeVpnStatus | null>(null);
  nativeStatusRef.current = nativeStatus;

  const bridge = typeof window === "undefined" ? null : getNativeVpnBridge();
  const nativeAvailable = bridge !== null;

  const updateRates = useCallback((list: VpnDevice[], localDeviceId: string | null) => {
    const scope = localDeviceId
      ? list.filter((device) => device.id === localDeviceId)
      : list;
    const received = sumBytes(scope, "received_bytes");
    const sent = sumBytes(scope, "sent_bytes");
    const now = Date.now();
    const previous = lastSampleRef.current;
    if (received !== null && sent !== null) {
      if (previous && now > previous.at) {
        const seconds = (now - previous.at) / 1000;
        setRates({
          down_bytes_per_second: Math.max(0, (received - previous.received) / seconds),
          up_bytes_per_second: Math.max(0, (sent - previous.sent) / seconds),
        });
      }
      lastSampleRef.current = { at: now, received, sent };
    }
  }, []);

  const loadNative = useCallback(async (): Promise<NativeVpnStatus | null> => {
    const currentBridge = getNativeVpnBridge();
    if (!currentBridge) {
      setNativeStatus(null);
      return null;
    }
    try {
      const nextStatus = normalizeNativeVpnStatus(await currentBridge.status());
      if (!nextStatus) {
        throw new Error("本机 VPN 状态格式异常。");
      }
      setNativeStatus(nextStatus);
      return nextStatus;
    } catch (error) {
      setNativeError(errorMessage(error, "本机 VPN 状态暂时无法读取。"));
      return null;
    }
  }, []);

  const load = useCallback(
    async ({ silent = false }: { silent?: boolean } = {}) => {
      const previousController = abortControllerRef.current;
      if (previousController && !previousController.signal.aborted) {
        previousController.abort(new ApiRequestAbortedError("VPN request superseded."));
      }
      const controller = new AbortController();
      const generation = requestGenerationRef.current + 1;
      requestGenerationRef.current = generation;
      abortControllerRef.current = controller;
      if (!silent) {
        setIsLoading(true);
      }

      const [nodesResult, devicesResult] = await Promise.allSettled([
        getVpnNodes(controller.signal),
        getVpnDevices(controller.signal),
      ]);
      if (controller.signal.aborted || requestGenerationRef.current !== generation) {
        return;
      }

      if (nodesResult.status === "fulfilled") {
        setNodes(nodesResult.value);
        setNodeError("");
      } else if (!isApiAbortError(nodesResult.reason)) {
        setNodeError(errorMessage(nodesResult.reason, "节点状态暂时无法读取。"));
      }
      if (devicesResult.status === "fulfilled") {
        setDevices(devicesResult.value.devices);
        setUnavailableNodes(devicesResult.value.unavailable_nodes);
        setDeviceError("");
        updateRates(devicesResult.value.devices, nativeStatusRef.current?.device_id ?? null);
      } else if (!isApiAbortError(devicesResult.reason)) {
        setDeviceError(errorMessage(devicesResult.reason, "我的设备暂时无法读取。"));
      }
      abortControllerRef.current = null;
      setIsLoading(false);
    },
    [updateRates],
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

  // Wait for the native tunnel to actually come up (or down) instead of
  // judging the first status read after the command, which is what used to
  // flash "异常" for a moment right after a successful connect.
  const settleNative = useCallback(
    async (wantConnected: boolean): Promise<NativeVpnStatus | null> => {
      for (let attempt = 0; attempt < CONNECT_SETTLE_ATTEMPTS; attempt += 1) {
        const status = await loadNative();
        if (status && status.connected === wantConnected) {
          return status;
        }
        await sleep(CONNECT_SETTLE_INTERVAL_MS);
      }
      return null;
    },
    [loadNative],
  );

  const localDevice = nativeStatus?.device_id
    ? devices.find((device) => device.id === nativeStatus.device_id) ?? null
    : null;
  const currentNodeId = nativeStatus?.node_id ?? localDevice?.node_id ?? null;
  const currentNode = nodes.find((node) => node.id === currentNodeId) ?? null;
  const defaultNode = nodes.find((node) => node.enabled && isNodeOnline(node)) ?? nodes.find((node) => node.enabled) ?? null;

  const enrollAndConnect = useCallback(
    async (node: VpnNode) => {
      const currentBridge = getNativeVpnBridge();
      if (!currentBridge) {
        throw new Error("请在控制台 App 中使用一键连接。");
      }
      let status = nativeStatusRef.current;
      if (!status?.installed) {
        const installed = normalizeNativeVpnStatus(await currentBridge.install());
        if (!installed?.installed) {
          throw new Error("VPN 组件尚未完成安装，请允许系统权限后重试。");
        }
        status = installed;
        setNativeStatus(installed);
      }
      const identity = normalizeNativeVpnIdentity(await currentBridge.enrollment());
      if (!identity) {
        throw new Error("本机设备身份格式异常。");
      }
      const enrollment = await enrollNativeVpnDevice(identity, node.id);
      await currentBridge.provision(enrollment.provisioning);
      setDevices((before) => [
        ...before.filter((device) => device.id !== enrollment.device.id),
        enrollment.device,
      ]);
      await currentBridge.connect();
      const settled = await settleNative(true);
      if (!settled) {
        throw new Error("连接超时，请稍后再试一次。");
      }
    },
    [settleNative],
  );

  const controlNativeVpn = async () => {
    const currentBridge = getNativeVpnBridge();
    if (!currentBridge) {
      setNativeError("请在控制台 App 中使用一键连接。");
      return;
    }
    const status = nativeStatusRef.current;
    const wantsDisconnect = Boolean(status?.provisioned && (status.connected || status.desired_connected));
    setNativeBusy(wantsDisconnect ? "disconnect" : "connect");
    setNativeError("");
    try {
      if (wantsDisconnect) {
        await currentBridge.disconnect();
        await settleNative(false);
      } else if (status?.provisioned && status.node_id) {
        await currentBridge.connect();
        const settled = await settleNative(true);
        if (!settled) {
          throw new Error("连接超时，请稍后再试一次。");
        }
      } else {
        const target = currentNode ?? defaultNode;
        if (!target) {
          throw new Error("当前没有可用节点。");
        }
        await enrollAndConnect(target);
      }
      await load({ silent: true });
    } catch (error) {
      setNativeError(errorMessage(error, "本机 VPN 操作失败，请稍后重试。"));
      await loadNative();
    } finally {
      setNativeBusy(null);
    }
  };

  const switchNode = async (node: VpnNode) => {
    if (!nativeAvailable || node.id === currentNodeId) {
      return;
    }
    setNativeBusy("switch");
    setSwitchingNodeId(node.id);
    setNativeError("");
    try {
      const currentBridge = getNativeVpnBridge();
      if (currentBridge && nativeStatusRef.current?.connected) {
        await currentBridge.disconnect();
        await settleNative(false);
      }
      await enrollAndConnect(node);
      await load({ silent: true });
    } catch (error) {
      setNativeError(errorMessage(error, "切换节点失败，请稍后重试。"));
      await loadNative();
    } finally {
      setNativeBusy(null);
      setSwitchingNodeId(null);
    }
  };

  const toggleDevice = async (device: VpnDevice) => {
    setIsMutating(true);
    setDeviceError("");
    try {
      const updated = await setVpnDeviceEnabled(device.id, !device.enabled);
      setDevices((current) =>
        current.map((item) => (item.id === updated.id ? { ...item, ...updated, node_id: updated.node_id ?? item.node_id } : item)),
      );
      void load({ silent: true });
    } catch (error) {
      setDeviceError(errorMessage(error, "设备状态更新失败，请稍后重试。"));
    } finally {
      setIsMutating(false);
    }
  };

  // ---- derived view state -------------------------------------------------
  let phase: ConnectionPhase;
  if (!nativeAvailable) {
    phase = "browser";
  } else if (nativeBusy === "disconnect") {
    phase = "disconnecting";
  } else if (nativeBusy !== null) {
    phase = "connecting";
  } else if (nativeError) {
    phase = "error";
  } else if (nativeStatus?.connected) {
    phase = "connected";
  } else if (nativeStatus?.desired_connected) {
    phase = "connecting";
  } else {
    phase = "disconnected";
  }

  const nodeName = phase === "browser"
    ? defaultNode?.name ?? null
    : nativeStatus?.node_name ?? currentNode?.name ?? defaultNode?.name ?? null;
  const actionLabel = !nativeStatus?.installed
    ? "安装并连接"
    : !nativeStatus.provisioned
      ? "登记本机并连接"
      : nativeStatus.connected || nativeStatus.desired_connected
        ? "断开 VPN"
        : "连接 VPN";
  const detail = phase === "browser"
    ? "普通浏览器没有本机系统权限。安装控制台 App 后在 App 里打开本页，一键登记本机并连接。"
    : nativeError
      ? nativeError
      : phase === "connected"
        ? `本机经 ${currentNode?.name ?? "专线"} 出口上网；关闭控制台不会断开。`
        : phase === "connecting"
          ? "正在建立安全隧道…"
          : phase === "disconnecting"
            ? "正在断开…"
            : nativeStatus?.provisioned
              ? "本机已登记，随时可以连接。"
              : "第一次会申请一次系统权限，并自动登记本机。";
  const deviceCounts = devices.reduce<Record<string, number>>((acc, device) => {
    if (device.node_id) {
      acc[device.node_id] = (acc[device.node_id] ?? 0) + 1;
    }
    return acc;
  }, {});
  const scopeDevices = localDevice ? [localDevice] : devices;
  const headerStatus = isLoading && nodes.length === 0
    ? "连接中"
    : nodeError
      ? "读取异常"
      : `${nodes.filter(isNodeOnline).length} 个节点在线`;

  return (
    <div className="dashboard-page cc-dash cc-vpn">
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

      <ConnectionBar
        actionDisabled={!nativeAvailable || (phase !== "connected" && !defaultNode && !currentNode)}
        actionLabel={actionLabel}
        address={nativeStatus?.address ?? localDevice?.address ?? null}
        busy={nativeBusy !== null}
        detail={detail}
        nodeName={nodeName}
        onAction={() => void controlNativeVpn()}
        onDownloadAndroid={() => window.location.assign(VPN_DOWNLOADS.android)}
        onDownloadWindows={() => window.location.assign(VPN_DOWNLOADS.windows)}
        phase={phase}
        rates={rates}
        totalReceived={sumBytes(scopeDevices, "received_bytes")}
        totalSent={sumBytes(scopeDevices, "sent_bytes")}
      />

      {isLoading && nodes.length === 0 && !nodeError ? (
        <DashboardSkeleton />
      ) : (
        <div className="cc-grid cc-vpn-grid">
          <div className="cc-card wide">
            <NodePanel
              currentNodeId={currentNodeId}
              deviceCounts={deviceCounts}
              error={nodeError}
              nodes={nodes}
              onSelect={(node) => void switchNode(node)}
              selectable={nativeAvailable && Boolean(nativeStatus?.installed)}
              switchingNodeId={switchingNodeId}
            />
          </div>
          <div className="cc-card wide">
            <DeviceList
              busy={isMutating}
              currentDeviceId={nativeStatus?.device_id ?? null}
              devices={devices}
              error={deviceError}
              nodes={nodes}
              onToggle={(device) => void toggleDevice(device)}
              unavailableNodes={unavailableNodes}
            />
          </div>
        </div>
      )}
    </div>
  );
}
