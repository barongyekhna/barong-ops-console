"use client";

import { apiRequest } from "@/lib/api";

import {
  normalizeRdDevice,
  normalizeRdDeviceDetail,
  normalizeRdDeviceList,
  normalizeRdIceConfig,
  normalizeRdSession,
  normalizeRdSessionList,
  type RdDevice,
  type RdDeviceDetail,
  type RdIceConfig,
  type RdSession,
} from "./types";

/** SSE 走同源代理:EventSource 不能带自定义头,只能靠同源 cookie。 */
export const RD_STREAM_PATH = "/api/backend/rd/stream";

export async function registerRdDevice(payload: {
  agent_version: string;
  device_uuid: string;
  name: string;
  platform: string;
}): Promise<RdDevice> {
  const result = await apiRequest<unknown>("/rd/devices/register", {
    body: payload,
    method: "POST",
    retryLimit: 0,
    timeoutMs: 12_000,
  });
  const device = normalizeRdDevice(result);
  if (!device) {
    throw new Error("设备数据格式异常。");
  }
  return device;
}

export async function heartbeatRdDevice(
  deviceId: string,
  agentVersion: string,
): Promise<void> {
  await apiRequest<unknown>(`/rd/devices/${deviceId}/heartbeat`, {
    body: { agent_version: agentVersion },
    method: "POST",
    retryLimit: 0,
    timeoutMs: 9_000,
  });
}

export async function getRdSession(sessionId: string): Promise<RdSession> {
  const payload = await apiRequest<unknown>(`/rd/sessions/${sessionId}`, {
    bypassCache: true,
    method: "GET",
    retryLimit: 0,
    timeoutMs: 9_000,
  });
  const session = normalizeRdSession(payload);
  if (!session) {
    throw new Error("会话数据格式异常。");
  }
  return session;
}

export async function listRdDevices(signal?: AbortSignal): Promise<RdDevice[]> {
  const payload = await apiRequest<unknown>("/rd/devices", {
    bypassCache: true,
    method: "GET",
    retryLimit: 0,
    signal,
    timeoutMs: 9_000,
  });
  return normalizeRdDeviceList(payload);
}

export async function getRdDevice(
  deviceId: string,
  signal?: AbortSignal,
): Promise<RdDeviceDetail> {
  const payload = await apiRequest<unknown>(`/rd/devices/${deviceId}`, {
    bypassCache: true,
    method: "GET",
    retryLimit: 0,
    signal,
    timeoutMs: 9_000,
  });
  const device = normalizeRdDeviceDetail(payload);
  if (!device) {
    throw new Error("设备数据格式异常。");
  }
  return device;
}

export async function listRdSessions(
  signal?: AbortSignal,
): Promise<RdSession[]> {
  const payload = await apiRequest<unknown>("/rd/sessions?limit=100", {
    bypassCache: true,
    method: "GET",
    retryLimit: 0,
    signal,
    timeoutMs: 9_000,
  });
  return normalizeRdSessionList(payload);
}

export async function requestRdSession(deviceId: string): Promise<RdSession> {
  const payload = await apiRequest<unknown>("/rd/sessions", {
    body: { device_id: deviceId },
    method: "POST",
    retryLimit: 0,
    timeoutMs: 12_000,
  });
  const session = normalizeRdSession(payload);
  if (!session) {
    throw new Error("会话数据格式异常。");
  }
  return session;
}

export async function respondRdSession(
  sessionId: string,
  approve: boolean,
): Promise<RdSession> {
  const payload = await apiRequest<unknown>(
    `/rd/sessions/${sessionId}/respond`,
    { body: { approve }, method: "POST", retryLimit: 0, timeoutMs: 12_000 },
  );
  const session = normalizeRdSession(payload);
  if (!session) {
    throw new Error("会话数据格式异常。");
  }
  return session;
}

export async function activateRdSession(sessionId: string): Promise<RdSession> {
  const payload = await apiRequest<unknown>(
    `/rd/sessions/${sessionId}/activate`,
    { method: "POST", retryLimit: 0, timeoutMs: 12_000 },
  );
  const session = normalizeRdSession(payload);
  if (!session) {
    throw new Error("会话数据格式异常。");
  }
  return session;
}

export async function endRdSession(
  sessionId: string,
  reason: "controller_left" | "agent_kicked" | "connection_lost",
): Promise<void> {
  await apiRequest<unknown>(`/rd/sessions/${sessionId}/end`, {
    body: { reason },
    method: "POST",
    retryLimit: 0,
    timeoutMs: 12_000,
  });
}

export async function getRdIceConfig(sessionId: string): Promise<RdIceConfig> {
  const payload = await apiRequest<unknown>(`/rd/sessions/${sessionId}/ice`, {
    bypassCache: true,
    method: "GET",
    retryLimit: 0,
    timeoutMs: 9_000,
  });
  return normalizeRdIceConfig(payload);
}

export async function pushRdSignal(
  sessionId: string,
  kind: "offer" | "answer" | "ice",
  payload: string,
): Promise<void> {
  await apiRequest<unknown>(`/rd/sessions/${sessionId}/signals`, {
    body: { kind, payload },
    method: "POST",
    retryLimit: 0,
    timeoutMs: 12_000,
  });
}

export async function setRdUnattended(
  deviceId: string,
  enabled: boolean,
  confirmedOnDevice: boolean,
): Promise<RdDevice> {
  const payload = await apiRequest<unknown>(
    `/rd/devices/${deviceId}/unattended`,
    {
      body: { confirmed_on_device: confirmedOnDevice, enabled },
      method: "POST",
      retryLimit: 0,
      timeoutMs: 12_000,
    },
  );
  const device = normalizeRdDevice(payload);
  if (!device) {
    throw new Error("设备数据格式异常。");
  }
  return device;
}

export async function addRdGrant(
  deviceId: string,
  granteeUserId: number,
): Promise<RdDeviceDetail> {
  const payload = await apiRequest<unknown>(`/rd/devices/${deviceId}/grants`, {
    body: { grantee_user_id: granteeUserId },
    method: "POST",
    retryLimit: 0,
    timeoutMs: 12_000,
  });
  const device = normalizeRdDeviceDetail(payload);
  if (!device) {
    throw new Error("设备数据格式异常。");
  }
  return device;
}

export async function removeRdGrant(
  deviceId: string,
  granteeUserId: number,
): Promise<RdDeviceDetail> {
  const payload = await apiRequest<unknown>(
    `/rd/devices/${deviceId}/grants/${granteeUserId}`,
    { method: "DELETE", retryLimit: 0, timeoutMs: 12_000 },
  );
  const device = normalizeRdDeviceDetail(payload);
  if (!device) {
    throw new Error("设备数据格式异常。");
  }
  return device;
}
