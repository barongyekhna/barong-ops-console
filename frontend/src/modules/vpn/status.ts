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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return normalized.length > 0 && normalized.length <= 256 ? normalized : null;
}

function safeCount(value: unknown): number | null {
  return typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0
    ? value
    : null;
}

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
