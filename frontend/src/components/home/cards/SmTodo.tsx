"use client";

import { formatDateTime } from "../home-api";
import { HomeCardShell, HomeItemList } from "../HomeCardShell";
import type { HomeCardProps, HomeDrawerProps } from "../home-types";

function counts(card: HomeCardProps["card"]) {
  const n = (key: string) => (typeof card.extra[key] === "number" ? (card.extra[key] as number) : 0);
  return { pending: n("pending_review"), gaps: n("photo_gaps_due"), blocked: n("blocked_slots") };
}

export function SmTodoCard({ card, onOpen }: HomeCardProps) {
  const { pending, gaps, blocked } = counts(card);
  return (
    <HomeCardShell
      card={card}
      onOpen={onOpen}
      tag={`待审 ${pending} · 缺真照片 ${gaps}${blocked ? ` · 排不出 ${blocked}` : ""}`}
      title="社媒待办"
    >
      <HomeItemList card={card} empty="没有等你的帖子，也不缺图。" />
    </HomeCardShell>
  );
}

/** 浮窗只看和跳转：审帖子在内容台，拍照片在吉林，这里都替不了。 */
export function SmTodoDrawer({ card }: HomeDrawerProps) {
  const { pending, gaps, blocked } = counts(card);
  return (
    <div className="hs-drawer-body">
      <div className="hs-kpis hs-kpis-3">
        <div className="hs-kpi"><b>{pending}</b><span>待审帖子</span></div>
        <div className="hs-kpi"><b>{gaps}</b><span>真照片缺口（7 天内到期）</span></div>
        <div className="hs-kpi"><b>{blocked}</b><span>排不出来的格子</span></div>
      </div>
      {card.items.length === 0 ? (
        <div className="hs-empty">四周日历都排好了，没有等你的事。</div>
      ) : (
        card.items.map((item) => (
          <div className="hs-item" key={item.id}>
            <div className="hs-item-head">
              <span>{item.title}</span>
              <span className="hs-muted">{formatDateTime(item.at)}</span>
            </div>
            <p className="hs-item-sub">{item.subtitle}</p>
            <div className="hs-item-actions">
              <a className="hs-btn" href={item.href}>
                去处理
              </a>
              <span className="hs-muted">帖子在内容台审；照片要真人拍。</span>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
