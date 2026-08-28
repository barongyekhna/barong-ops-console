"use client";

import { platformLabel, type VpnDevice } from "./devices";
import type { VpnNode } from "./nodes";
import { formatBytes, formatStatusTime } from "./nodes";

type DeviceListProps = {
  busy: boolean;
  currentDeviceId: string | null;
  devices: VpnDevice[];
  error: string;
  nodes: VpnNode[];
  onToggle: (device: VpnDevice) => void;
  unavailableNodes: string[];
};

const PLATFORM_ICONS: Record<VpnDevice["platform"], string> = {
  android: "📱",
  ios: "📱",
  macos: "💻",
  other: "🖥️",
  windows: "🖥️",
};

/**
 * Read-only roster of the signed-in user's devices. Devices only appear here
 * after a device enrolls itself from the console app; nothing is added by hand.
 */
export function DeviceList({
  busy,
  currentDeviceId,
  devices,
  error,
  nodes,
  onToggle,
  unavailableNodes,
}: DeviceListProps) {
  const nodeName = (nodeId: string | null) =>
    nodes.find((node) => node.id === nodeId)?.name ?? nodeId ?? "—";

  return (
    <article className="module-card cc-vpn-devices">
      <div className="module-card-header">
        <div>
          <span className="status-pill active">
            <span aria-hidden="true" />
            本人可见
          </span>
          <h3>我的设备</h3>
        </div>
        <span className="subtle-badge">{devices.length} 台</span>
      </div>
      <p>
        设备只会由控制台 App 在登录后自动登记；要加一台新设备，就在那台设备上安装控制台
        App 并登录。其他用户看不到、也操作不了这些设备。
      </p>
      {error ? (
        <div className="form-message" role="alert">
          {error}
        </div>
      ) : null}
      {unavailableNodes.length > 0 ? (
        <div className="form-message">
          {unavailableNodes.map(nodeName).join("、")} 暂时没有响应，这些节点上的设备没有列出。
        </div>
      ) : null}
      {devices.length === 0 ? (
        <div className="cc-vpn-empty">
          <span aria-hidden="true">📡</span>
          在新设备上安装控制台 App 并登录，它会自动出现在这里。
        </div>
      ) : (
        <ul className="cc-vpn-device-list">
          {devices.map((device) => {
            const current = device.id === currentDeviceId;
            return (
              <li
                className={`cc-vpn-device ${device.enabled ? "" : "cc-vpn-device-off"} ${current ? "cc-vpn-device-current" : ""}`}
                key={device.id}
              >
                <span aria-hidden="true" className="cc-vpn-device-icon">
                  {PLATFORM_ICONS[device.platform]}
                </span>
                <span className="cc-vpn-device-text">
                  <span className="cc-vpn-device-name">
                    {device.name}
                    {current ? <em className="cc-vpn-node-tag">本机</em> : null}
                  </span>
                  <span className="cc-vpn-device-meta">
                    {platformLabel(device.platform)} · {nodeName(device.node_id)} · {device.address}
                  </span>
                  <span className="cc-vpn-device-meta">
                    {device.last_handshake_at
                      ? `最后连接 ${formatStatusTime(device.last_handshake_at)}`
                      : "尚未连接"}
                    {" · "}↓ {formatBytes(device.received_bytes)} ↑ {formatBytes(device.sent_bytes)}
                  </span>
                </span>
                <span className={`status-pill ${device.enabled ? "active" : "disabled"}`}>
                  <span aria-hidden="true" />
                  {device.enabled ? "已启用" : "已停用"}
                </span>
                <button
                  className="module-card-action cc-vpn-device-toggle"
                  disabled={busy}
                  onClick={() => onToggle(device)}
                  type="button"
                >
                  {device.enabled ? "停用" : "重新启用"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}
