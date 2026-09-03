"use client";

import { useCallback, useEffect, useState } from "react";

import styles from "./Prospects.module.css";
import {
  type Prospect,
  type ProspectList,
  type ProspectQuery,
  type ProspectStatus,
  type SweepResult,
  getProspectQueries,
  getProspects,
  getQuota,
  reviewProspect,
  runSweep,
  screenProspects,
  seedProspectConfig,
} from "./api";

const COUNTRY_LABELS: Record<string, string> = {
  US: "美国",
  CA: "加拿大",
  MX: "墨西哥",
};

const VERDICT_LABELS: Record<string, string> = {
  fit: "✅ 推荐发",
  unfit: "❌ 别发",
  unsure: "❓ 判不准",
};

const REJECT_REASONS = [
  "不是目标店型",
  "已停业 / 网站打不开",
  "是连锁大店，走不通",
  "没有联系方式",
  "其他",
];


function describeReason(reason: unknown) {
  if (reason instanceof Error) {
    return reason.message;
  }
  return String(reason);
}
export function ProspectWorkspace() {
  const [data, setData] = useState<ProspectList | null>(null);
  const [queries, setQueries] = useState<ProspectQuery[]>([]);
  const [quota, setQuota] = useState<SweepResult | null>(null);
  const [statusFilter, setStatusFilter] = useState<ProspectStatus | "">("new");
  const [countryFilter, setCountryFilter] = useState("");
  const [storeTypeFilter, setStoreTypeFilter] = useState("");
  // 默认只看机器推荐发的——用户读结论，不看原始数据。
  const [verdictFilter, setVerdictFilter] = useState("");
  const [sweepCount, setSweepCount] = useState(20);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // allSettled 而不是 all：三份数据互相独立，取到哪份就渲染哪份。
      // 2026-08-31 体检：候选客户接口 403 时，Promise.all 整体 reject，
      // 于是模板和额度这两份**已经成功取到**的数据被一起丢掉，页面显示
      // 「还没有查询模板」——而实际有 14 条。用户照着提示点「灌入默认模板」
      // 就会重复灌一遍种子数据。一个请求的失败不该抹掉另一个请求的成功。
      const [listResult, queryResult, quotaResult] = await Promise.allSettled([
        getProspects({
          status: statusFilter,
          country: countryFilter,
          storeType: storeTypeFilter,
          verdict: verdictFilter,
        }),
        getProspectQueries(),
        getQuota(),
      ]);

      if (listResult.status === "fulfilled") {
        setData(listResult.value);
      }
      if (queryResult.status === "fulfilled") {
        setQueries(queryResult.value);
      }
      if (quotaResult.status === "fulfilled") {
        setQuota(quotaResult.value);
      }

      // 只报真正失败的那几份，并说清楚是哪一份 —— 而不是把整页打成空白。
      const failures: string[] = [];
      if (listResult.status === "rejected") {
        failures.push(`候选客户：${describeReason(listResult.reason)}`);
      }
      if (queryResult.status === "rejected") {
        failures.push(`查询模板：${describeReason(queryResult.reason)}`);
      }
      if (quotaResult.status === "rejected") {
        failures.push(`今日额度：${describeReason(quotaResult.reason)}`);
      }
      setError(failures.length > 0 ? failures.join("；") : null);
    } finally {
      setLoading(false);
    }
  }, [countryFilter, statusFilter, storeTypeFilter, verdictFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const withBusy = async (fn: () => Promise<string>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setNotice(await fn());
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const doSeed = () =>
    withBusy(async () => {
      const result = await seedProspectConfig();
      return `已灌入 ${result.queries_added} 条查询模板、${result.cities_added} 个城市。`;
    });

  const doSweep = () =>
    withBusy(async () => {
      const result = await runSweep({
        max_queries: sweepCount,
        country: countryFilter || undefined,
        store_type: storeTypeFilter || undefined,
      });
      const stopped = result.quota_stopped ? "（额度用完，已暂停）" : "";
      return (
        `跑了 ${result.queries_executed} 次查询，看到 ${result.places_seen} 家店，` +
        `新增 ${result.prospects_created} 家${stopped}`
      );
    });

  const doScreen = () =>
    withBusy(async () => {
      const result = await screenProspects({
        limit: 20,
        store_type: storeTypeFilter || undefined,
      });
      if (result.message) return result.message;
      const stopped = result.quota_stopped ? "（额度用完，已暂停）" : "";
      return (
        `筛了 ${result.screened} 家：推荐发 ${result.fit}，别发 ${result.unfit}，` +
        `判不准 ${result.unsure}${stopped}`
      );
    });

  const doReview = (prospect: Prospect, approve: boolean, reason?: string) =>
    withBusy(async () => {
      await reviewProspect(prospect.id, {
        approve,
        reject_reason: approve ? undefined : reason,
      });
      return approve
        ? `已通过：${prospect.store_name}`
        : `已拒绝：${prospect.store_name}`;
    });

  const storeTypes = Array.from(
    new Map(queries.map((q) => [q.store_type, q.store_type_label])).entries(),
  );
  const quotaPercent = quota?.quota_budget
    ? Math.min(100, (quota.quota_used_today / quota.quota_budget) * 100)
    : 0;

  return (
    <div className={styles.workspace}>
      <section className={styles.summaryRow}>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>待审核</span>
          <strong className={styles.valueNew}>{data?.new_count ?? "—"}</strong>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>已通过</span>
          <strong className={styles.valueOk}>
            {data?.approved_count ?? "—"}
          </strong>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>已拒绝</span>
          <strong className={styles.valueMuted}>
            {data?.rejected_count ?? "—"}
          </strong>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>
            今日额度 {quota?.quota_used_today ?? 0} / {quota?.quota_budget ?? 0}
          </span>
          <span className={styles.quotaBarWrap}>
            <span
              className={styles.quotaBar}
              data-hot={quotaPercent > 80}
              style={{ width: `${quotaPercent}%` }}
            />
          </span>
        </div>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <h2>抓取</h2>
          <p className={styles.hint}>
            按「查询模板 × 城市」跑。跑过的组合永不重复跑，可以随时点、随时停。
            城市按<strong>小城八成、大城两成</strong>混着跑——大城市的店天天被人
            开发（抓回来全是连锁），小镇店铺几乎没人找过；大城市一个不漏，
            只是排在后面。
          </p>
          <div className={styles.toolbar}>
            <select
              className={styles.select}
              onChange={(event) => setCountryFilter(event.target.value)}
              value={countryFilter}
            >
              <option value="">全部国家</option>
              <option value="US">美国</option>
              <option value="CA">加拿大</option>
              <option value="MX">墨西哥</option>
            </select>
            <select
              className={styles.select}
              onChange={(event) => setStoreTypeFilter(event.target.value)}
              value={storeTypeFilter}
            >
              <option value="">全部店型</option>
              {storeTypes.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            <label className={styles.numLabel}>
              本次跑
              <input
                className={styles.numInput}
                inputMode="numeric"
                onChange={(event) =>
                  setSweepCount(Math.max(1, Number(event.target.value) || 1))
                }
                value={sweepCount}
              />
              次
            </label>
            <button
              className={styles.primaryButton}
              disabled={busy || !queries.length}
              onClick={() => void doSweep()}
              type="button"
            >
              {busy ? "跑批中…" : "开始抓取"}
            </button>
            {queries.length === 0 ? (
              <button
                className={styles.ghostButton}
                disabled={busy}
                onClick={() => void doSeed()}
                type="button"
              >
                灌入默认模板和城市
              </button>
            ) : null}
          </div>
        </header>
        {error ? <p className={styles.error}>{error}</p> : null}
        {notice ? <p className={styles.notice}>{notice}</p> : null}
        {queries.length === 0 ? (
          <p className={styles.empty}>
            还没有查询模板。点上面那个按钮灌入默认的（14 条模板 / 68 个城市，
            墨西哥用西班牙语词）。
          </p>
        ) : (
          <p className={styles.queryCount}>
            已启用 {queries.filter((q) => q.active).length} 条查询模板
          </p>
        )}
      </section>

      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <h2>候选客户</h2>
          <p className={styles.hint}>
            点「自动筛选」让机器去读每家店的官网，判断它到底卖不卖货、是不是
            独立店，然后写<strong>一句人话</strong>给你。你只读那句话就行，
            不用自己点开地图逐家看。
          </p>
          <div className={styles.toolbar}>
            <select
              className={styles.select}
              onChange={(event) =>
                setStatusFilter(event.target.value as ProspectStatus | "")
              }
              value={statusFilter}
            >
              <option value="new">待审核</option>
              <option value="approved">已通过</option>
              <option value="rejected">已拒绝</option>
              <option value="">全部</option>
            </select>
            <select
              className={styles.select}
              onChange={(event) => setVerdictFilter(event.target.value)}
              value={verdictFilter}
            >
              <option value="">全部结论</option>
              <option value="fit">✅ 只看推荐发的</option>
              <option value="unsure">❓ 判不准的</option>
              <option value="unfit">❌ 别发的</option>
            </select>
            <button
              className={styles.primaryButton}
              disabled={busy}
              onClick={() => void doScreen()}
              type="button"
            >
              {busy ? "筛选中…" : "自动筛选 20 家"}
            </button>
          </div>
        </header>

        {loading ? (
          <p className={styles.empty}>加载中…</p>
        ) : !data?.items.length ? (
          <p className={styles.empty}>
            这个筛选下没有客户。先在上面跑一次抓取。
          </p>
        ) : (
          <ul className={styles.cardList}>
            {data.items.map((prospect) => (
              <li className={styles.card} key={prospect.id}>
                <div className={styles.cardMain}>
                  <div className={styles.cardTop}>
                    <strong className={styles.storeName}>
                      {prospect.store_name}
                    </strong>
                    <span className={styles.place}>
                      {[prospect.city, prospect.region].filter(Boolean).join(", ")}
                      {" · "}
                      {COUNTRY_LABELS[prospect.country] ?? prospect.country}
                    </span>
                  </div>
                  <div className={styles.cardMeta}>
                    {prospect.website ? (
                      <a
                        className={styles.link}
                        href={prospect.website}
                        rel="noreferrer noopener"
                        target="_blank"
                      >
                        {prospect.website.replace(/^https?:\/\//, "")}
                      </a>
                    ) : (
                      <span className={styles.muted}>无网站</span>
                    )}
                    {prospect.phone ? <span>{prospect.phone}</span> : null}
                    {prospect.rating ? (
                      <span>
                        ★ {prospect.rating}
                        {prospect.reviews_count
                          ? `（${prospect.reviews_count}）`
                          : ""}
                      </span>
                    ) : null}
                  </div>
                  <div className={styles.cardMeta}>
                    {prospect.place_category ? (
                      <span className={styles.tag}>
                        {prospect.place_category}
                      </span>
                    ) : (
                      <span className={styles.tag}>{prospect.store_type}</span>
                    )}
                    <span className={styles.muted}>
                      来源词：{prospect.source_query ?? "—"}
                    </span>
                    {prospect.email ? (
                      <span className={styles.emailOk}>{prospect.email}</span>
                    ) : (
                      <span className={styles.muted}>邮箱审核后补</span>
                    )}
                  </div>
                  {prospect.screen_verdict ? (
                    <div
                      className={styles.screenBox}
                      data-verdict={prospect.screen_verdict}
                    >
                      <strong className={styles.verdictTag}>
                        {VERDICT_LABELS[prospect.screen_verdict] ??
                          prospect.screen_verdict}
                      </strong>
                      <span className={styles.screenReason}>
                        {prospect.screen_reason}
                      </span>
                    </div>
                  ) : null}
                  {prospect.chain_hint ? (
                    <span className={styles.chainHint}>
                      ⚠ {prospect.chain_hint}
                    </span>
                  ) : null}
                  {prospect.maps_url ? (
                    <a
                      className={styles.mapsLink}
                      href={prospect.maps_url}
                      rel="noreferrer noopener"
                      target="_blank"
                    >
                      🗺 在地图上看这家店（能看到店面照片和官网）
                    </a>
                  ) : null}
                  {prospect.reject_reason ? (
                    <span className={styles.rejectReason}>
                      拒绝原因：{prospect.reject_reason}
                    </span>
                  ) : null}
                </div>
                {prospect.status === "new" ? (
                  <div className={styles.cardActions}>
                    <button
                      className={styles.approveButton}
                      disabled={busy}
                      onClick={() => void doReview(prospect, true)}
                      type="button"
                    >
                      通过
                    </button>
                    <select
                      className={styles.rejectSelect}
                      defaultValue=""
                      disabled={busy}
                      onChange={(event) => {
                        if (!event.target.value) return;
                        void doReview(prospect, false, event.target.value);
                        event.target.value = "";
                      }}
                    >
                      <option value="">拒绝…</option>
                      {REJECT_REASONS.map((reason) => (
                        <option key={reason} value={reason}>
                          {reason}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <span className={styles.statusTag} data-status={prospect.status}>
                    {prospect.status === "approved" ? "已通过" : "已拒绝"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
