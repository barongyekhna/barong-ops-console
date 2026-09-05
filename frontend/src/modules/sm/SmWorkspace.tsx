"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import styles from "./SmWorkspace.module.css";
import {
  type Channel,
  type Inventory,
  type Job,
  type Platform,
  PLATFORM_LABEL,
  getChannels,
  getInventory,
  getJobs,
  planCalendar,
} from "./api";
import { CalendarPanel } from "./CalendarPanel";
import { GapsPanel } from "./GapsPanel";
import { PostsPanel } from "./PostsPanel";
import { ProfilesPanel } from "./ProfilesPanel";

type Tab = "calendar" | "gaps" | "posts" | "profiles";

const TABS: { key: Tab; label: string; hint: string }[] = [
  { key: "calendar", label: "日历", hint: "四周 × 三平台，什么时候发什么" },
  { key: "gaps", label: "缺口单", hint: "版式 / Codex / 真照片三条道" },
  { key: "posts", label: "帖子", hint: "写出来的稿子；审在内容台" },
  { key: "profiles", label: "渠道档案", hint: "平台调性与图片需求单；登记渠道" },
];

function isTab(value: string | null): value is Tab {
  return value === "calendar" || value === "gaps" || value === "posts" || value === "profiles";
}

export function SmWorkspace() {
  const router = useRouter();
  const params = useSearchParams();
  const initialTab = params.get("tab");
  const [tab, setTab] = useState<Tab>(isTab(initialTab) ? initialTab : "calendar");
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [planning, setPlanning] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const refresh = useCallback(() => setRefreshTick((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    // 用 allSettled：一路失败不吞掉另一路已经成功的结果（information-flattening 反模式）。
    Promise.allSettled([getChannels(), getInventory(), getJobs()]).then(([c, inv, j]) => {
      if (cancelled) return;
      const problems: string[] = [];
      if (c.status === "fulfilled") setChannels(c.value.channels);
      else problems.push(c.reason instanceof Error ? c.reason.message : String(c.reason));
      if (inv.status === "fulfilled") setInventory(inv.value);
      else problems.push(inv.reason instanceof Error ? inv.reason.message : String(inv.reason));
      if (j.status === "fulfilled") setJobs(j.value.jobs);
      else problems.push(j.reason instanceof Error ? j.reason.message : String(j.reason));
      setError(problems.length ? problems.join("；") : null);
    });
    return () => {
      cancelled = true;
    };
  }, [refreshTick]);

  // 有任务在飞就 5 秒轮询一次任务表，飞完刷新整页数据。
  const inFlight = useMemo(() => jobs.some((j) => j.status === "pending" || j.status === "running"), [jobs]);
  useEffect(() => {
    if (!inFlight) return;
    const timer = window.setInterval(() => {
      getJobs()
        .then((data) => {
          setJobs(data.jobs);
          if (!data.jobs.some((j) => j.status === "pending" || j.status === "running")) {
            refresh();
          }
        })
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [inFlight, refresh]);

  const switchTab = (next: Tab) => {
    setTab(next);
    router.replace(`/sm?tab=${next}`);
  };

  const handlePlan = async () => {
    if (planning) return;
    setPlanning(true);
    setError(null);
    try {
      const result = await planCalendar(28);
      setNotice(
        `排好了：新增 ${result.created} 格（${Object.entries(result.per_platform)
          .map(([k, v]) => `${PLATFORM_LABEL[k as Platform] ?? k} ${v}`)
          .join(" · ")}），其中 ${result.blocked} 格没源头。`,
      );
      window.setTimeout(() => setNotice(null), 8000);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPlanning(false);
    }
  };

  const activeChannels = (channels ?? []).filter((c) => c.status === "active");
  const skuById = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of inventory?.products ?? []) map.set(p.product_id, p.sku);
    return map;
  }, [inventory]);

  return (
    <div className={styles.workspace}>
      <div className={styles.topbar}>
        <nav className={styles.tabs}>
          {TABS.map((item) => (
            <button
              className={styles.tab}
              data-active={tab === item.key}
              key={item.key}
              onClick={() => switchTab(item.key)}
              type="button"
            >
              <span className={styles.tabLabel}>{item.label}</span>
              <span className={styles.tabHint}>{item.hint}</span>
            </button>
          ))}
        </nav>
        <div className={styles.actions}>
          <span className={styles.muted}>
            {channels === null
              ? "渠道加载中…"
              : activeChannels.length === 0
                ? "还没登记渠道：去「渠道档案」先登记平台（mock 期都是手动）"
                : `渠道 ${activeChannels.map((c) => PLATFORM_LABEL[c.platform]).join(" / ")} · mock 不外发`}
          </span>
          <button
            className={styles.btnPrimary}
            disabled={planning || activeChannels.length === 0}
            onClick={handlePlan}
            type="button"
          >
            {planning ? "排期中…" : "重排未来 28 天"}
          </button>
        </div>
      </div>

      {inventory ? (
        <div className={styles.kpis}>
          <div className={styles.kpi}><b>{inventory.summary.products_in_stock}/{inventory.summary.products}</b><span>可发产品 / 有货</span></div>
          <div className={styles.kpi}><b>{inventory.summary.guides}</b><span>已发布指南</span></div>
          <div className={styles.kpi}><b>{inventory.summary.facts}</b><span>已批工艺事实</span></div>
          <div className={styles.kpi}><b>{inventory.summary.factory_photos}</b><span>工厂真照片</span></div>
          <div className={styles.kpi}><b>{inventory.summary.pin_reserve_estimate}</b><span>图钉储备估算</span></div>
          <div className={styles.kpi}><b>{jobs.filter((j) => j.status === "pending" || j.status === "running").length}</b><span>写手任务在飞</span></div>
        </div>
      ) : null}

      {error ? <div className={styles.error}>{error}</div> : null}
      {notice ? <div className={styles.notice}>{notice}</div> : null}

      {tab === "calendar" ? <CalendarPanel jobs={jobs} onChanged={refresh} refreshTick={refreshTick} /> : null}
      {tab === "gaps" ? <GapsPanel onChanged={refresh} refreshTick={refreshTick} skuById={skuById} /> : null}
      {tab === "posts" ? <PostsPanel initialPostId={params.get("post")} onChanged={refresh} refreshTick={refreshTick} /> : null}
      {tab === "profiles" ? <ProfilesPanel channels={channels ?? []} onChanged={refresh} /> : null}
    </div>
  );
}
