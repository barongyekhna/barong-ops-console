"use client";

import { formatBytes, formatRate } from "./nodes";

export type ConnectionPhase =
  | "browser"
  | "connected"
  | "connecting"
  | "disconnected"
  | "disconnecting"
  | "error";

export type ConnectionRates = {
  down_bytes_per_second: number | null;
  up_bytes_per_second: number | null;
};

type ConnectionBarProps = {
  actionDisabled: boolean;
  actionLabel: string;
  address: string | null;
  busy: boolean;
  detail: string;
  nodeName: string | null;
  onAction: () => void;
  onDownloadAndroid?: () => void;
  onDownloadWindows?: () => void;
  phase: ConnectionPhase;
  rates: ConnectionRates;
  totalReceived: number | null;
  totalSent: number | null;
  /** Installed client is too old to enroll: swap the action for the installers. */
  upgradeRequired?: boolean;
};

const PHASE_LABELS: Record<ConnectionPhase, string> = {
  browser: "浏览器模式",
  connected: "已连接",
  connecting: "连接中",
  disconnected: "未连接",
  disconnecting: "断开中",
  error: "异常",
};

/**
 * Always-visible strip: node name, a breathing lamp that reflects the tunnel
 * state, live up/down rate, lifetime totals and the one-tap action.
 */
export function ConnectionBar({
  actionDisabled,
  actionLabel,
  address,
  busy,
  detail,
  nodeName,
  onAction,
  onDownloadAndroid,
  onDownloadWindows,
  phase,
  rates,
  totalReceived,
  totalSent,
  upgradeRequired = false,
}: ConnectionBarProps) {
  const live = phase === "connected";
  return (
    <section
      aria-label="VPN 连接状态"
      className={`cc-vpn-bar cc-vpn-bar-${phase}`}
      data-phase={phase}
    >
      <div className="cc-vpn-bar-identity">
        <span aria-hidden="true" className="cc-vpn-lamp">
          <span className="cc-vpn-lamp-core" />
          <span className="cc-vpn-lamp-ring" />
        </span>
        <div>
          <div className="cc-vpn-bar-node">{nodeName ?? "未选择节点"}</div>
          <div className="cc-vpn-bar-state">
            <span className="cc-vpn-bar-state-label">{PHASE_LABELS[phase]}</span>
            {address ? <span className="cc-vpn-bar-address">{address}</span> : null}
          </div>
        </div>
      </div>

      <div className="cc-vpn-bar-flow" aria-live="off">
        <div className={`cc-vpn-flow ${live ? "cc-vpn-flow-live" : ""}`}>
          <span className="cc-vpn-flow-arrow cc-vpn-flow-down" aria-hidden="true">↓</span>
          <span className="cc-vpn-flow-value">{formatRate(rates.down_bytes_per_second)}</span>
          <span className="cc-vpn-flow-total">{formatBytes(totalReceived)}</span>
        </div>
        <div className={`cc-vpn-flow ${live ? "cc-vpn-flow-live" : ""}`}>
          <span className="cc-vpn-flow-arrow cc-vpn-flow-up" aria-hidden="true">↑</span>
          <span className="cc-vpn-flow-value">{formatRate(rates.up_bytes_per_second)}</span>
          <span className="cc-vpn-flow-total">{formatBytes(totalSent)}</span>
        </div>
        <div className="cc-vpn-wave" aria-hidden="true">
          {Array.from({ length: 12 }, (_, index) => (
            <span key={index} style={{ animationDelay: `${index * 0.09}s` }} />
          ))}
        </div>
      </div>

      <div className="cc-vpn-bar-actions">
        <p className="cc-vpn-bar-detail">{detail}</p>
        {phase === "browser" || upgradeRequired ? (
          <div className="cc-vpn-bar-downloads" data-upgrade-required={upgradeRequired || undefined}>
            <button
              className="cc-customize"
              onClick={onDownloadWindows}
              type="button"
            >
              {upgradeRequired ? "下载最新 Windows 控制台 App" : "下载 Windows 控制台 App"}
            </button>
            <button
              className="cc-vpn-secondary"
              onClick={onDownloadAndroid}
              type="button"
            >
              下载安卓 App
            </button>
          </div>
        ) : (
          <button
            className={`cc-customize cc-vpn-action ${live ? "cc-vpn-action-live" : ""}`}
            disabled={actionDisabled || busy}
            onClick={onAction}
            type="button"
          >
            {busy ? "处理中…" : actionLabel}
          </button>
        )}
      </div>
    </section>
  );
}
