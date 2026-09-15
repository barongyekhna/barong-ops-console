"use client";

import type { HomeBootstrapRead } from "./home-api";
import { HomeShell } from "./HomeShell";
import {
  AMAZON_HOME_CARD_GROUPS,
  AMAZON_HOME_CARDS,
  AMAZON_HOME_CARDS_BY_ID,
} from "./home-registry-amazon";

export const AMAZON_HOME_STORAGE_KEY = "barong-home-cards-v2:amazon";

/** 亚马逊公司主页 = 通用骨架 + A 系列的卡片注册表。作用域类仍是 home-store,差异放 home-amazon。 */
export function AmazonHome({ bootstrap }: { bootstrap: HomeBootstrapRead }) {
  return (
    <HomeShell
      bootstrap={bootstrap}
      cardsById={AMAZON_HOME_CARDS_BY_ID}
      extraClass="home-amazon"
      eyebrow="工作台 · 亚马逊公司"
      groups={AMAZON_HOME_CARD_GROUPS}
      registry={AMAZON_HOME_CARDS}
      storageKey={AMAZON_HOME_STORAGE_KEY}
      title="控制台概览"
    />
  );
}
