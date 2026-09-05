"use client";

import { formatDateTime } from "../home-api";
import { HomeCardShell, HomeItemList } from "../HomeCardShell";
import type { HomeCardProps, HomeDrawerProps } from "../home-types";

export function WOrdersCard({ card, onOpen }: HomeCardProps) {
  const exceptions = typeof card.extra.exceptions === "number" ? card.extra.exceptions : 0;
  return (
    <HomeCardShell
      card={card}
      onOpen={onOpen}
      tag={exceptions ? `物流异常 ${exceptions}` : "待发货"}
      title="W 新订单"
    >
      <HomeItemList card={card} empty="现在没有待处理订单。独立站还没上品，这个零是真的。" />
    </HomeCardShell>
  );
}

export function WOrdersDrawer({ card, notify }: HomeDrawerProps) {
  if (card.items.length === 0) {
    return (
      <div className="hs-empty">
        没有待处理订单。独立站尚未上品，订单同步正常但无单可同步。上品后这里显示待发货和物流异常。
      </div>
    );
  }
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      notify(`已复制 ${text}`);
    } catch {
      notify("复制失败，手动选中吧");
    }
  };
  return (
    <div className="hs-drawer-body">
      {card.items.map((item) => (
        <div className="hs-item" key={item.id}>
          <div className="hs-item-head">
            <span>{item.title}</span>
            <span className="hs-muted">{formatDateTime(item.at)}</span>
          </div>
          <p className="hs-item-sub">{item.subtitle}</p>
          <div className="hs-item-actions">
            <button className="hs-btn" onClick={() => void copy(item.title.replace(/^#/, ""))} type="button">
              复制单号
            </button>
            <span className="hs-muted">发货、录单号在发货模块做。</span>
          </div>
        </div>
      ))}
    </div>
  );
}
