"use client";

import { formatDateTime } from "../home-api";
import { HomeCardShell, HomeItemList } from "../HomeCardShell";
import type { HomeCardProps, HomeDrawerProps } from "../home-types";

type DocRow = {
  id: string;
  doc_no: string;
  doc_type: string;
  doc_type_label: string;
  actor_name: string;
  note: string | null;
  created_at: string | null;
};

const TYPE_TONE: Record<string, string> = {
  receipt: "ok",
  production: "info",
  shipment: "warn",
  adjustment: "bad",
};

function today(card: HomeCardProps["card"]) {
  const value = (card.extra.today ?? {}) as Record<string, number>;
  return {
    receipt: value.receipt ?? 0,
    production: value.production ?? 0,
    shipment: value.shipment ?? 0,
    adjustment: value.adjustment ?? 0,
  };
}

export function MfgDocsCard({ card, onOpen }: HomeCardProps) {
  const counts = today(card);
  const tz = typeof card.extra.tz === "string" ? card.extra.tz : "工厂时间";
  return (
    <HomeCardShell card={card} freshnessNote={tz} onOpen={onOpen} tag="今天开的单" title="今日单据">
      <div className="hs-kpis">
        <div className="hs-kpi"><b>{counts.receipt}</b><span>入库</span></div>
        <div className="hs-kpi"><b>{counts.production}</b><span>生产</span></div>
        <div className="hs-kpi"><b>{counts.shipment}</b><span>发货</span></div>
        <div className="hs-kpi"><b>{counts.adjustment}</b><span>盘点调整</span></div>
      </div>
      <HomeItemList card={card} empty="今天还没开单。" />
    </HomeCardShell>
  );
}

export function MfgDocsDrawer({ card }: HomeDrawerProps) {
  const recent = Array.isArray(card.extra.recent) ? (card.extra.recent as DocRow[]) : [];
  const counts = today(card);
  return (
    <div className="hs-drawer-body">
      <div className="hs-kpis">
        <div className="hs-kpi"><b>{counts.receipt}</b><span>入库</span></div>
        <div className="hs-kpi"><b>{counts.production}</b><span>生产</span></div>
        <div className="hs-kpi"><b>{counts.shipment}</b><span>发货</span></div>
        <div className="hs-kpi"><b>{counts.adjustment}</b><span>盘点调整</span></div>
      </div>
      <section className="hs-block">
        <div className="hs-block-head"><span>最近的单据</span><span className="hs-muted">单据落地即不可改</span></div>
        {recent.length === 0 ? (
          <div className="hs-empty">还没有单据。</div>
        ) : (
          recent.map((doc) => (
            <div className="hs-item" key={doc.id}>
              <div className="hs-item-head">
                <span>
                  {doc.doc_no}{" "}
                  <span className={`hs-pill hs-pill-${TYPE_TONE[doc.doc_type] ?? "info"}`}>{doc.doc_type_label}</span>
                </span>
                <span className="hs-muted">{formatDateTime(doc.created_at)}</span>
              </div>
              <p className="hs-item-sub">
                {doc.actor_name}
                {doc.note ? ` · ${doc.note}` : ""}
              </p>
            </div>
          ))
        )}
      </section>
      <p className="hs-muted">开新单、看流水、撤销（反向调整）都在库存模块里做。</p>
    </div>
  );
}
