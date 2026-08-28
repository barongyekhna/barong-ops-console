// Self-contained (no runtime sibling imports) so node's test runner can load
// it directly, matching the convention of the other tested frontend modules.

export type VpnStatus = {
  agent_version: string | null;
  generated_at: string | null;
  status: "ok";
  vpn: {
    address: string | null;
    expected_listen_port: number | null;
    interface: "awg0";
    latest_handshake_at: string | null;
    listen_port: number | null;
    peer_count: number | null;
    recently_active_peer_count: number | null;
    service: {
      active_since: string | null;
      active_state: string | null;
      sub_state: string | null;
    };
    transfer: {
      received_bytes: number | null;
      sent_bytes: number | null;
    };
  };
  warnings: string[];
};

export type VpnNodeState = "ok" | "degraded" | "unreachable";

export type VpnNode = {
  enabled: boolean;
  id: string;
  name: string;
  order: number;
  region: string;
  state: VpnNodeState;
  status: VpnStatus | null;
  warnings: string[];
};

const NODE_ID_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/;
const MAX_NODES = 32;

const WARNING_LABELS: Record<string, string> = {
  interface_status_unavailable: "隧道网卡没有地址",
  node_unreachable: "控制台连不上这个节点",
  service_status_unavailable: "专线服务状态未知",
  vpn_status_unavailable: "专线程序无响应",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeString(value: unknown, maxLength = 256): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return normalized.length > 0 && normalized.length <= maxLength
    ? normalized
    : null;
}

function safeCount(value: unknown): number | null {
  return typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0
    ? value
    : null;
}

// ---- per-node status ------------------------------------------------------

export function normalizeVpnStatus(payload: unknown): VpnStatus | null {
  if (!isRecord(payload) || payload.status !== "ok" || !isRecord(payload.vpn)) {
    return null;
  }
  const vpn = payload.vpn;
  if (
    vpn.interface !== "awg0" ||
    !isRecord(vpn.service) ||
    !isRecord(vpn.transfer)
  ) {
    return null;
  }
  const warnings = Array.isArray(payload.warnings)
    ? payload.warnings
        .map((warning) => safeString(warning))
        .filter((warning): warning is string => warning !== null)
        .slice(0, 10)
    : [];
  return {
    agent_version: safeString(payload.agent_version),
    generated_at: safeString(payload.generated_at),
    status: "ok",
    vpn: {
      address: safeString(vpn.address),
      expected_listen_port: safeCount(vpn.expected_listen_port),
      interface: "awg0",
      latest_handshake_at: safeString(vpn.latest_handshake_at),
      listen_port: safeCount(vpn.listen_port),
      peer_count: safeCount(vpn.peer_count),
      recently_active_peer_count: safeCount(vpn.recently_active_peer_count),
      service: {
        active_since: safeString(vpn.service.active_since),
        active_state: safeString(vpn.service.active_state),
        sub_state: safeString(vpn.service.sub_state),
      },
      transfer: {
        received_bytes: safeCount(vpn.transfer.received_bytes),
        sent_bytes: safeCount(vpn.transfer.sent_bytes),
      },
    },
    warnings,
  };
}

export function isVpnOnline(status: VpnStatus | null): boolean {
  if (!status || status.vpn.service.active_state !== "active") {
    return false;
  }
  if (status.vpn.listen_port === null || status.vpn.listen_port <= 0) {
    return false;
  }
  return (
    status.vpn.expected_listen_port === null ||
    status.vpn.listen_port === status.vpn.expected_listen_port
  );
}

export function totalTransferBytes(status: VpnStatus | null): number | null {
  if (!status) {
    return null;
  }
  const received = status.vpn.transfer.received_bytes;
  const sent = status.vpn.transfer.sent_bytes;
  if (received === null || sent === null) {
    return null;
  }
  return received + sent;
}

// ---- node registry --------------------------------------------------------

export function normalizeVpnNode(payload: unknown): VpnNode | null {
  if (!isRecord(payload)) {
    return null;
  }
  const id = safeString(payload.id, 32);
  const name = safeString(payload.name, 64);
  const region = typeof payload.region === "string" ? payload.region.trim().slice(0, 32) : "";
  const order =
    typeof payload.order === "number" && Number.isSafeInteger(payload.order)
      ? payload.order
      : 100;
  if (!id || !NODE_ID_PATTERN.test(id) || !name || typeof payload.enabled !== "boolean") {
    return null;
  }
  const rawStatus = payload.status;
  let state: VpnNodeState = "unreachable";
  let status: VpnStatus | null = null;
  let warnings: string[] = [];
  if (isRecord(rawStatus)) {
    const rawState = rawStatus.status;
    if (rawState === "ok" || rawState === "degraded") {
      status = normalizeVpnStatus({ ...rawStatus, status: "ok" });
      state = status ? rawState : "unreachable";
    }
    if (Array.isArray(rawStatus.warnings)) {
      warnings = rawStatus.warnings
        .map((warning) => safeString(warning, 200))
        .filter((warning): warning is string => warning !== null)
        .slice(0, 10);
    }
  }
  return { enabled: payload.enabled, id, name, order, region, state, status, warnings };
}

export function normalizeVpnNodeList(payload: unknown): VpnNode[] | null {
  if (!isRecord(payload) || !Array.isArray(payload.nodes) || payload.nodes.length > MAX_NODES) {
    return null;
  }
  const nodes = payload.nodes.map(normalizeVpnNode);
  return nodes.every((node): node is VpnNode => node !== null) ? nodes : null;
}

export function isNodeOnline(node: VpnNode): boolean {
  return node.enabled && node.state === "ok" && isVpnOnline(node.status);
}

export function nodeWarningLabel(warning: string): string {
  return WARNING_LABELS[warning] ?? warning;
}

export function nodeStateLabel(node: VpnNode): string {
  if (!node.enabled) {
    return "已停用";
  }
  if (isNodeOnline(node)) {
    return "在线";
  }
  if (node.state === "degraded") {
    return "降级";
  }
  if (node.state === "ok") {
    return "未就绪";
  }
  return "失联";
}

// ---- formatting -----------------------------------------------------------

export function formatBytes(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    return "—";
  }
  if (value === 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unitIndex = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1,
  );
  const scaled = value / 1024 ** unitIndex;
  const digits = scaled < 10 && unitIndex > 0 ? 1 : 0;
  return `${scaled.toFixed(digits)} ${units[unitIndex]}`;
}

export function formatRate(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value < 0) {
    return "—";
  }
  return `${formatBytes(Math.round(value))}/s`;
}

export function formatStatusTime(value: string | null | undefined): string {
  if (!value) {
    return "暂无记录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(date);
}
