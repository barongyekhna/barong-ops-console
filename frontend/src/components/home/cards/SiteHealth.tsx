"use client";

import { useEffect, useState } from "react";

import { isApiAbortError } from "@/lib/api";
import { getWpSentinel } from "@/modules/h/sitehealth/api";

import { formatDateTime, type HomeCardRead } from "../home-api";
import { HomeCardShell, HomeItemList } from "../HomeCardShell";
import type { HomeDrawerProps } from "../home-types";

type RunExtra = {
  id: string;
  status: string;
  urls_total: number;
  urls_ok: number;
  urls_broken: number;
  urls_slow: number;
  homepage_ok: boolean;
  sitemap_ok: boolean;
  p95_response_ms: number | null;
} | null;

type StaleWorker = { worker_name: string; silent_seconds: number | null };

function pill(ok: boolean, label: string) {
  return (
    <div>
      {label}
      <span className={ok ? "hs-pill hs-pill-ok" : "hs-pill hs-pill-bad"}>{ok ? "OK" : "异常"}</span>
    </div>
  );
}

export function SiteHealthCard({ card, onOpen }: { card: HomeCardRead; onOpen: () => void }) {
  const run = (card.extra.run as RunExtra) ?? null;
  const stale = (card.extra.stale_workers as StaleWorker[] | undefined) ?? [];
  const label =
    card.severity === "error" ? "有异常" : card.severity === "warn" ? "需留意" : "全部正常";
  return (
    <HomeCardShell card={card} external onOpen={onOpen} tag="H 哨兵" title="站点健康">
      <div className={`hs-pill hs-pill-${card.severity === "ok" ? "ok" : card.severity === "warn" ? "warn" : "bad"}`}>
        {label}
      </div>
      {run ? (
        <div className="hs-health">
          {pill(run.homepage_ok, "首页")}
          {pill(run.urls_broken === 0, `断链 ${run.urls_broken}`)}
          {pill(run.sitemap_ok, "sitemap")}
          {pill(run.urls_slow === 0, `慢页 ${run.urls_slow}`)}
        </div>
      ) : (
        <div className="hs-empty">还没有巡检记录。</div>
      )}
      {stale.length > 0 ? (
        <div className="hs-alert">
          {stale.map((worker) => worker.worker_name).join("、")} 失联
        </div>
      ) : null}
    </HomeCardShell>
  );
}

type SentinelState = { loading: boolean; error: string | null; data: unknown };

export function SiteHealthDrawer({ card }: HomeDrawerProps) {
  const run = (card.extra.run as RunExtra) ?? null;
  const [sentinel, setSentinel] = useState<SentinelState>({ loading: false, error: null, data: null });

  useEffect(() => {
    let active = true;
    setSentinel({ loading: true, error: null, data: null });
    getWpSentinel()
      .then((data) => {
        if (active) setSentinel({ loading: false, error: null, data });
      })
      .catch((error: unknown) => {
        if (active && !isApiAbortError(error)) {
          setSentinel({ loading: false, error: "哨兵快照暂时拿不到。", data: null });
        }
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="hs-drawer-body">
      <section className="hs-block">
        <div className="hs-block-head">
          <span>最近一次巡检</span>
          <span className="hs-muted">{formatDateTime(card.freshness)}</span>
        </div>
        {run ? (
          <div className="hs-health">
            <div>状态<span className="hs-pill hs-pill-info">{run.status}</span></div>
            <div>共 {run.urls_total} 页<span className="hs-pill hs-pill-ok">{run.urls_ok} OK</span></div>
            {pill(run.homepage_ok, "首页")}
            {pill(run.sitemap_ok, "sitemap")}
            {pill(run.urls_broken === 0, `断链 ${run.urls_broken}`)}
            {pill(run.urls_slow === 0, `慢页 ${run.urls_slow}`)}
            <div>p95 响应<span className="hs-pill hs-pill-info">{run.p95_response_ms ?? "—"} ms</span></div>
          </div>
        ) : (
          <div className="hs-empty">还没有巡检记录。</div>
        )}
      </section>
      <section className="hs-block">
        <div className="hs-block-head"><span>失联的 worker</span></div>
        <HomeItemList card={{ ...card, items: card.items.filter((item) => item.id.startsWith("worker:")) }} empty="所有 worker 心跳正常。" />
      </section>
      <section className="hs-block">
        <div className="hs-block-head">
          <span>WordPress 插件哨兵</span>
          <span className="hs-muted">{sentinel.loading ? "现查中…" : "按需实时查"}</span>
        </div>
        {sentinel.error ? <div className="hs-alert">{sentinel.error}</div> : null}
        {sentinel.data ? (
          <pre className="hs-pre">{JSON.stringify(sentinel.data, null, 2)}</pre>
        ) : null}
      </section>
    </div>
  );
}
