"use client";

import { useCallback, useEffect, useState } from "react";

import styles from "./AmzWorkspace.module.css";
import { getPortfolio, getStores, getStoreInventory, setSolicitations, type AmzPortfolio, type AmzStore, type AmzStoreInventory } from "./api";

function usd(value: number) {
  return `$${value.toFixed(0)}`;
}

/**
 * 跨店协调(殷素素):三家店卖同一款货——
 * 1. 同一个词谁主打:按「每花一块钱卖回多少」分主场,明显更差的店让位(建议在总览里放行 / 驳回);
 * 2. 同一批货的需求合起来看:各店 28 天销量 → 合计日均 → 合计库存能撑几天 → 该补多少(只给人看,系统不下单);
 * 3. 各店库存能撑几天 + 请求留评开关(影子期默认关,只有老板能开)。
 */
export function PortfolioPanel() {
  const [market, setMarket] = useState("US");
  const [data, setData] = useState<AmzPortfolio | null>(null);
  const [stores, setStores] = useState<AmzStore[]>([]);
  const [isOwner, setIsOwner] = useState(false);
  const [inventory, setInventory] = useState<Record<string, AmzStoreInventory>>({});
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [portfolio, storeList] = await Promise.all([getPortfolio(market), getStores()]);
      setData(portfolio);
      const mine = storeList.items.filter((s) => s.country === market);
      setStores(mine);
      setIsOwner(storeList.is_owner);
      const pairs = await Promise.all(mine.map(async (s) => [s.store_code, await getStoreInventory(s.store_code)] as const));
      setInventory(Object.fromEntries(pairs));
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, [market]);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggle(storeCode: string, enabled: boolean) {
    const ok = enabled ? window.confirm(`打开 ${storeCode} 的请求留评?系统会对发货 5–30 天、亚马逊说可以请求的订单点官方「Request a Review」。`) : true;
    if (!ok) return;
    try {
      await setSolicitations(storeCode, enabled);
      setStatus(`${storeCode} 请求留评已${enabled ? "打开" : "关闭"}`);
      await load();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }

  const codes = stores.map((s) => s.store_code);

  return (
    <div className={styles.workspace}>
      {status ? <div className={styles.muted} style={{ padding: "6px 2px" }}>{status}</div> : null}
      <div className={styles.sheetActions}>
        {["US", "DE"].map((m) => (
          <button className={m === market ? styles.button : styles.linkButton} key={m} onClick={() => setMarket(m)} type="button">
            {m === "US" ? "美国站" : "德国站"}
          </button>
        ))}
      </div>

      <section className={styles.panel} aria-label="主场词">
        <div className={styles.panelHead}>
          <h2>主场词 · 谁来主打</h2>
          <span className={styles.muted}>最近 28 天、≥2 家店都买的词;按每花一块钱卖回多少分主场,不到主场七成的店该让位 · 让位建议在总览里放行</span>
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>搜索词</th>
                <th>主场</th>
                <th>该让</th>
                {codes.map((c) => (
                  <th key={c}>{c} 点击 / 单 / 花 / 卖</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data?.owners ?? []).map((row) => (
                <tr key={row.term}>
                  <td>{row.term}</td>
                  <td>{row.home_store ? <b className={styles.good}>{row.home_store}</b> : <span className={styles.muted}>还分不出</span>}</td>
                  <td>{row.yield_stores.length ? <span className={styles.warn}>{row.yield_stores.join("、")}</span> : "—"}</td>
                  {codes.map((c) => {
                    const v = row.stores[c];
                    return <td key={c}>{v ? `${v.clicks} / ${v.orders} / ${usd(v.spend)} / ${usd(v.sales)}` : "—"}</td>;
                  })}
                </tr>
              ))}
              {data && data.owners.length === 0 ? (
                <tr>
                  <td className={styles.muted} colSpan={3 + codes.length}>
                    这个站点最近没有被几家店同时争的词
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className={styles.panel} aria-label="同批货需求">
        <div className={styles.panelHead}>
          <h2>同批货需求 · 合起来看</h2>
          <span className={styles.muted}>
            各店 28 天销量相加;生产 + 头程按 {data?.lead_days_default ?? 40} 天估,再加 {data?.safety_days ?? 45} 天安全库存 · 排产只给人看,系统不下单
          </span>
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>产品线</th>
                <th>28 天销量(各店)</th>
                <th>合计日均</th>
                <th>合计库存(可售 + 在途)</th>
                <th>能撑</th>
                <th>建议补</th>
              </tr>
            </thead>
            <tbody>
              {(data?.demand ?? []).map((row) => (
                <tr key={row.product_line}>
                  <td>{row.label}</td>
                  <td>
                    {row.units_28d_total}
                    <div className={styles.muted}>{Object.entries(row.units_28d).map(([s, n]) => `${s} ${n}`).join(" · ")}</div>
                  </td>
                  <td>{row.daily}</td>
                  <td>
                    {Object.keys(row.stock).length ? Object.entries(row.stock).map(([s, v]) => `${s} ${v.fulfillable}+${v.inbound}`).join(" · ") : "—"}
                    {row.stock_missing_stores.length ? <div className={styles.muted}>缺库存数据:{row.stock_missing_stores.join("、")}</div> : null}
                  </td>
                  <td className={row.days_cover != null && row.days_cover < 21 ? styles.bad : undefined}>{row.days_cover != null ? `${row.days_cover} 天` : "—"}</td>
                  <td>
                    {row.reorder_units != null ? `${row.reorder_units} 件` : "—"}
                    {row.note ? <div className={styles.muted}>{row.note}</div> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {stores.map((store) => {
        const inv = inventory[store.store_code];
        return (
          <section className={styles.panel} aria-label={`${store.store_code} 库存`} key={store.store_code}>
            <div className={styles.panelHead}>
              <h2>
                {store.display_name} <code>{store.store_code}</code> · 库存能撑几天
              </h2>
              <span className={styles.muted}>
                {inv?.items.length ? `快照 ${inv.items[0].snap_date}` : "还没有库存数据(这家店没接 SP-API)"} · 请求留评:
                {inv?.solicitations.enabled ? " 已打开" : " 影子期,只查不发"}
                {inv && Object.keys(inv.solicitations.counts).length ? `(${Object.entries(inv.solicitations.counts).map(([k, v]) => `${k} ${v}`).join(" · ")})` : ""}
              </span>
            </div>
            {inv?.items.length ? (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>SKU</th>
                      <th>可售</th>
                      <th>在途</th>
                      <th>日均</th>
                      <th>能撑</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inv.items.map((item) => (
                      <tr key={item.sku}>
                        <td>
                          <code>{item.sku}</code>
                        </td>
                        <td className={item.fulfillable === 0 && item.daily_rate > 0 ? styles.bad : undefined}>{item.fulfillable}</td>
                        <td>{item.inbound}</td>
                        <td>{item.daily_rate}</td>
                        <td className={item.days_cover != null && item.days_cover < 7 ? styles.bad : item.days_cover != null && item.days_cover < 21 ? styles.warn : undefined}>
                          {item.days_cover != null ? `${item.days_cover} 天` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {isOwner && inv?.items.length ? (
              <div className={styles.sheetActions}>
                <button className={styles.linkButton} onClick={() => void toggle(store.store_code, !inv.solicitations.enabled)} type="button">
                  {inv.solicitations.enabled ? "关掉请求留评" : "打开请求留评(亚马逊官方按钮)"}
                </button>
              </div>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
