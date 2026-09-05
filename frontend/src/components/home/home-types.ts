import type { ComponentType } from "react";

import type { HomeCardRead } from "./home-api";

export type HomeDrawerProps = {
  card: HomeCardRead;
  /** 浮窗里做完简单操作后的乐观更新；下一帧服务端整卡覆盖收敛。 */
  patchCard: (updater: (card: HomeCardRead) => HomeCardRead) => void;
  /** 操作失败或拿不准时拉一次真值。 */
  refetchCard: () => Promise<void>;
  onClose: () => void;
  notify: (message: string) => void;
};

export type HomeCardProps = { card: HomeCardRead; onOpen: () => void };

export type HomeCardGroup = "外部" | "模块" | "治理";

export type HomeCardDef = {
  id: string;
  title: string;
  desc: string;
  group: HomeCardGroup;
  /** null = 外部数据卡，store 组织人人可见；否则要过 sidebarItems 的模块门。 */
  module_key: string | null;
  /** 浮窗底部「去模块」跳转目标；null = 只看不跳。 */
  moduleHref: string | null;
  moduleLabel: string | null;
  Card: ComponentType<HomeCardProps>;
  Drawer: ComponentType<HomeDrawerProps>;
  defaultVisible: boolean;
  wide?: boolean;
};

/** 从卡片条目里取掉一条并把角标减一：所有「处理完就消失」的浮窗动作共用。 */
export function withoutItem(card: HomeCardRead, itemId: string): HomeCardRead {
  const remaining = card.items.filter((item) => item.id !== itemId);
  const removed = remaining.length !== card.items.length;
  return {
    ...card,
    items: remaining,
    count: removed && typeof card.count === "number" ? Math.max(0, card.count - 1) : card.count,
  };
}
