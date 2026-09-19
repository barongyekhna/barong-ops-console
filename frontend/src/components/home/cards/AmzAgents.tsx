"use client";

import { formatDateTime } from "../home-api";
import { HomeCardShell, HomeItemList } from "../HomeCardShell";
import type { HomeCardProps, HomeDrawerProps } from "../home-types";

export function AmzAgentsCard({ card, onOpen }: HomeCardProps) {
  const stale = Number(card.extra.stale ?? 0);
  const total = Number(card.extra.total ?? card.items.length);
  const roles = Array.isArray(card.extra.roles) ? (card.extra.roles as string[]) : [];
  return (
    <HomeCardShell card={card} onOpen={onOpen} tag="数字员工" title="运营员工">
      <div className="hs-inline">
        <span className={stale === 0 ? "hs-pill hs-pill-ok" : "hs-pill hs-pill-warn"}>
          {stale === 0 ? `${total} 人全在岗` : `${total - stale} / ${total} 人在岗`}
        </span>
        <span className="hs-muted">{roles.join(" · ")}</span>
      </div>
      <HomeItemList card={card} empty="员工还没上岗。" />
    </HomeCardShell>
  );
}

export function AmzAgentsDrawer({ card }: HomeDrawerProps) {
  return (
    <div className="hs-drawer-body">
      <section className="hs-block">
        <div className="hs-block-head"><span>{card.items.length} 名数字员工</span></div>
        {card.items.map((item) => (
          <div className="hs-item" key={item.id}>
            <div className="hs-item-head">
              <span>{item.title}</span>
              <span className={item.subtitle === "在岗" ? "hs-pill hs-pill-ok" : "hs-pill hs-pill-warn"}>{item.subtitle}</span>
            </div>
            <p className="hs-item-sub">{item.at ? `最近干成活 ${formatDateTime(item.at)}` : "还没有心跳"}</p>
          </div>
        ))}
        <p className="hs-muted">他们只在卡住时开口,一天最多一条,同一件事不重提。私聊在 C19。</p>
      </section>
    </div>
  );
}
