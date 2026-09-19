"use client";

import { apiRequest } from "@/lib/api";

import { rdTrace, rdTraceError, requestQueueSnapshot } from "./diagnostics";

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

/** 重开流时带上已经收到的最后一条信令 id,后端就不会把 offer/answer 重放一遍。 */
export function rdStreamUrl(afterSignalId: number): string {
  return afterSignalId > 0
    ? `${RD_STREAM_PATH}?after=${Math.floor(afterSignalId)}`
    : RD_STREAM_PATH;
}

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

/** 建连路上的关键请求不能「一次失败就放弃」。
 *
 * 2026-09-18 真机首测:对方点完同意两秒后,发起端再也没有请求到达服务器(同办公室
 * 别的机器照常),offer 那一条没送出去,整场连接就此作废,连「结束」都没报上去,被控
 * 机被一条死会话占住。
 * 网络抖一下是常态,所以这里按 0 / 1 / 2 / 4 秒退避最多试四次,总共不超过半分钟。
 * 每次都是全新的请求(apiRequest 的超时从排队那一刻起算,不能复用同一次)。
 */
const RELIABLE_BACKOFF_MS = [0, 1_000, 2_000, 4_000];

export type RdTraceContext = { sessionId: string; step: string };

export async function withRdRetry<T>(
  send: () => Promise<T>,
  shouldStop: () => boolean = () => false,
  trace?: RdTraceContext,
): Promise<T> {
  let lastError: unknown = null;
  let attempt = 0;
  for (const delay of RELIABLE_BACKOFF_MS) {
    if (delay > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, delay));
    }
    if (shouldStop()) {
      break;
    }
    attempt += 1;
    const startedAt = Date.now();
    try {
      const result = await send();
      if (trace) {
        rdTrace(
          `${trace.step}_ok`,
          { attempt, ms: Date.now() - startedAt },
          trace.sessionId,
        );
      }
      return result;
    } catch (error) {
      lastError = error;
      const status = (error as { status?: unknown } | null)?.status;
      if (trace) {
        rdTraceError(
          `${trace.step}_fail`,
          error,
          {
            attempt,
            ms: Date.now() - startedAt,
            online: navigator.onLine,
            status: typeof status === "number" ? status : null,
            ...requestQueueSnapshot(),
          },
          trace.sessionId,
        );
      }
      // 4xx 是后端明确说不行(会话已经结束之类),再试也一样
      if (
        typeof status === "number" &&
        status >= 400 &&
        status < 500 &&
        status !== 408 &&
        status !== 429
      ) {
        break;
      }
    }
  }
  throw lastError ?? new Error("请求没有送达。");
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
