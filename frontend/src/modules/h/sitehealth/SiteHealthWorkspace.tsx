"use client";

import { useState } from "react";

import { HealthDeck } from "./HealthDeck";
import styles from "./HealthDeck.module.css";
import { PluginSentinel, RedirectManager } from "./WpBridgePanels";

type WorkspaceTab = "health" | "redirects" | "sentinel";

const tabs: Array<{ id: WorkspaceTab; label: string }> = [
  { id: "health", label: "巡检中心" },
  { id: "redirects", label: "跳转管理" },
  { id: "sentinel", label: "插件哨兵" },
];

export function SiteHealthWorkspace() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("health");

  return (
    <div className={styles.workspace}>
      <div aria-label="H 站点健康工作区" className={styles.workspaceTabs} role="tablist">
        {tabs.map((tab) => (
          <button
            aria-selected={activeTab === tab.id}
            className={`${styles.workspaceTab} ${activeTab === tab.id ? styles.workspaceTabOn : ""}`}
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            role="tab"
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div role="tabpanel">
        {activeTab === "health" ? <HealthDeck /> : null}
        {activeTab === "redirects" ? <RedirectManager /> : null}
        {activeTab === "sentinel" ? <PluginSentinel /> : null}
      </div>
    </div>
  );
}
