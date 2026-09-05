"use client";

import { useState } from "react";

import { reviewItem as reviewGeoItem } from "@/modules/geo/content/api";
import { reviewItem as reviewSeoItem } from "@/modules/seo/facts/api";

import { formatDateTime, type HomeCardItem } from "../home-api";
import { HomeCardShell, HomeItemList } from "../HomeCardShell";
import { withoutItem, type HomeCardProps, type HomeDrawerProps } from "../home-types";

type Engine = "geo" | "seo";

const TITLE: Record<Engine, string> = { geo: "GEO 待办", seo: "SEO 待办" };
const MODULE_LABEL: Record<Engine, string> = { geo: "GEO", seo: "SEO" };
const REVIEW: Record<Engine, (id: string) => Promise<unknown>> = {
  geo: (id) => reviewGeoItem(id, "approved"),
  seo: (id) => reviewSeoItem(id, "approved"),
};

function counts(card: HomeCardProps["card"]) {
  const n = (key: string) => (typeof card.extra[key] === "number" ? (card.extra[key] as number) : 0);
  return { pending: n("pending_review"), unpublished: n("unpublished"), jobs: n("publish_jobs") };
}

function makeCard(engine: Engine) {
  return function ContentTodoCard({ card, onOpen }: HomeCardProps) {
    const { pending, unpublished, jobs } = counts(card);
    return (
      <HomeCardShell
        card={card}
        onOpen={onOpen}
        tag={`待批评 ${pending} · 待发布 ${unpublished}${jobs ? ` · 任务卡住 ${jobs}` : ""}`}
        title={TITLE[engine]}
      >
        <HomeItemList card={card} empty="没有等你的稿子。" />
      </HomeCardShell>
    );
  };
}

function ApproveRow({
  engine,
  item,
  patchCard,
  refetchCard,
  notify,
}: { engine: Engine; item: HomeCardItem } & Pick<HomeDrawerProps, "patchCard" | "refetchCard" | "notify">) {
  const [busy, setBusy] = useState(false);
  const approve = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await REVIEW[engine](item.id);
      patchCard((card) => withoutItem(card, item.id));
      notify("已放行，发布在模块里点");
    } catch {
      notify(`放行失败，去 ${MODULE_LABEL[engine]} 模块看原因`);
      await refetchCard();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="hs-item">
      <div className="hs-item-head">
        <span>{item.title}</span>
        <span className="hs-muted">{formatDateTime(item.at)}</span>
      </div>
      <p className="hs-item-sub">{item.subtitle}</p>
      <div className="hs-item-actions">
        <button className="hs-btn hs-btn-primary" disabled={busy} onClick={approve} type="button">
          放行
        </button>
        <span className="hs-muted">改稿、发布、批评回写在模块里做。</span>
      </div>
    </div>
  );
}

function makeDrawer(engine: Engine) {
  return function ContentTodoDrawer({ card, patchCard, refetchCard, notify }: HomeDrawerProps) {
    const { pending, unpublished, jobs } = counts(card);
    return (
      <div className="hs-drawer-body">
        <div className="hs-kpis hs-kpis-3">
          <div className="hs-kpi"><b>{pending}</b><span>待批评</span></div>
          <div className="hs-kpi"><b>{unpublished}</b><span>已批未发</span></div>
          <div className="hs-kpi"><b>{jobs}</b><span>发布任务卡住</span></div>
        </div>
        {card.items.length === 0 ? (
          <div className="hs-empty">没有待批评的稿子。已批未发和卡住的任务在模块里处理。</div>
        ) : (
          card.items.map((item) => (
            <ApproveRow
              engine={engine}
              item={item}
              key={item.id}
              notify={notify}
              patchCard={patchCard}
              refetchCard={refetchCard}
            />
          ))
        )}
      </div>
    );
  };
}

export const GeoTodoCard = makeCard("geo");
export const GeoTodoDrawer = makeDrawer("geo");
export const SeoTodoCard = makeCard("seo");
export const SeoTodoDrawer = makeDrawer("seo");
