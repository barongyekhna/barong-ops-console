"use client";

import { HomeCardShell } from "../HomeCardShell";
import type { HomeCardProps, HomeDrawerProps } from "../home-types";

type StockRow = { id: string; code: string; name: string; kind: string; unit: string; stock: string };

function rows(card: HomeCardProps["card"], key: "products" | "zero"): StockRow[] {
  const value = card.extra[key];
  return Array.isArray(value) ? (value as StockRow[]) : [];
}

function num(card: HomeCardProps["card"], key: string) {
  return typeof card.extra[key] === "number" ? (card.extra[key] as number) : 0;
}

function StockList({ list, showBar }: { list: StockRow[]; showBar: boolean }) {
  if (list.length === 0) return <div className="hs-empty">还没有成品。</div>;
  const top = Math.max(1, ...list.map((row) => Number(row.stock) || 0));
  return (
    <div className="hs-stock">
      {list.map((row) => {
        const qty = Number(row.stock) || 0;
        return (
          <div className="hs-stock-row" key={row.id}>
            <span>
              <b title={row.name}>{row.name}</b>
              <small>{row.code} · {row.kind === "product" ? "成品" : "配件"}</small>
              {showBar ? <div className="hs-stockbar" style={{ width: `${Math.max(2, Math.round((100 * qty) / top))}%` }} /> : null}
            </span>
            <span className={qty <= 0 ? "hs-qty hs-qty-zero" : "hs-qty"}>
              {row.stock} {row.unit}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function MfgStockCard({ card, onOpen }: HomeCardProps) {
  const zeroCount = num(card, "zero_count");
  return (
    <HomeCardShell
      card={card}
      onOpen={onOpen}
      tag={`成品 ${num(card, "products_total")} · 配件 ${num(card, "parts_total")}${zeroCount ? ` · 断货 ${zeroCount}` : ""}`}
      title="库存总览"
    >
      <StockList list={rows(card, "products").slice(0, 5)} showBar />
      {zeroCount > 0 ? (
        <div className="hs-alert">
          {rows(card, "zero").slice(0, 3).map((row) => row.name).join("、")}
          {zeroCount > 3 ? ` 等 ${zeroCount} 项` : ""} 断货
        </div>
      ) : null}
    </HomeCardShell>
  );
}

export function MfgStockDrawer({ card }: HomeDrawerProps) {
  return (
    <div className="hs-drawer-body">
      <div className="hs-kpis hs-kpis-3">
        <div className="hs-kpi"><b>{num(card, "products_total")}</b><span>成品种类</span></div>
        <div className="hs-kpi"><b>{num(card, "parts_total")}</b><span>配件种类</span></div>
        <div className="hs-kpi"><b>{num(card, "zero_count")}</b><span>断货物料</span></div>
      </div>
      <section className="hs-block">
        <div className="hs-block-head"><span>成品库存</span><span className="hs-muted">库存 = 流水求和</span></div>
        <StockList list={rows(card, "products")} showBar />
      </section>
      <section className="hs-block">
        <div className="hs-block-head"><span>断货</span><span className="hs-muted">现有 ≤ 0 的物料</span></div>
        {rows(card, "zero").length === 0 ? (
          <div className="hs-empty">没有断货。</div>
        ) : (
          <StockList list={rows(card, "zero")} showBar={false} />
        )}
      </section>
      <p className="hs-muted">入库、盘点在库存模块做；这里只看。</p>
    </div>
  );
}
