export type VpnDevicePlatform =
  | "windows"
  | "macos"
  | "ios"
  | "android"
  | "other";

export type VpnDevice = {
  address: string;
  created_at: string | null;
  enabled: boolean;
  id: string;
  last_handshake_at: string | null;
  name: string;
  node_id: string | null;
  platform: VpnDevicePlatform;
  received_bytes: number | null;
  sent_bytes: number | null;
  updated_at: string | null;
};

export type VpnDeviceList = {
  devices: VpnDevice[];
  unavailable_nodes: string[];
};

export type VpnObfuscation = {
  H1: number;
  H2: number;
  H3: number;
  H4: number;
  Jc: number;
  Jmax: number;
  Jmin: number;
  S1: number;
  S2: number;
  S3: number;
  S4: number;
};

export type NativeVpnProvisioningNode = {
  endpoint: string;
  id: string;
  mtu: number;
  name: string;
  obfuscation: VpnObfuscation;
  public_key: string;
};

/**
 * Schema 2: everything a client needs to build its tunnel comes from the
 * server at enrollment. Clients hold no built-in node address or key.
 */
export type NativeVpnProvisioning = {
  address: string;
  device_id: string;
  dns: string[];
  node: NativeVpnProvisioningNode;
  preshared_key: string;
  schema_version: 2;
};

export type NativeVpnEnrollment = {
  device: VpnDevice;
  one_time: true;
  provisioning: NativeVpnProvisioning;
};

const DEVICE_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ADDRESS_PATTERN =
  /^10\.66\.66\.(?:[2-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-4])\/32$/;
const NODE_ID_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/;
const ENDPOINT_PATTERN =
  /^(?:(?:\d{1,3}\.){3}\d{1,3}|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+):\d{2,5}$/;
const DNS_PATTERN = /^(?:\d{1,3}\.){3}\d{1,3}$/;
const OBFUSCATION_FIELDS: (keyof VpnObfuscation)[] = [
  "Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4",
];
const PLATFORMS = new Set<VpnDevicePlatform>([
  "windows",
  "macos",
  "ios",
  "android",
  "other",
]);
const KEY_PATTERN = /^[A-Za-z0-9+/]{43}=$/;
const MAX_DEVICES = 10 * 32;

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

function safeTimestamp(value: unknown): string | null {
  return value === null ? null : safeString(value, 64);
}

function safeCount(value: unknown): number | null {
  return typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0
    ? value
    : null;
}

export function normalizeVpnDevice(payload: unknown): VpnDevice | null {
  if (!isRecord(payload)) {
    return null;
  }
  const id = safeString(payload.id, 36);
  const name = safeString(payload.name, 64);
  const address = safeString(payload.address, 32);
  const platform = payload.platform;
  const nodeId =
    payload.node_id === undefined || payload.node_id === null
      ? null
      : safeString(payload.node_id, 32);
  if (
    !id ||
    !DEVICE_ID_PATTERN.test(id) ||
    !name ||
    !address ||
    !ADDRESS_PATTERN.test(address) ||
    typeof platform !== "string" ||
    !PLATFORMS.has(platform as VpnDevicePlatform) ||
    typeof payload.enabled !== "boolean" ||
    (nodeId !== null && !NODE_ID_PATTERN.test(nodeId))
  ) {
    return null;
  }
  return {
    address,
    created_at: safeTimestamp(payload.created_at),
    enabled: payload.enabled,
    id,
    last_handshake_at: safeTimestamp(payload.last_handshake_at),
    name,
    node_id: nodeId,
    platform: platform as VpnDevicePlatform,
    received_bytes: safeCount(payload.received_bytes),
    sent_bytes: safeCount(payload.sent_bytes),
    updated_at: safeTimestamp(payload.updated_at),
  };
}

