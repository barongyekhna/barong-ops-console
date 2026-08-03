"use client";

import { useState } from "react";

import { HealthDeck } from "./HealthDeck";
import styles from "./HealthDeck.module.css";
import { PluginSentinel, RedirectManager } from "./WpBridgePanels";

type WorkspaceTab = "health" | "redirects" | "sentinel";

/** 从「巡检中心」的一条死链，带着它的路径跳到「跳转管理」去建规则。 */
export type RedirectHandoff = {
  path: string;
  /** 跳转保存并**验证生效**后，用它把这条死链标成已解决 */
  findingId: string;
  /** 原始死链地址，只用于显示 */
  url: string;
};

const tabs: Array<{ id: WorkspaceTab; label: string }> = [
  { id: "health", label: "巡检中心" },
  { id: "redirects", label: "跳转管理" },
  { id: "sentinel", label: "插件哨兵" },
];

export function SiteHealthWorkspace() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("health");
  const [handoff, setHandoff] = useState<RedirectHandoff | null>(null);

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
        {activeTab === "health" ? (
          <HealthDeck
            onCreateRedirect={(next) => {
              setHandoff(next);
              setActiveTab("redirects");
            }}
          />
        ) : null}
        {activeTab === "redirects" ? (
          <RedirectManager
            handoff={handoff}
            onHandoffConsumed={() => setHandoff(null)}
          />
        ) : null}
        {activeTab === "sentinel" ? <PluginSentinel /> : null}
      </div>
    </div>
  );
}
