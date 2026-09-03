"use client";

import { formatBytes, formatStatusTime, totalTransferBytes } from "./nodes";
import {
  isNodeOnline,
  nodeStateLabel,
  nodeWarningLabel,
  type VpnNode,
} from "./nodes";

type NodePanelProps = {
  currentNodeId: string | null;
  deviceCounts: Record<string, number>;
  error: string;
  nodes: VpnNode[];
  onSelect?: (node: VpnNode) => void;
  selectable: boolean;
  switchingNodeId: string | null;
};

const REGION_FLAGS: Record<string, string> = {
  DE: "🇩🇪",
  HK: "🇭🇰",
  JP: "🇯🇵",
  KR: "🇰🇷",
  SG: "🇸🇬",
  TW: "🇹🇼",
  UK: "🇬🇧",
  US: "🇺🇸",
};

function regionFlag(region: string): string {
  return REGION_FLAGS[region.toUpperCase()] ?? "🌐";
}

/**
 * One component for every node. It renders whatever the registry returns,
 * so adding a node is a server-side change only.
 */
export function NodePanel({
  currentNodeId,
  deviceCounts,
  error,
  nodes,
  onSelect,
  selectable,
  switchingNodeId,
}: NodePanelProps) {
  const sorted = [...nodes].sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
  const onlineCount = sorted.filter(isNodeOnline).length;

  return (
    <article className="module-card cc-vpn-nodes">
      <div className="module-card-header">
        <div>
          <span className={`status-pill ${onlineCount > 0 ? "active" : "error"}`}>
            <span aria-hidden="true" />
            {onlineCount}/{sorted.length} 在线
          </span>
          <h3>节点</h3>
        </div>
        <span className="subtle-badge">NODES</span>
      </div>
      <p>
        {selectable
          ? "点一个节点即切换本机出口；切换会重新登记本机并重写隧道配置。"
          : "所有节点由控制台统一管理；在控制台 App 里可以一键切换。"}
      </p>
      {error ? (
        <div className="form-message" role="alert">
          {error}
        </div>
      ) : null}
      <ul className="cc-vpn-node-list">
        {sorted.map((node) => {
          const online = isNodeOnline(node);
          const current = node.id === currentNodeId;
          const switching = node.id === switchingNodeId;
          const status = node.status;
          const activePeers = status?.vpn.recently_active_peer_count ?? null;
          const transfer = totalTransferBytes(status);
          const canSelect = selectable && node.enabled && online && !current && !switching;
          return (
            <li
              className={`cc-vpn-node ${online ? "cc-vpn-node-online" : "cc-vpn-node-offline"} ${current ? "cc-vpn-node-current" : ""}`}
              data-node-id={node.id}
              key={node.id}
            >
              <button
                className="cc-vpn-node-main"
                disabled={!canSelect}
                onClick={() => onSelect?.(node)}
                type="button"
              >
                <span aria-hidden="true" className="cc-vpn-node-flag">
                  {regionFlag(node.region)}
                </span>
                <span className="cc-vpn-node-text">
                  <span className="cc-vpn-node-name">
                    {node.name}
                    {current ? <em className="cc-vpn-node-tag">当前</em> : null}
                    {switching ? <em className="cc-vpn-node-tag cc-vpn-node-tag-busy">切换中…</em> : null}
                  </span>
                  <span className="cc-vpn-node-meta">
                    <span className={`cc-vpn-node-dot ${online ? "on" : node.state === "degraded" ? "warn" : "off"}`} aria-hidden="true" />
                    {nodeStateLabel(node)}
                    {status?.vpn.listen_port ? ` · UDP ${status.vpn.listen_port}` : ""}
                    {activePeers !== null ? ` · ${activePeers} 台在线` : ""}
                    {deviceCounts[node.id] ? ` · 我的 ${deviceCounts[node.id]} 台` : ""}
                  </span>
                  {node.warnings.length > 0 ? (
                    <span className="cc-vpn-node-warn">
                      {node.warnings.map(nodeWarningLabel).join("；")}
                    </span>
                  ) : null}
                </span>
                <span className="cc-vpn-node-stats">
                  <span className="cc-vpn-node-stat">
                    <small>累计流量</small>
                    <strong>{formatBytes(transfer)}</strong>
                  </span>
                  <span className="cc-vpn-node-stat">
                    <small>最近握手</small>
                    <strong>
                      {status?.vpn.latest_handshake_at
                        ? formatStatusTime(status.vpn.latest_handshake_at)
                        : "—"}
                    </strong>
                  </span>
                </span>
              </button>
            </li>
          );
        })}
        {sorted.length === 0 ? (
          <li className="cc-vpn-node-empty">
            {/* 取不到数据时不许说「还没有登记任何节点」——那是在断言一件我们
                并不知道的事。2026-08-31 体检：后端一条 /vpn 路由都没有，
                接口全 404，页面却把「接口不存在」渲染成「你还没配节点」，
                于是任何人（包括 owner）都会以为是自己配错了。
                而 VPN 实际有两个在跑的节点。 */}
            {error ? "节点列表没取到，上面是原因。" : "还没有登记任何节点。"}
          </li>
        ) : null}
      </ul>
    </article>
  );
}
