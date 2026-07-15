"use client";

import { apiRequest } from "@/lib/api";

import {
  normalizeCreatedVpnDevice,
  normalizeVpnDevice,
  normalizeVpnDeviceList,
  type CreatedVpnDevice,
  type VpnDevice,
  type VpnDevicePlatform,
} from "./devices";
import { normalizeVpnStatus, type VpnStatus } from "./status";

export async function getVpnStatus(signal?: AbortSignal): Promise<VpnStatus> {
  const payload = await apiRequest<unknown>("/vpn/status", {
    bypassCache: true,
    method: "GET",
    retryLimit: 0,
    signal,
    timeoutMs: 7_000,
  });
  const status = normalizeVpnStatus(payload);
  if (!status) {
    throw new Error("VPN 状态数据格式异常。");
  }
  return status;
}

export async function getVpnDevices(
  signal?: AbortSignal,
): Promise<VpnDevice[]> {
  const payload = await apiRequest<unknown>("/vpn/devices", {
    bypassCache: true,
    method: "GET",
    retryLimit: 0,
    signal,
    timeoutMs: 8_000,
  });
  const devices = normalizeVpnDeviceList(payload);
  if (!devices) {
    throw new Error("VPN 设备数据格式异常。");
  }
  return devices;
}

export async function createVpnDevice(input: {
  name: string;
  platform: VpnDevicePlatform;
}): Promise<CreatedVpnDevice> {
  const payload = await apiRequest<unknown>("/vpn/devices", {
    body: input,
    method: "POST",
    retryLimit: 0,
    timeoutMs: 10_000,
  });
  const created = normalizeCreatedVpnDevice(payload);
  if (!created) {
    throw new Error("VPN 设备创建结果格式异常。");
  }
  return created;
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
