"use client";

import { apiRequest } from "@/lib/api";

import {
  normalizeNativeVpnEnrollment,
  normalizeVpnDevice,
  normalizeVpnDeviceList,
  type NativeVpnEnrollment,
  type VpnDevice,
  type VpnDeviceList,
} from "./devices";
import type { NativeVpnIdentity } from "./native";
import { normalizeVpnNodeList, type VpnNode } from "./nodes";

// Installers are served by nginx under /api/backend so the session cookie
// (path=/api/backend) travels with a plain same-origin navigation.
export const VPN_DOWNLOADS = {
  android: "/api/backend/vpn/downloads/android",
  windows: "/api/backend/vpn/downloads/windows",
} as const;

export async function getVpnNodes(signal?: AbortSignal): Promise<VpnNode[]> {
  const payload = await apiRequest<unknown>("/vpn/nodes", {
    bypassCache: true,
    method: "GET",
    retryLimit: 0,
    signal,
    timeoutMs: 9_000,
  });
  const nodes = normalizeVpnNodeList(payload);
  if (!nodes) {
    throw new Error("VPN 节点数据格式异常。");
  }
  return nodes;
}

export async function getVpnDevices(
  signal?: AbortSignal,
): Promise<VpnDeviceList> {
  const payload = await apiRequest<unknown>("/vpn/devices", {
    bypassCache: true,
    method: "GET",
    retryLimit: 0,
    signal,
    timeoutMs: 9_000,
  });
  const list = normalizeVpnDeviceList(payload);
  if (!list) {
    throw new Error("VPN 设备数据格式异常。");
  }
  return list;
}

/**
 * The only way a device comes into existence: the signed-in client enrolls
 * itself with its own public key on the node it picked.
 */
export async function enrollNativeVpnDevice(
  identity: NativeVpnIdentity,
  nodeId: string,
): Promise<NativeVpnEnrollment> {
  const payload = await apiRequest<unknown>("/vpn/devices/enroll", {
    body: {
      agent_version: identity.agent_version,
      architecture: identity.architecture,
      device_id: identity.device_id,
      name: identity.suggested_name,
      node_id: nodeId,
      platform: identity.platform,
      public_key: identity.public_key,
    },
    method: "POST",
    retryLimit: 0,
    timeoutMs: 12_000,
  });
  const enrollment = normalizeNativeVpnEnrollment(payload);
  if (!enrollment) {
    throw new Error("本机 VPN 登记结果格式异常。");
  }
  return enrollment;
}

export async function setVpnDeviceEnabled(
  deviceId: string,
  enabled: boolean,
): Promise<VpnDevice> {
  const payload = await apiRequest<unknown>(
    `/vpn/devices/${encodeURIComponent(deviceId)}`,
    {
      body: { enabled },
      method: "PATCH",
      retryLimit: 0,
      timeoutMs: 10_000,
    },
  );
  const device =
    typeof payload === "object" && payload !== null && "device" in payload
      ? normalizeVpnDevice((payload as { device: unknown }).device)
      : null;
  if (!device) {
    throw new Error("VPN 设备状态结果格式异常。");
  }
  return device;
}