export function normalizeVpnDeviceList(payload: unknown): VpnDeviceList | null {
  if (!isRecord(payload) || !Array.isArray(payload.devices) || payload.devices.length > MAX_DEVICES) {
    return null;
  }
  const devices = payload.devices.map(normalizeVpnDevice);
  if (!devices.every((device): device is VpnDevice => device !== null)) {
    return null;
  }
  const unavailable = Array.isArray(payload.unavailable_nodes)
    ? payload.unavailable_nodes
        .map((entry) => safeString(entry, 32))
        .filter((entry): entry is string => entry !== null && NODE_ID_PATTERN.test(entry))
    : [];
  return { devices, unavailable_nodes: unavailable };
}

export function normalizeVpnObfuscation(payload: unknown): VpnObfuscation | null {
  if (!isRecord(payload)) {
    return null;
  }
  const result: Partial<VpnObfuscation> = {};
  for (const field of OBFUSCATION_FIELDS) {
    const value = safeCount(payload[field]);
    if (value === null) {
      return null;
    }
    result[field] = value;
  }
  return result as VpnObfuscation;
}

export function normalizeNativeVpnProvisioning(
  payload: unknown,
): NativeVpnProvisioning | null {
  if (!isRecord(payload) || payload.schema_version !== 2 || !isRecord(payload.node)) {
    return null;
  }
  const deviceId = safeString(payload.device_id, 36);
  const address = safeString(payload.address, 32);
  const presharedKey = safeString(payload.preshared_key, 64);
  const nodeId = safeString(payload.node.id, 32);
  const nodeName = safeString(payload.node.name, 64);
  const endpoint = safeString(payload.node.endpoint, 260);
  const publicKey = safeString(payload.node.public_key, 64);
  const mtu = payload.node.mtu;
  const obfuscation = normalizeVpnObfuscation(payload.node.obfuscation);
  const dns = Array.isArray(payload.dns)
    ? payload.dns
        .map((entry) => safeString(entry, 15))
        .filter((entry): entry is string => entry !== null && DNS_PATTERN.test(entry))
    : [];
  if (
    !deviceId ||
    !DEVICE_ID_PATTERN.test(deviceId) ||
    !address ||
    !ADDRESS_PATTERN.test(address) ||
    !presharedKey ||
    !KEY_PATTERN.test(presharedKey) ||
    !nodeId ||
    !NODE_ID_PATTERN.test(nodeId) ||
    !nodeName ||
    !endpoint ||
    !ENDPOINT_PATTERN.test(endpoint) ||
    !publicKey ||
    !KEY_PATTERN.test(publicKey) ||
    typeof mtu !== "number" ||
    !Number.isSafeInteger(mtu) ||
    mtu < 576 ||
    mtu > 1500 ||
    !obfuscation ||
    dns.length === 0 ||
    dns.length > 4
  ) {
    return null;
  }
  return {
    address,
    device_id: deviceId,
    dns,
    node: {
      endpoint,
      id: nodeId,
      mtu,
      name: nodeName,
      obfuscation,
      public_key: publicKey,
    },
    preshared_key: presharedKey,
    schema_version: 2,
  };
}

export function normalizeNativeVpnEnrollment(
  payload: unknown,
): NativeVpnEnrollment | null {
  if (!isRecord(payload) || payload.one_time !== true) {
    return null;
  }
  const device = normalizeVpnDevice(payload.device);
  const provisioning = normalizeNativeVpnProvisioning(payload.provisioning);
  if (
    !device ||
    !provisioning ||
    provisioning.device_id !== device.id ||
    provisioning.address !== device.address ||
    (device.node_id !== null && device.node_id !== provisioning.node.id)
  ) {
    return null;
  }
  return { device, one_time: true, provisioning };
}

export function platformLabel(platform: VpnDevicePlatform): string {
  return {
    android: "安卓手机",
    ios: "苹果手机",
    macos: "苹果电脑",
    other: "其他设备",
    windows: "Windows 电脑",
  }[platform];
}
