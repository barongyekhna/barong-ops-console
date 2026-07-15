"use client";

import { apiRequest } from "@/lib/api";

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
