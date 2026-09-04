"use client";

import { Copy } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * 一次性凭据横幅:新建账号的初始密码 / 重置出来的 MCP 钥匙 + 装机命令。
 * 明文只显示这一次,由管理者转交;用户管理与「接入钥匙」两页共用。
 */
export type McpSecretPayload = {
  username: string;
  secret?: string | null;
  initialPassword?: string | null;
  setupCommandMac?: string | null;
  setupCommandWindows?: string | null;
};

const CODE_STYLE = {
  color: "var(--color-text-strong)",
  background: "var(--color-canvas)",
  padding: "2px 6px",
  borderRadius: 6,
  border: "1px solid color-mix(in srgb, var(--color-primary) 25%, transparent)",
} as const;

export function McpSecretBanner({
  payload,
  onClose,
}: {
  payload: McpSecretPayload;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState<string | null>(null);
  const [os, setOs] = useState<"mac" | "windows">("mac");
  useEffect(() => {
    if (typeof navigator !== "undefined" && /windows/i.test(navigator.userAgent)) {
      setOs("windows");
    }
  }, []);

  async function copy(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      window.setTimeout(() => setCopied(null), 2500);
    } catch {
      setCopied(null);
    }
  }

  const command = os === "windows" ? payload.setupCommandWindows : payload.setupCommandMac;

  return (
    <div className="users-alert users-alert-success" role="status" style={{ display: "grid", gap: 8 }}>
      <strong>{payload.username} 的一次性凭据——只显示这一次,请立刻转交:</strong>
      {payload.initialPassword ? (
        <span>
          初始密码:<code style={CODE_STYLE}>{payload.initialPassword}</code>{" "}
          <button className="secondary-button" onClick={() => void copy("pw", payload.initialPassword ?? "")} type="button">
            <Copy aria-hidden="true" size={13} /> {copied === "pw" ? "已复制" : "复制"}
          </button>
        </span>
      ) : null}
      {payload.secret ? (
        <span>
          MCP 钥匙:<code style={CODE_STYLE}>{payload.secret}</code>{" "}
          <button className="secondary-button" onClick={() => void copy("tk", payload.secret ?? "")} type="button">
            <Copy aria-hidden="true" size={13} /> {copied === "tk" ? "已复制" : "复制"}
          </button>
        </span>
      ) : null}
      {command ? (
        <span style={{ fontSize: 12, opacity: 0.9, display: "grid", gap: 4 }}>
          <span>
            他在自己电脑({os === "windows" ? "Windows" : "Mac"})的终端里贴这一行回车即可接入 Codex:{" "}
            <button
              className="secondary-button"
              onClick={() => setOs(os === "windows" ? "mac" : "windows")}
              type="button"
            >
              切到 {os === "windows" ? "Mac" : "Windows"}
            </button>
          </span>
          <span>
            <code style={{ ...CODE_STYLE, display: "inline-block", maxWidth: "100%", overflowX: "auto", whiteSpace: "nowrap", verticalAlign: "middle" }}>
              {command}
            </code>{" "}
            <button className="secondary-button" onClick={() => void copy("cmd", command)} type="button">
              <Copy aria-hidden="true" size={13} /> {copied === "cmd" ? "已复制" : "复制这一行"}
            </button>
          </span>
        </span>
      ) : null}
      <button className="secondary-button" onClick={onClose} type="button">
        我已转交,关闭
      </button>
    </div>
  );
}
