"use client";

import { useCallback, useEffect, useState } from "react";

import { type WholesaleItem, getWholesaleItems } from "../wholesale/api";
import styles from "./Widget.module.css";
import {
  type WholesaleSiteStatus,
  type WidgetJob,
  getWholesaleSiteStatus,
  getWidgetJobs,
  publishWholesaleSite,
  pushWidgets,
} from "./api";

const JOB_STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  dispatched: "推送中",
  success: "成功",
  failed: "失败",
};

/**
 * 小窗在不在线上，完全由批发记录推导出来，不另存一份状态：
 * 填全批发信息（ready）+ 已上过 Woo = 线上有小窗。
 */
type WidgetState = "live" | "missing_price" | "not_uploaded";

function widgetState(item: WholesaleItem): WidgetState {
  if (!item.woo_product_id) return "not_uploaded";
  return item.status === "ready" ? "live" : "missing_price";
}

export function WidgetWorkspace() {
  const [items, setItems] = useState<WholesaleItem[]>([]);
  const [jobs, setJobs] = useState<WidgetJob[]>([]);
  const [site, setSite] = useState<WholesaleSiteStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, jobList, siteStatus] = await Promise.all([
        getWholesaleItems(),
        getWidgetJobs(),
        getWholesaleSiteStatus(),
      ]);
      setItems(list.items);
      setJobs(jobList);
      setSite(siteStatus);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const doPush = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await pushWidgets();
      setNotice(
        `已派单 ${result.targets} 个产品（任务 ${result.job_id.slice(0, 8)}）。` +
          "n8n 跑完后下面的记录会变成「成功」。",
      );
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const doPublishSite = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await publishWholesaleSite();
      setNotice(
        `已生成 /wholesale/ 主页和 ${result.groups} 个店型子页。` +
          (result.main_link ? ` 打开：${result.main_link}` : ""),
      );
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const live = items.filter((item) => widgetState(item) === "live");
  const missingPrice = items.filter(
    (item) => widgetState(item) === "missing_price",
  );
  const notUploaded = items.filter(
    (item) => widgetState(item) === "not_uploaded",
  );

  return (
    <div className={styles.workspace}>
      <section className={styles.explainer}>
        <h2>产品页批发小窗</h2>
        <p>
          买家在产品页上看到的<strong>「Wholesale - buying for a store?」</strong>
          入口。冷开发是我们去敲别人门，这个是<strong>别人已经站在店里了</strong>
          ——热线索。
        </p>
        <p>
          <strong>你平时什么都不用点。</strong>在「批发目录」里填完批发价，
          小窗自动出现；清空批发价，小窗自动消失。
        </p>
        <p className={styles.gate}>
          ⚠ 小窗上<strong>绝不显示批发价</strong>，只显示起订量/装箱数/交期和
          三条政策，价格要对方留资来问。这既挡住了 GMC 的「页面价与 feed 价
          不符」，也让零售商看不到你的成本。
        </p>
      </section>

      <section className={styles.summaryRow}>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>线上有小窗</span>
          <strong className={styles.valueOk}>{live.length}</strong>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>缺批发价（不显示）</span>
          <strong className={styles.valueWarn}>{missingPrice.length}</strong>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>还没上过 Woo</span>
          <strong className={styles.valueMuted}>{notUploaded.length}</strong>
        </div>
      </section>

      {error ? <p className={styles.error}>{error}</p> : null}
      {notice ? <p className={styles.notice}>{notice}</p> : null}

      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <h3>全量重推</h3>
          <p className={styles.hint}>
            <strong>只有改了政策文案时才需要点这个</strong>
            （比如免运费门槛从 $500 改成 $800）。每个产品的起订量/交期在你保存
            批发信息时就自动推过去了，不用手动。
          </p>
        </header>
        <button
          className={styles.primaryButton}
          disabled={busy || loading}
          onClick={() => void doPush()}
          type="button"
        >
          {busy ? "派单中…" : "重推全部产品"}
        </button>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <h3>批发主页 /wholesale/</h3>
          <p className={styles.hint}>
            店家搜「wholesale 供应商」落到的<strong>主入口</strong>——浮窗只接住
            已经点进某个产品的人。页面<strong>列店型不列产品</strong>：产品从 6 个
            涨到 300 个，卡片还是这几张，只有数字变大。
            填了批发价的产品会自动进对应店型的子页。
          </p>
        </header>
        {site?.store_types?.length ? (
          <ul className={styles.itemList}>
            {site.store_types.map((entry) => (
              <li className={styles.item} key={entry.key}>
                <span className={styles.name}>{entry.label}</span>
                <span className={styles.sku}>
                  {entry.count} 个品
                  {entry.guides ? ` · ${entry.guides} 篇指南` : ""}
                </span>
                <span className={styles.stateTag} data-state={entry.page_id ? "live" : "missing_price"}>
                  {entry.page_id ? `✅ ${entry.url}` : "未生成"}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.empty}>
            还没有店型有可上架的货——先在「批发目录」里填批发价。
          </p>
        )}
        <p className={styles.hint}>
          {site?.last_published_at
            ? `上次生成：${new Date(site.last_published_at).toLocaleString("zh-CN")}`
            : "还没生成过。"}
          {site?.guide_categories_mapped
            ? ` · ${site.guide_categories_mapped} 个类目的指南文章会回链批发页`
            : ""}
        </p>
        <button
          className={styles.primaryButton}
          disabled={busy || loading}
          onClick={() => void doPublishSite()}
          type="button"
        >
          {busy ? "生成中…" : "重新生成批发主页"}
        </button>
      </section>

      <section className={styles.panel}>
        <h3>产品状态（{items.length}）</h3>
        {loading ? (
          <p className={styles.empty}>加载中…</p>
        ) : !items.length ? (
          <p className={styles.empty}>批发目录里还没有产品。</p>
        ) : (
          <ul className={styles.itemList}>
            {items.map((item) => {
              const state = widgetState(item);
              return (
                <li className={styles.item} key={item.id}>
                  <span className={styles.sku}>{item.sku}</span>
                  <span className={styles.name}>{item.product_name}</span>
                  <span className={styles.stateTag} data-state={state}>
                    {state === "live"
                      ? "✅ 线上有小窗"
                      : state === "missing_price"
                        ? "⚠ 缺批发价"
                        : "— 没上过 Woo"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className={styles.panel}>
        <h3>推送记录</h3>
        {!jobs.length ? (
          <p className={styles.empty}>还没有推送记录。</p>
        ) : (
          <ul className={styles.jobList}>
            {jobs.map((job) => (
              <li className={styles.job} key={job.job_id}>
                <span className={styles.jobStatus} data-status={job.status}>
                  {JOB_STATUS_LABELS[job.status] ?? job.status}
                </span>
                <span className={styles.jobMeta}>
                  {job.targets} 个产品
                  {job.created_at
                    ? ` · ${new Date(job.created_at).toLocaleString("zh-CN")}`
                    : ""}
                </span>
                {job.error ? (
                  <span className={styles.jobError}>{job.error}</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
