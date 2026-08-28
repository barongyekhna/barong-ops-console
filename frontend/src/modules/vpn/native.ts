import type { NativeVpnProvisioning, VpnDevicePlatform } from "./devices";

export type NativeVpnPlatform = Exclude<VpnDevicePlatform, "other">;

export type NativeVpnStatus = {
  address: string | null;
  agent_version: string | null;
  available: boolean;
  connected: boolean;
  desired_connected: boolean;
  device_id: string | null;
  installed: boolean;
  node_id: string | null;
  node_name: string | null;
  platform: NativeVpnPlatform;
  provisioned: boolean;
  tunnel_service_state: string;
};

export type NativeVpnIdentity = {
  agent_version: string;
  architecture: string;
  device_id: string;
  platform: NativeVpnPlatform;
  public_key: string;
  schema_version: 1;
  suggested_name: string;
};

export type NativeVpnBridge = {
  connect: () => Promise<unknown>;
  disconnect: () => Promise<unknown>;
  enrollment: () => Promise<unknown>;
  install: () => Promise<unknown>;
  provision: (provisioning: NativeVpnProvisioning) => Promise<unknown>;
  status: () => Promise<unknown>;
};

const DEVICE_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ADDRESS_PATTERN =
  /^10\.66\.66\.(?:[2-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-4])\/32$/;
const NODE_ID_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/;
const KEY_PATTERN = /^[A-Za-z0-9+/]{43}=$/;
const AGENT_FIELD_PATTERN = /^[A-Za-z0-9._+-]{1,32}$/;
const NATIVE_PLATFORMS = new Set<NativeVpnPlatform>([
  "android",
  "ios",
  "macos",
  "windows",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeString(value: unknown, maxLength: number): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return normalized.length > 0 && normalized.length <= maxLength
    ? normalized
    : null;
}

function optionalString(value: unknown, maxLength: number): string | null {
  return value === undefined || value === null ? null : safeString(value, maxLength);
}

export function getNativeVpnBridge(): NativeVpnBridge | null {
  if (typeof window === "undefined") {
    return null;
  }
  const candidate = (window as Window & { barongVPN?: unknown }).barongVPN;
  if (!isRecord(candidate)) {
    return null;
  }
  for (const method of [
    "connect",
    "disconnect",
    "enrollment",
    "install",
    "provision",
    "status",
  ]) {
    if (typeof candidate[method] !== "function") {
      return null;
    }
  }
  return candidate as NativeVpnBridge;
}

export function normalizeNativeVpnStatus(payload: unknown): NativeVpnStatus | null {
  if (!isRecord(payload)) {
    return null;
  }
  const available = payload.available === true;
  const installed = payload.installed === true;
  const deviceId = optionalString(payload.device_id, 36);
  const address = optionalString(payload.address, 32);
  const agentVersion = optionalString(payload.agent_version, 32);
  const nodeId = optionalString(payload.node_id, 32);
  const nodeName = optionalString(payload.node_name, 64);
  const tunnelState = safeString(payload.tunnel_service_state, 32) ?? "unavailable";
  const platform = payload.platform === undefined || payload.platform === null
    ? "windows"
    : typeof payload.platform === "string" &&
        NATIVE_PLATFORMS.has(payload.platform as NativeVpnPlatform)
      ? payload.platform as NativeVpnPlatform
      : null;
  if (
    (deviceId !== null && !DEVICE_ID_PATTERN.test(deviceId)) ||
    (address !== null && !ADDRESS_PATTERN.test(address)) ||
    (agentVersion !== null && !AGENT_FIELD_PATTERN.test(agentVersion)) ||
    (nodeId !== null && !NODE_ID_PATTERN.test(nodeId)) ||
    platform === null ||
    typeof payload.provisioned !== "boolean" ||
    typeof payload.desired_connected !== "boolean" ||
    typeof payload.connected !== "boolean"
  ) {
    return null;
  }
  return {
    address,
    agent_version: agentVersion,
    available,
    connected: payload.connected,
    desired_connected: payload.desired_connected,
    device_id: deviceId,
    installed,
    node_id: nodeId,
    node_name: nodeName,
    platform,
    provisioned: payload.provisioned,
    tunnel_service_state: tunnelState,
  };
}

export function normalizeNativeVpnIdentity(payload: unknown): NativeVpnIdentity | null {
  if (!isRecord(payload) || payload.schema_version !== 1) {
    return null;
  }
  const deviceId = safeString(payload.device_id, 36);
  const publicKey = safeString(payload.public_key, 64);
  const architecture = safeString(payload.architecture, 32);
  const agentVersion = safeString(payload.agent_version, 32);
  const platform = typeof payload.platform === "string" &&
    NATIVE_PLATFORMS.has(payload.platform as NativeVpnPlatform)
    ? payload.platform as NativeVpnPlatform
    : null;
  const defaultNames: Record<NativeVpnPlatform, string> = {
    android: "Android 手机",
    ios: "iPhone",
    macos: "Mac",
    windows: "Windows 电脑",
  };
  const suggestedName = safeString(payload.suggested_name, 64) ??
    (platform ? defaultNames[platform] : "本机设备");
  if (
    !deviceId ||
    !DEVICE_ID_PATTERN.test(deviceId) ||
    !publicKey ||
    !KEY_PATTERN.test(publicKey) ||
    !architecture ||
    !AGENT_FIELD_PATTERN.test(architecture) ||
    !agentVersion ||
    !AGENT_FIELD_PATTERN.test(agentVersion) ||
    !platform
  ) {
    return null;
  }
  return {
    agent_version: agentVersion,
    architecture,
    device_id: deviceId,
    platform,
    public_key: publicKey,
    schema_version: 1,
    suggested_name: suggestedName,
  };
}
