"use client";

import type { HomeBootstrapRead } from "./home-api";
import { HomeShell } from "./HomeShell";
import { HOME_CARD_GROUPS, HOME_CARDS_BY_ID, STORE_HOME_CARDS } from "./home-registry";

/** 每类组织各记一份；旧主页沿用它自己的 v1 键，互不干扰。 */
export const STORE_HOME_STORAGE_KEY = "barong-home-cards-v2:store";

/** 贸易公司主页 = 通用骨架 + 贸易公司的卡片注册表。骨架在 `HomeShell.tsx`。 */
export function StoreHome({ bootstrap }: { bootstrap: HomeBootstrapRead }) {
  return (
    <HomeShell
      bootstrap={bootstrap}
      cardsById={HOME_CARDS_BY_ID}
      eyebrow="工作台 · 贸易公司"
      groups={HOME_CARD_GROUPS}
      registry={STORE_HOME_CARDS}
      storageKey={STORE_HOME_STORAGE_KEY}
      title="控制台概览"
    />
  );
}
