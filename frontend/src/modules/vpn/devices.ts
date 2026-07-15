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
  platform: VpnDevicePlatform;
  received_bytes: number | null;
  sent_bytes: number | null;
  updated_at: string | null;
};

export type CreatedVpnDevice = {
  configuration: string;
  device: VpnDevice;
  one_time: true;
};

export type NativeVpnProvisioning = {
  address: string;
  device_id: string;
  preshared_key: string;
  schema_version: 1;
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
const PLATFORMS = new Set<VpnDevicePlatform>([
  "windows",
  "macos",
  "ios",
  "android",
  "other",
]);
const KEY_PATTERN = /^[A-Za-z0-9+/]{43}=$/;

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
  if (
    !id ||
    !DEVICE_ID_PATTERN.test(id) ||
    !name ||
    !address ||
    !ADDRESS_PATTERN.test(address) ||
    typeof platform !== "string" ||
    !PLATFORMS.has(platform as VpnDevicePlatform) ||
    typeof payload.enabled !== "boolean"
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
    platform: platform as VpnDevicePlatform,
    received_bytes: safeCount(payload.received_bytes),
    sent_bytes: safeCount(payload.sent_bytes),
    updated_at: safeTimestamp(payload.updated_at),
  };
}

export function normalizeVpnDeviceList(payload: unknown): VpnDevice[] | null {
  if (!isRecord(payload) || !Array.isArray(payload.devices) || payload.devices.length > 10) {
    return null;
  }
  const devices = payload.devices.map(normalizeVpnDevice);
  return devices.every((device): device is VpnDevice => device !== null)
    ? devices
    : null;
}

export function normalizeCreatedVpnDevice(
  payload: unknown,
): CreatedVpnDevice | null {
  if (!isRecord(payload) || payload.one_time !== true) {
    return null;
  }
  const device = normalizeVpnDevice(payload.device);
  const configuration =
    typeof payload.configuration === "string" &&
    payload.configuration.length > 0 &&
    payload.configuration.length <= 8192
      ? payload.configuration
      : null;
  if (!device || !configuration) {
    return null;
  }
  return { configuration, device, one_time: true };
}

export function normalizeNativeVpnEnrollment(
  payload: unknown,
): NativeVpnEnrollment | null {
  if (!isRecord(payload) || payload.one_time !== true) {
    return null;
  }
  const device = normalizeVpnDevice(payload.device);
  const provisioning = payload.provisioning;
  if (!device || !isRecord(provisioning)) {
    return null;
  }
  const deviceId = safeString(provisioning.device_id, 36);
  const address = safeString(provisioning.address, 32);
  const presharedKey = safeString(provisioning.preshared_key, 64);
  if (
    provisioning.schema_version !== 1 ||
    !deviceId ||
    !DEVICE_ID_PATTERN.test(deviceId) ||
    deviceId !== device.id ||
    !address ||
    !ADDRESS_PATTERN.test(address) ||
    address !== device.address ||
    !presharedKey ||
    !KEY_PATTERN.test(presharedKey)
  ) {
    return null;
  }
  return {
    device,
    one_time: true,
    provisioning: {
      address,
      device_id: deviceId,
      preshared_key: presharedKey,
      schema_version: 1,
    },
  };
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
