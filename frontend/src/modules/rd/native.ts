"use client";

/** RD 系列 · 原生桥检测。
 *
 * 被控端必须是控制台 Windows 客户端:抓屏和注入键鼠要本机权限,普通浏览器没有,
 * 这不是能绕过去的限制,是操作系统的边界。
 *
 * 检测方式照 VPN 模块的路子:六个方法一个不少才认,少一个就当没有——半截桥比没有
 * 桥更危险,会走到一半才失败。
 */

export type RdNativeBridge = {
  beginUnattended: (payload: { sessionId: string }) => Promise<{ approved: boolean }>;
  consent: (payload: {
    sessionId: string;
    requesterName: string;
  }) => Promise<{ approved: boolean; reason?: string }>;
  input: (event: unknown) => Promise<{ ok: boolean }>;
  markUnattended: (payload: {
    deviceId: string;
    enabled: boolean;
  }) => Promise<{ confirmed: boolean }>;
  status: () => Promise<{
    active: boolean;
    available: boolean;
    /** 这台机器的身份，由客户端自持，和 VPN 的设备 UUID 无关。 */
    device_name: string;
    device_uuid: string;
    peer_name: string | null;
    platform: string;
    reason: string | null;
    session_id: string | null;
  }>;
  stop: () => Promise<{ active: boolean }>;
};

const REQUIRED_METHODS = [
  "beginUnattended",
  "consent",
  "input",
  "markUnattended",
  "status",
  "stop",
] as const;

export function getRdNativeBridge(): RdNativeBridge | null {
  if (typeof window === "undefined") {
    return null;
  }
  const candidate = (window as unknown as { barongRemote?: unknown }).barongRemote;
  if (typeof candidate !== "object" || candidate === null) {
    return null;
  }
  const bridge = candidate as Record<string, unknown>;
  for (const method of REQUIRED_METHODS) {
    if (typeof bridge[method] !== "function") {
      return null;
    }
  }
  return candidate as RdNativeBridge;
}

export function nativeUnavailableMessage(): string {
  return "这台机器上没有装控制台客户端，所以它不能被远程操控——但你在这里照样可以去控制别人的机器。";
}
