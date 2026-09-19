"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AmzOverview } from "./AmzOverview";
import { AmzWorkspace } from "./AmzWorkspace";
import { CompetitorsPanel } from "./CompetitorsPanel";
import { ControlPanel } from "./ControlPanel";
import { FinancePanel } from "./FinancePanel";
import { ImagesPanel } from "./ImagesPanel";
import { LaunchPanel } from "./LaunchPanel";
import { PortfolioPanel } from "./PortfolioPanel";
import { getEmployeePanel } from "./api";
import styles from "./AmzOverview.module.css";

const TABS = [
  { key: "overview", label: "总览", href: "/amz" },
  { key: "finance", label: "财务 · 殷乐乐", href: "/amz?tab=finance" },
  { key: "cross", label: "跨店 · 主场词 / 需求 / 库存", href: "/amz?tab=cross" },
  { key: "control", label: "总闸 · 梯子 / 护栏 / 台账", href: "/amz?tab=control" },
  { key: "competitors", label: "竞品 · 殷长辰盯盘", href: "/amz?tab=competitors" },
  { key: "launch", label: "推新 · 六步", href: "/amz?tab=launch" },
  { key: "images", label: "图片 · 殷熊的 brief", href: "/amz?tab=images" },
  { key: "manage", label: "管理 · 店铺 / 授权 / 种子", href: "/amz?tab=manage" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

/** 默认是总览(设计稿);其余每块一个 tab。手机(<900px)底部固定一排导航,每个 tab 都在。 */
export function AmzPage() {
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab: TabKey = TABS.some((t) => t.key === raw) ? (raw as TabKey) : "overview";
  const [openTotal, setOpenTotal] = useState(0);
  const company = params.get("company"); // 从侧边栏某家公司进来:切 tab 时带着

  useEffect(() => {
    let alive = true;
    getEmployeePanel()
      .then((panel) => {
        if (alive) setOpenTotal(panel.open_total);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  return (
    <>
      <div className={styles.filters} role="tablist" aria-label="页面">
        {TABS.map((t) => (
          <Link aria-selected={tab === t.key} className={`${styles.chip} ${tab === t.key ? styles.chipOn : ""}`} href={company ? `${t.href}${t.href.includes("?") ? "&" : "?"}company=${encodeURIComponent(company)}` : t.href} key={t.key} role="tab">
            {t.label}
          </Link>
        ))}
      </div>
      {tab === "manage" ? (
        <AmzWorkspace />
      ) : tab === "finance" ? (
        <FinancePanel companyOrgId={params.get("company")} />
      ) : tab === "control" ? (
        <ControlPanel />
      ) : tab === "cross" ? (
        <PortfolioPanel />
      ) : tab === "competitors" ? (
        <CompetitorsPanel />
      ) : tab === "launch" ? (
        <LaunchPanel />
      ) : tab === "images" ? (
        <ImagesPanel briefId={params.get("brief")} suggestionId={params.get("suggestion")} />
      ) : (
        <AmzOverview companyOrgId={params.get("company")} />
      )}
      <nav className={styles.tabs} aria-label="手机导航">
        <Link className={styles.tab} href="/amz">
          总览
        </Link>
        <Link className={`${styles.tab} ${styles.tabMsg}`} href="/amz#amz-crew">
          {openTotal > 0 ? <span className={styles.tabBadge}>{openTotal}</span> : null}
          待拍板
        </Link>
        <Link className={styles.tab} href="/amz?tab=cross">
          跨店
        </Link>
        <Link className={styles.tab} href="/amz?tab=control">
          总闸
        </Link>
        <Link className={styles.tab} href="/amz?tab=manage">
          管理
        </Link>
      </nav>
    </>
  );
}
