"use client";

import { useState } from "react";

import styles from "./B2BWorkspace.module.css";
import { OutreachWorkspace } from "./outreach/OutreachWorkspace";
import { ProspectWorkspace } from "./prospects/ProspectWorkspace";
import { StoreTypeWorkspace } from "./store-types/StoreTypeWorkspace";
import { WidgetWorkspace } from "./widget/WidgetWorkspace";
import { WholesaleWorkspace } from "./wholesale/WholesaleWorkspace";

type Tab = "store-types" | "wholesale" | "prospects" | "outreach" | "widget";

// 店型排第一：它是 B2B 的主键，挖客户和出图册都从这里派生。
const TABS: { key: Tab; label: string; hint: string }[] = [
  { key: "store-types", label: "店型", hint: "决定卖给谁、一次只跑一条线" },
  { key: "wholesale", label: "批发目录", hint: "填批发价、出 line sheet" },
  { key: "prospects", label: "客户挖掘", hint: "抓店铺、机器筛选、攒名单" },
  { key: "outreach", label: "开发信", hint: "补邮箱、写草稿、你亲手发" },
  { key: "widget", label: "产品页小窗", hint: "谁上线了、政策改了重推" },
];

export function B2BWorkspace() {
  const [tab, setTab] = useState<Tab>("store-types");

  return (
    <div className={styles.shell}>
      <nav className={styles.tabs}>
        {TABS.map((item) => (
          <button
            className={styles.tab}
            data-active={tab === item.key}
            key={item.key}
            onClick={() => setTab(item.key)}
            type="button"
          >
            <span className={styles.tabLabel}>{item.label}</span>
            <span className={styles.tabHint}>{item.hint}</span>
          </button>
        ))}
      </nav>
      {tab === "store-types" ? <StoreTypeWorkspace /> : null}
      {tab === "wholesale" ? <WholesaleWorkspace /> : null}
      {tab === "prospects" ? <ProspectWorkspace /> : null}
      {tab === "outreach" ? <OutreachWorkspace /> : null}
      {tab === "widget" ? <WidgetWorkspace /> : null}
    </div>
  );
}
