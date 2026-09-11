"use client";

/** RD 系列 · 远程桌面的数据形状与规范化。
 *
 * 后端回什么都不能直接信:少一个字段就让整个面板白屏,是这类面板最常见的死法。
 * 所有进入 UI 的对象都先过这里的 normalize,形状不对就整条丢掉,而不是留一个
 * 半截对象往下传。
 */

export type RdSessionState =
  | "requested"
  | "consented"
  | "active"
  | "denied"
  | "expired"
  | "ended";

export type RdConsentMode = "prompt" | "unattended";

export type RdDevice = {
  id: string;
  name: string;
  platform: string;
  agent_version: string;
  owner_user_id: number;
  owner_name: string | null;
  is_online: boolean;
  is_mine: boolean;
  is_unattended: boolean;
  /** 这个人连这台机器要不要弹框。按钮文案据此在「请求控制」和「直接连接」之间切。 */
  needs_consent: boolean;
  busy: boolean;
  last_seen_at: string | null;
};

export type RdGrant = {
  grantee_user_id: number;
  grantee_name: string | null;
  created_at: string;
};

export type RdDeviceDetail = RdDevice & { grants: RdGrant[] };

export type RdSession = {
  id: string;
  device_id: string;
  device_name: string | null;
  controller_user_id: number;
  controller_name: string | null;
  state: RdSessionState;
  consent_mode: RdConsentMode;
  requested_at: string;
  responded_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  end_reason: string | null;
};

export type RdIceConfig = {
  stun_urls: string[];
  turn_urls: string[];
  turn_username: string | null;
  turn_credential: string | null;
  ttl: number;
};

const SESSION_STATES: ReadonlySet<string> = new Set([
  "requested",
  "consented",
  "active",
  "denied",
  "expired",
  "ended",
]);

const CONSENT_MODES: ReadonlySet<string> = new Set(["prompt", "unattended"]);

/** 还占着被控机、界面上要显示成「进行中」的状态。 */
export const LIVE_SESSION_STATES: ReadonlySet<RdSessionState> = new Set([
  "requested",
  "consented",
  "active",
]);

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function nullableText(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function bool(value: unknown): boolean {
  return value === true;
}

export function normalizeRdDevice(value: unknown): RdDevice | null {
  const raw = record(value);
  if (!raw) {
    return null;
  }
  const id = text(raw.id);
  const name = text(raw.name);
  const platform = text(raw.platform);
  const agentVersion = text(raw.agent_version);
  const ownerId = raw.owner_user_id;
  if (
    id === null ||
    name === null ||
    platform === null ||
    agentVersion === null ||
    typeof ownerId !== "number"
  ) {
    return null;
  }
  return {
    agent_version: agentVersion,
    busy: bool(raw.busy),
    id,
    is_mine: bool(raw.is_mine),
    is_online: bool(raw.is_online),
    is_unattended: bool(raw.is_unattended),
    last_seen_at: nullableText(raw.last_seen_at),
    name,
    // 缺这个字段时按「要弹框」处理:拿不准就走更严的那条路,绝不默认放行。
    needs_consent: raw.needs_consent !== false,
    owner_name: nullableText(raw.owner_name),
    owner_user_id: ownerId,
    platform,
  };
}

export function normalizeRdDeviceList(value: unknown): RdDevice[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const devices: RdDevice[] = [];
  for (const item of value) {
    const device = normalizeRdDevice(item);
    if (device) {
      devices.push(device);
    }
  }
  return devices;
}

export function normalizeRdGrant(value: unknown): RdGrant | null {
  const raw = record(value);
  if (!raw || typeof raw.grantee_user_id !== "number") {
    return null;
  }
  return {
    created_at: text(raw.created_at) ?? "",
    grantee_name: nullableText(raw.grantee_name),
    grantee_user_id: raw.grantee_user_id,
  };
}

export function normalizeRdDeviceDetail(value: unknown): RdDeviceDetail | null {
  const device = normalizeRdDevice(value);
  if (!device) {
    return null;
  }
  const raw = record(value);
  const rawGrants = raw && Array.isArray(raw.grants) ? raw.grants : [];
  const grants: RdGrant[] = [];
  for (const item of rawGrants) {
    const grant = normalizeRdGrant(item);
    if (grant) {
      grants.push(grant);
    }
  }
  return { ...device, grants };
}

export function normalizeRdSession(value: unknown): RdSession | null {
  const raw = record(value);
  if (!raw) {
    return null;
  }
  const id = text(raw.id);
  const deviceId = text(raw.device_id);
  const state = text(raw.state);
  const consentMode = text(raw.consent_mode);
  const controllerId = raw.controller_user_id;
  if (
    id === null ||
    deviceId === null ||
    state === null ||
    consentMode === null ||
    !SESSION_STATES.has(state) ||
    !CONSENT_MODES.has(consentMode) ||
    typeof controllerId !== "number"
  ) {
    return null;
  }
  return {
    consent_mode: consentMode as RdConsentMode,
    controller_name: nullableText(raw.controller_name),
    controller_user_id: controllerId,
    device_id: deviceId,
    device_name: nullableText(raw.device_name),
    end_reason: nullableText(raw.end_reason),
    ended_at: nullableText(raw.ended_at),
    id,
    requested_at: text(raw.requested_at) ?? "",
    responded_at: nullableText(raw.responded_at),
    started_at: nullableText(raw.started_at),
    state: state as RdSessionState,
  };
}

export function normalizeRdSessionList(value: unknown): RdSession[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const sessions: RdSession[] = [];
  for (const item of value) {
    const session = normalizeRdSession(item);
    if (session) {
      sessions.push(session);
    }
  }
  return sessions;
}

export function normalizeRdIceConfig(value: unknown): RdIceConfig {
  const raw = record(value);
  const stun =
    raw && Array.isArray(raw.stun_urls)
      ? raw.stun_urls.filter((item): item is string => typeof item === "string")
      : [];
  const turn =
    raw && Array.isArray(raw.turn_urls)
      ? raw.turn_urls.filter((item): item is string => typeof item === "string")
      : [];
  return {
    stun_urls: stun,
    ttl: raw && typeof raw.ttl === "number" ? raw.ttl : 0,
    turn_credential: raw ? nullableText(raw.turn_credential) : null,
    turn_urls: turn,
    turn_username: raw ? nullableText(raw.turn_username) : null,
  };
}

/** 把后端给的通路配置翻成 RTCPeerConnection 认识的形状。 */
export function toIceServers(config: RdIceConfig): RTCIceServer[] {
  const servers: RTCIceServer[] = [];
  if (config.stun_urls.length > 0) {
    servers.push({ urls: config.stun_urls });
  }
  // TURN 三样缺一不可,凑不齐就只走直连——宁可连不上,也不发一把不完整的凭据出去
  if (
    config.turn_urls.length > 0 &&
    config.turn_username !== null &&
    config.turn_credential !== null
  ) {
    servers.push({
      credential: config.turn_credential,
      urls: config.turn_urls,
      username: config.turn_username,
    });
  }
  return servers;
}

const PLATFORM_LABELS: Record<string, string> = {
  darwin: "Mac",
  linux: "Linux",
  win32: "Windows",
};

export function platformLabel(platform: string): string {
  return PLATFORM_LABELS[platform] ?? platform;
}

export function deviceStatusLabel(device: RdDevice): string {
  if (!device.is_online) {
    return "离线";
  }
  if (device.busy) {
    return "正被远程";
  }
  return "在线";
}
