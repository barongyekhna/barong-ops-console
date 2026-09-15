"use client";

import { HomeCardShell, HomeItemList } from "../HomeCardShell";
import type { HomeCardProps, HomeDrawerProps } from "../home-types";

type StoreView = {
  store_code: string;
  display_name: string;
  currency: string;
  role: string;
  ads: { spend: number; sales: number; orders: number; acos_pct: number | null; first_date: string | null; last_date: string | null };
  transactions: { rows: number; first_at: string | null; last_at: string | null };
};

function stores(card: HomeCardProps["card"]): StoreView[] {
  return Array.isArray(card.extra.stores) ? (card.extra.stores as StoreView[]) : [];
}

function money(value: number, currency: string) {
  return `${currency === "EUR" ? "€" : "$"}${Math.round(value).toLocaleString("en-US")}`;
}

export function AmzStoresCard({ card, onOpen }: HomeCardProps) {
  const list = stores(card);
  const spend = list.reduce((sum, s) => sum + s.ads.spend, 0);
  const sales = list.reduce((sum, s) => sum + s.ads.sales, 0);
  const orders = list.reduce((sum, s) => sum + s.ads.orders, 0);
  const acos = sales > 0 ? Math.round((spend / sales) * 1000) / 10 : null;
  return (
    <HomeCardShell card={card} onOpen={onOpen} tag="亚马逊运营 · 本公司店铺" title="店铺">
      <div className="hs-kpis hs-kpis-3">
        <div className="hs-kpi"><b>{acos === null ? "—" : `${acos}%`}</b><span>ACOS(已导入期)</span></div>
        <div className="hs-kpi"><b>{orders}</b><span>广告订单</span></div>
        <div className="hs-kpi"><b>{list.length}</b><span>店铺</span></div>
      </div>
      <HomeItemList card={card} empty="这家公司还没有店铺记录。跑一次 amz bootstrap。" />
    </HomeCardShell>
  );
}

export function AmzStoresDrawer({ card }: HomeDrawerProps) {
  const list = stores(card);
  return (
    <div className="hs-drawer-body">
      <section className="hs-block">
        <div className="hs-block-head"><span>店铺</span><span className="hs-muted">影子模式 · 只看不动</span></div>
        {list.length === 0 ? (
          <div className="hs-empty">没有店铺。</div>
        ) : (
          list.map((store) => (
            <div className="hs-item" key={store.store_code}>
              <div className="hs-item-head">
                <span>
                  {store.display_name} <span className="hs-pill hs-pill-info">{store.store_code}</span>
                </span>
                <span className={store.ads.acos_pct !== null && store.ads.acos_pct >= 40 ? "hs-pill hs-pill-warn" : "hs-pill hs-pill-ok"}>
                  {store.ads.acos_pct === null ? "无广告数据" : `ACOS ${store.ads.acos_pct}%`}
                </span>
              </div>
              <p className="hs-item-sub">
                花费 {money(store.ads.spend, store.currency)} · 广告销售 {money(store.ads.sales, store.currency)} · 单 {store.ads.orders}
                {store.ads.first_date ? ` · ${store.ads.first_date} → ${store.ads.last_date}` : ""}
                {store.transactions.rows ? ` · 交易 ${store.transactions.rows} 行` : ""}
              </p>
            </div>
          ))
        )}
        <p className="hs-muted">五店合计、两条线、员工消息在「亚马逊运营」模块页;这里只列本公司的店。</p>
      </section>
    </div>
  );
}
