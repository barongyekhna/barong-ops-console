"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { isApiAbortError } from "@/lib/api";

import {
  formatClock,
  getHomeTrafficRange,
  type HomeCardRead,
  type HomeTrafficRange,
  type HomeTrafficSummary,
} from "../home-api";
import { HomeCardShell } from "../HomeCardShell";
import { TrafficBars } from "../TrafficBars";
import type { HomeDrawerProps } from "../home-types";

const MAX_RANGE_DAYS = 92;

function summaryOf(card: HomeCardRead): HomeTrafficSummary | null {
  const extra = card.extra as Partial<HomeTrafficSummary>;
  if (!Array.isArray(extra.days)) return null;
  return extra as HomeTrafficSummary;
}

function delta(current: number, previous: number) {
  if (current === previous) return null;
  const up = current > previous;
  return (
    <span className={up ? "hs-delta hs-delta-up" : "hs-delta hs-delta-down"}>
      {up ? "▲" : "▼"}
      {Math.abs(current - previous)}
    </span>
  );
}

function text(value: unknown, fallback = "—") {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function num(value: unknown) {
  return typeof value === "number" ? value : 0;
}

export function SiteTrafficCard({ card, onOpen }: { card: HomeCardRead; onOpen: () => void }) {
  const summary = summaryOf(card);
  const rangeLabel = summary ? `${summary.day_from.slice(5)} → ${summary.day_to.slice(5)}` : "";
  return (
    <HomeCardShell
      card={card}
      external
      freshnessNote={`站点时区 UTC${summary?.site_utc_offset ?? "-5"}`}
      onOpen={onOpen}
      tag={summary ? `最近 7 天 · ${rangeLabel}` : "最近 7 天"}
      title="独立站流量"
    >
      {!summary ? (
        <div className="hs-empty">还没有采集到数据。</div>
      ) : (
        <>
          {summary.collector_stale ? (
            <div className="hs-alert">
              采集停了：最近一次成功 {formatClock(summary.collected_at)}，超过 20 分钟没有心跳。
            </div>
          ) : null}
          <div className="hs-kpis">
            <div className="hs-kpi">
              <b>
                {summary.visitors}
                {delta(summary.visitors, summary.prev_visitors)}
              </b>
              <span>7 天访客 · 上个 7 天 {summary.prev_visitors}</span>
            </div>
            <div className="hs-kpi">
              <b>
                {summary.views}
                {delta(summary.views, summary.prev_views)}
              </b>
              <span>7 天浏览 · 上个 7 天 {summary.prev_views}</span>
            </div>
            <div className="hs-kpi">
              <b>{summary.today?.visitors ?? 0}</b>
              <span>今天访客 · 昨天 {summary.yesterday?.visitors ?? 0}</span>
            </div>
            <div className="hs-kpi">
              <b>{summary.today?.views ?? 0}</b>
              <span>今天浏览 · 昨天 {summary.yesterday?.views ?? 0}</span>
            </div>
          </div>
          <TrafficBars days={summary.days} height={120} />
          <div className="hs-tri">
            <div>
              <em>7 天最热页面</em>
              <strong title={text(summary.top_post?.title)}>{text(summary.top_post?.title, "暂无")}</strong>
            </div>
            <div>
              <em>7 天来源</em>
              <strong>
                {summary.top_referrer
                  ? `${text(summary.top_referrer.name)} · ${num(summary.top_referrer.views)}`
                  : "直接访问为主"}
              </strong>
            </div>
            <div>
              <em>7 天国家</em>
              <strong>
                {summary.top_country
                  ? `${text(summary.top_country.name)} · ${num(summary.top_country.views)}`
                  : "暂无"}
              </strong>
            </div>
          </div>
        </>
      )}
    </HomeCardShell>
  );
}

type Preset = 7 | 14 | 30;

function isoDaysAgo(anchor: string, days: number) {
  const date = new Date(`${anchor}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - days);
  return date.toISOString().slice(0, 10);
}

function Table({
  rows,
  labelKey,
  total,
}: {
  rows: Array<Record<string, unknown>>;
  labelKey: string;
  total?: number;
}) {
  if (rows.length === 0) return <div className="hs-empty">区间内没有记录。</div>;
  const top = num(rows[0]?.views) || 1;
  return (
    <table className="hs-table">
      <tbody>
        {rows.map((row, index) => {
          const views = num(row.views);
          const label = text(row[labelKey], text(row.name, "—"));
          return (
            <tr key={`${label}-${index}`}>
              <td title={label}>
                {label}
                <div className="hs-bar" style={{ width: `${Math.round((100 * views) / top)}%` }} />
              </td>
              <td>
                {views}
                {total ? ` · ${Math.round((100 * views) / total)}%` : ""}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function SiteTrafficDrawer({ card }: HomeDrawerProps) {
  const summary = summaryOf(card);
  const anchor = summary?.day_to ?? new Date().toISOString().slice(0, 10);
  const [preset, setPreset] = useState<Preset | null>(7);
  const [from, setFrom] = useState(() => isoDaysAgo(anchor, 6));
  const [to, setTo] = useState(anchor);
  const [report, setReport] = useState<HomeTrafficRange | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const spanDays = useMemo(() => {
    const start = new Date(`${from}T00:00:00Z`).getTime();
    const end = new Date(`${to}T00:00:00Z`).getTime();
    if (Number.isNaN(start) || Number.isNaN(end)) return 0;
    return Math.round((end - start) / 86_400_000) + 1;
  }, [from, to]);

  const load = useCallback(async (controller: AbortController) => {
    if (spanDays <= 0) {
      setError("结束日期不能早于开始日期。");
      return;
    }
    if (spanDays > MAX_RANGE_DAYS) {
      setError(`最多一次看 ${MAX_RANGE_DAYS} 天。`);
      return;
    }
    setError(null);
    setLoading(true);
    try {
      setReport(await getHomeTrafficRange(from, to, controller.signal));
    } catch (caught) {
      if (!isApiAbortError(caught)) setError("区间数据暂时拿不到。");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [from, spanDays, to]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller);
    return () => controller.abort();
  }, [load]);

  const choosePreset = (days: Preset) => {
    setPreset(days);
    setFrom(isoDaysAgo(anchor, days - 1));
    setTo(anchor);
  };

  const days = report?.days ?? summary?.days ?? [];
  const totalViews = report?.views ?? 0;

  return (
    <div className="hs-drawer-body">
      <section className="hs-block">
        <div className="hs-range">
          {([7, 14, 30] as Preset[]).map((days) => (
            <button
              className={preset === days ? "hs-chip on" : "hs-chip"}
              key={days}
              onClick={() => choosePreset(days)}
              type="button"
            >
              {days} 天
            </button>
          ))}
          <span className="hs-muted">自选</span>
          <input
            aria-label="开始日期"
            max={anchor}
            onChange={(event) => {
              setPreset(null);
              setFrom(event.target.value);
            }}
            type="date"
            value={from}
          />
          <span className="hs-muted">→</span>
          <input
            aria-label="结束日期"
            max={anchor}
            onChange={(event) => {
              setPreset(null);
              setTo(event.target.value);
            }}
            type="date"
            value={to}
          />
        </div>
        <div className="hs-block-head">
          <span>
            {from} → {to} · {spanDays > 0 ? `${spanDays} 天` : "—"}
          </span>
          <span className="hs-muted">
            {loading ? "加载中…" : report ? `访客 ${report.visitors} · 浏览 ${report.views}` : ""}
          </span>
        </div>
        {error ? <div className="hs-alert">{error}</div> : null}
        <TrafficBars days={days} height={170} highlightLast={to === anchor} />
        <p className="hs-muted">深色柱 = 访客，浅色柱 = 浏览。日期按站点时区分日，与 WordPress 后台一致。</p>
      </section>
      <div className="hs-two">
        <section className="hs-block">
          <div className="hs-block-head"><span>流量来源</span></div>
          <Table labelKey="name" rows={report?.referrers ?? []} total={totalViews} />
          <p className="hs-muted">Jetpack 只分「搜索引擎 / 来源站 / 直接」。要拆自然、付费、社交，等 GA4 授权后接。</p>
        </section>
        <section className="hs-block">
          <div className="hs-block-head"><span>国家 / 地区</span></div>
          <Table labelKey="name" rows={report?.countries ?? []} total={totalViews} />
        </section>
      </div>
      <section className="hs-block">
        <div className="hs-block-head"><span>热门页面</span></div>
        <Table labelKey="title" rows={report?.top_posts ?? []} />
      </section>
      <div className="hs-two">
        <section className="hs-block">
          <div className="hs-block-head"><span>搜索词</span></div>
          <Table labelKey="term" rows={report?.search_terms ?? []} />
          <p className="hs-muted">
            搜索引擎已加密 {report?.encrypted_search_terms ?? 0} 条搜索词，Jetpack 只报未加密的。
          </p>
        </section>
        <section className="hs-block">
          <div className="hs-block-head"><span>点出的外链</span></div>
          <Table labelKey="name" rows={report?.clicks ?? []} />
        </section>
      </div>
    </div>
  );
}
