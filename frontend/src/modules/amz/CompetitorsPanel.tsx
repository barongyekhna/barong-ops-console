"use client";

import { useCallback, useEffect, useState } from "react";

import styles from "./AmzWorkspace.module.css";
import { addCompetitor, getCompetitors, type AmzCompetitor, type AmzCompetitorSnap } from "./api";

const LINES: Record<string, string> = { pump: "沐浴泵", heater: "热水棒", flash: "太阳能手电", nail: "磨甲器", bundle: "套装", other: "其他" };

function money(value: number | null | undefined, market: string) {
  if (value == null) return "—";
  return `${market === "DE" ? "€" : "$"}${value.toFixed(2)}`;
}

function delta(now: number | null | undefined, prev: number | null | undefined, lowerIsBetter = false) {
  if (now == null || prev == null || now === prev) return null;
  const up = now > prev;
  const good = lowerIsBetter ? !up : up;
  return <span className={good ? styles.good : styles.bad}>{up ? " ↑" : " ↓"}</span>;
}

function Row({ item }: { item: AmzCompetitor }) {
  const s: AmzCompetitorSnap | null = item.latest;
  const p = item.previous;
  return (
    <tr>
      <td>
        <code>{item.asin}</code>
        <div className={styles.muted}>{item.label || s?.brand || ""}{item.whose === "ours" ? " · 自家" : ""}</div>
      </td>
      <td>{item.product_line_label}</td>
      <td>
        {s ? (s.in_stock === false ? <span className={styles.bad}>断货</span> : money(s.price, item.marketplace)) : "—"}
        {s && p ? delta(s.price, p.price) : null}
        {s?.coupon ? <div className={styles.muted}>券 {s.coupon}</div> : null}
      </td>
      <td>
        {s?.rating ?? "—"}
        {s && p ? delta(s.rating, p.rating) : null}
      </td>
      <td>{s?.reviews ?? "—"}</td>
      <td>
        {s?.bsr ?? "—"}
        {s && p ? delta(s.bsr, p.bsr, true) : null}
      </td>
      <td>{s?.monthly_sold ?? "—"}</td>
      <td className={styles.muted}>{s?.date ?? "还没拍"}</td>
    </tr>
  );
}

/**
 * 殷长辰的竞品盯盘:名单来自事实表里的对手 ASIN + 自家子 ASIN,也可手加。
 * Keepa 每天一张快照,只在「变化」时出建议(价格 ±8%、断货、评分、评论一周猛涨、排名大涨)。这一页不碰亚马逊。
 */
export function CompetitorsPanel() {
  const [market, setMarket] = useState("US");
  const [items, setItems] = useState<AmzCompetitor[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ asin: "", product_line: "pump", whose: "competitor" as "competitor" | "ours", label: "" });

  const load = useCallback(async () => {
    try {
      setItems((await getCompetitors(market)).items);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, [market]);

  useEffect(() => {
    void load();
  }, [load]);

  async function add() {
    const asin = form.asin.trim().toUpperCase();
    if (!/^B0[A-Z0-9]{8}$/.test(asin)) {
      setStatus("ASIN 要 10 位,B0 开头");
      return;
    }
    setBusy(true);
    try {
      const result = await addCompetitor({ marketplace: market, asin, product_line: form.product_line, whose: form.whose, label: form.label.trim() || undefined });
      setItems(result.items);
      setStatus(result.added ? `已加入 ${asin},明天起每天拍一张` : `${asin} 已经在名单里`);
      setForm((prev) => ({ ...prev, asin: "", label: "" }));
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const snapped = items.filter((i) => i.latest).length;

  return (
    <div className={styles.workspace}>
      {status ? <div className={styles.muted} style={{ padding: "6px 2px" }}>{status}</div> : null}
      <section className={styles.panel} aria-label="竞品">
        <div className={styles.panelHead}>
          <h2>竞品 · 殷长辰盯盘</h2>
          <span className={styles.muted}>
            Keepa 每天一张快照,只报变化 · 名单 {items.length} 个,已拍 {snapped} 个
          </span>
        </div>
        <div className={styles.sheetActions}>
          {["US", "DE"].map((m) => (
            <button className={m === market ? styles.button : styles.linkButton} key={m} onClick={() => setMarket(m)} type="button">
              {m === "US" ? "美国站" : "德国站"}
            </button>
          ))}
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>ASIN</th>
                <th>产品线</th>
                <th>价格</th>
                <th>评分</th>
                <th>评论</th>
                <th>BSR</th>
                <th>月销</th>
                <th>快照日</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <Row item={item} key={item.id} />
              ))}
              {items.length === 0 ? (
                <tr>
                  <td className={styles.muted} colSpan={8}>
                    名单是空的:在事实表的「竞品 ASIN」里填,或在下面手加
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <div className={styles.sheetRow}>
          <label>
            ASIN
            <input onChange={(e) => setForm((prev) => ({ ...prev, asin: e.target.value }))} placeholder="B0XXXXXXXX" value={form.asin} />
          </label>
          <label>
            产品线
            <select onChange={(e) => setForm((prev) => ({ ...prev, product_line: e.target.value }))} value={form.product_line}>
              {Object.entries(LINES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label>
            是谁的
            <select onChange={(e) => setForm((prev) => ({ ...prev, whose: e.target.value as "competitor" | "ours" }))} value={form.whose}>
              <option value="competitor">对手</option>
              <option value="ours">自家</option>
            </select>
          </label>
          <label>
            备注名
            <input onChange={(e) => setForm((prev) => ({ ...prev, label: e.target.value }))} placeholder="比如 vignuto" value={form.label} />
          </label>
        </div>
        <div className={styles.sheetActions}>
          <button className={styles.button} disabled={busy} onClick={() => void add()} type="button">
            加入盯盘
          </button>
        </div>
      </section>
    </div>
  );
}
