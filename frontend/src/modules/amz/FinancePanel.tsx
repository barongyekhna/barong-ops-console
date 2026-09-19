"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import styles from "./AmzWorkspace.module.css";
import { getCosts, getFinanceReport, getStores, saveCost, type AmzCostItem, type AmzStore, type AmzStorePnl } from "./api";

function usd(value: number | null | undefined) {
  if (value == null) return "—";
  const sign = value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
}

/**
 * 殷乐乐的账:每家店近 30 天(按这家店交易数据的最后一天)每天赚了还是亏了。
 * 成本只用下面成本表里人手填的;缺成本的那几天标「不完整」;广告报表没覆盖的日子标「广告费待接入」——都不估。
 */
export function FinancePanel({ companyOrgId = null }: { companyOrgId?: string | null }) {
  const [stores, setStores] = useState<AmzStore[]>([]);
  const [store, setStore] = useState<string | null>(null);
  const [report, setReport] = useState<AmzStorePnl | null>(null);
  const [costs, setCosts] = useState<AmzCostItem[]>([]);
  const [defaultFrom, setDefaultFrom] = useState<string>("");
  const [drafts, setDrafts] = useState<Record<string, { factory: string; freight: string; from: string }>>({});
  const [openHistory, setOpenHistory] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getStores()
      .then((r) => {
        const list = companyOrgId ? r.items.filter((s) => s.company_org_id === companyOrgId) : r.items;
        setStores(list);
        setStore((prev) => (prev && list.some((s) => s.store_code === prev) ? prev : list[0]?.store_code ?? null));
      })
      .catch((err) => setStatus(err instanceof Error ? err.message : String(err)));
  }, [companyOrgId]);

  const load = useCallback(async () => {
    if (!store) return;
    try {
      const [rep, cost] = await Promise.all([getFinanceReport({ store, days: 30 }), getCosts(store)]);
      setReport(rep.items[0] ?? null);
      setCosts(cost.items);
      setDefaultFrom(cost.default_effective_from ?? "");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, [store]);

  useEffect(() => {
    void load();
  }, [load]);

  const missing = useMemo(() => costs.filter((c) => !c.cost && c.units_30d > 0), [costs]);

  async function save(item: AmzCostItem) {
    if (!store) return;
    const d = drafts[item.sku] ?? { factory: "", freight: "", from: "" };
    const factory = Number(d.factory);
    const freight = Number(d.freight);
    const from = d.from || (item.cost ? new Date().toISOString().slice(0, 10) : defaultFrom);
    if (!(factory > 0) || !(freight >= 0) || !from) {
      setStatus("出厂价要大于 0、头程不能为负,生效日期要填");
      return;
    }
    setBusy(true);
    try {
      const out = await saveCost({ store_code: store, sku: item.sku, factory_cny: factory, freight_cny: freight, effective_from: from });
      setCosts(out.items);
      setDrafts((prev) => ({ ...prev, [item.sku]: { factory: "", freight: "", from: "" } }));
      setStatus(`${item.sku} 的成本已保存,账马上按新成本重算`);
      const rep = await getFinanceReport({ store, days: 30 });
      setReport(rep.items[0] ?? null);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const totals = report?.totals ?? null;

  return (
    <div className={styles.workspace}>
      <div className={styles.sheetActions}>
        {stores.map((s) => (
          <button className={s.store_code === store ? styles.button : styles.linkButton} key={s.store_code} onClick={() => setStore(s.store_code)} type="button">
            {s.store_code}
          </button>
        ))}
      </div>
      {status ? <div className={styles.muted}>{status}</div> : null}

      <section className={styles.panel} aria-label="利润">
        <div className={styles.panelHead}>
          <h2>殷乐乐的账 · {store ?? ""}</h2>
          <span className={styles.muted}>
            {report?.until ? `${report.since} → ${report.until}(这家店交易数据截至 ${report.until})` : "这家店还没有交易数据"}
            {report?.last_ads ? ` · 广告费截至 ${report.last_ads}` : " · 还没有广告费数据"}
          </span>
        </div>
        {totals ? (
          <div className={styles.sheetRow}>
            <div>
              近 30 天利润
              <div className={totals.profit < 0 ? styles.bad : styles.good} style={{ fontSize: 22, fontWeight: 700 }}>
                {usd(totals.profit)}
              </div>
              <div className={styles.muted}>{totals.complete ? "账是完整的" : "不完整:" + [totals.missing_cost_units ? `${totals.missing_cost_units} 件缺成本` : "", totals.ads_missing ? "有日子缺广告费" : ""].filter(Boolean).join(" · ")}</div>
            </div>
            <div>
              销售额 <div>{usd(totals.sales)}</div>
            </div>
            <div>
              亚马逊费用 + 退款 <div>{usd(totals.fees + totals.refunds)}</div>
            </div>
            <div>
              其他费用(含摊) <div>{usd(totals.other + totals.accrued)}</div>
            </div>
            <div>
              商品成本 <div>{usd(-totals.cogs)}</div>
            </div>
            <div>
              广告费 <div>{usd(-totals.ads)}</div>
            </div>
          </div>
        ) : null}
        {missing.length ? (
          <div className={styles.warn} style={{ padding: "6px 2px" }}>
            {missing.length} 个近 30 天有销量的 SKU 还没填成本,账算不完整——在下面的成本表里填。
          </div>
        ) : null}
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>日期</th>
                <th>件数</th>
                <th>销售额</th>
                <th>亚马逊费用</th>
                <th>退款</th>
                <th>其他(含摊)</th>
                <th>成本</th>
                <th>广告</th>
                <th>利润</th>
              </tr>
            </thead>
            <tbody>
              {[...(report?.days ?? [])].reverse().map((d) => (
                <tr key={d.date}>
                  <td className={styles.muted}>{d.date.slice(5)}</td>
                  <td>{d.units}</td>
                  <td>{usd(d.sales)}</td>
                  <td>{usd(d.fees)}</td>
                  <td>{usd(d.refunds)}</td>
                  <td>{usd(d.other + d.accrued)}</td>
                  <td>{usd(-d.cogs)}</td>
                  <td>{d.ads_missing ? <span className={styles.muted}>待接入</span> : usd(-d.ads)}</td>
                  <td className={d.profit < 0 ? styles.bad : undefined}>
                    {usd(d.profit)}
                    {!d.complete ? <div className={styles.muted}>{d.missing_cost_units ? `缺成本 ${d.missing_cost_units} 件` : "广告费待接入"}</div> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className={styles.panel} aria-label="按产品线">
        <div className={styles.panelHead}>
          <h2>按产品线 · 广告账</h2>
          <span className={styles.muted}>广告盈亏 = 广告带来的销售 × 这条线的毛利率 − 广告花费;缺成本的线不下结论</span>
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>产品线</th>
                <th>件数</th>
                <th>销售额</th>
                <th>扣广告前毛利</th>
                <th>广告花费</th>
                <th>扣完广告</th>
                <th>广告自己的账</th>
              </tr>
            </thead>
            <tbody>
              {(report?.lines ?? []).map((l) => (
                <tr key={l.product_line}>
                  <td>{l.label}</td>
                  <td>{l.units}</td>
                  <td>{usd(l.sales)}</td>
                  <td>{l.gross_before_ads == null ? <span className={styles.muted}>缺成本</span> : `${usd(l.gross_before_ads)}(${l.margin_pct}%)`}</td>
                  <td>{usd(l.ad_spend)}</td>
                  <td className={l.profit_after_ads != null && l.profit_after_ads < 0 ? styles.bad : undefined}>{usd(l.profit_after_ads)}</td>
                  <td className={l.ad_pnl != null && l.ad_pnl < 0 ? styles.bad : undefined}>{usd(l.ad_pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className={styles.panel} aria-label="成本表">
        <div className={styles.panelHead}>
          <h2>成本表 · {store ?? ""}</h2>
          <span className={styles.muted}>出厂价 + 头程(元 / 件)。成本变了就填新的一行(新的生效日期),旧的留着——历史的账用当时的成本。第一次填默认从这家店最早的数据日生效。</span>
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>SKU</th>
                <th>近 30 天</th>
                <th>现在的成本</th>
                <th>出厂价(元)</th>
                <th>头程(元)</th>
                <th>生效日期</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {costs.map((c) => {
                const d = drafts[c.sku] ?? { factory: "", freight: "", from: "" };
                return (
                  <tr key={c.sku}>
                    <td>
                      <code>{c.sku}</code>
                      {c.title ? <div className={styles.muted}>{c.title.slice(0, 40)}</div> : null}
                    </td>
                    <td>
                      {c.units_30d} 件{c.in_stock ? <div className={styles.muted}>有库存</div> : null}
                    </td>
                    <td>
                      {c.cost ? (
                        <>
                          ¥{c.cost.factory_cny} + ¥{c.cost.freight_cny}
                          <div className={styles.muted}>
                            {c.cost.effective_from} 起
                            {c.history.length > 1 ? (
                              <button className={styles.linkButton} onClick={() => setOpenHistory(openHistory === c.sku ? null : c.sku)} type="button">
                                历史 {c.history.length}
                              </button>
                            ) : null}
                          </div>
                          {openHistory === c.sku ? (
                            <div className={styles.muted}>
                              {c.history.map((h) => `${h.effective_from}:¥${h.factory_cny} + ¥${h.freight_cny}`).join(" · ")}
                            </div>
                          ) : null}
                        </>
                      ) : (
                        <span className={c.units_30d > 0 ? styles.bad : styles.muted}>没填</span>
                      )}
                    </td>
                    <td>
                      <input inputMode="decimal" onChange={(e) => setDrafts((prev) => ({ ...prev, [c.sku]: { ...d, factory: e.target.value } }))} placeholder={c.cost ? String(c.cost.factory_cny) : ""} value={d.factory} />
                    </td>
                    <td>
                      <input inputMode="decimal" onChange={(e) => setDrafts((prev) => ({ ...prev, [c.sku]: { ...d, freight: e.target.value } }))} placeholder={c.cost ? String(c.cost.freight_cny) : ""} value={d.freight} />
                    </td>
                    <td>
                      <input onChange={(e) => setDrafts((prev) => ({ ...prev, [c.sku]: { ...d, from: e.target.value } }))} type="date" value={d.from || (c.cost ? "" : defaultFrom)} />
                    </td>
                    <td>
                      <button className={styles.button} disabled={busy || !d.factory || d.freight === ""} onClick={() => void save(c)} type="button">
                        保存
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
