import type { Metadata } from "next";

import { DashboardScene } from "@/components/dashboard-scene";
import { McpKeysPanel } from "@/components/mcp-keys-panel";

export const metadata: Metadata = {
  title: "接入钥匙",
};

export default function McpKeysPage() {
  return (
    <div className="page-stack users-page">
      <DashboardScene />
      <div className="page-heading">
        <span className="section-index">接入</span>
        <div>
          <h2>接入钥匙</h2>
          <p>每个真人账号一把 MCP 个人钥匙:谁接入了 Codex、谁没接、谁被停了、最近谁用过。只对 owner 与超级管理员开放。</p>
        </div>
      </div>
      <McpKeysPanel />
    </div>
  );
}
