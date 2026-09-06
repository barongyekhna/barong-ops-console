"use client";

import type { HomeBootstrapRead } from "./home-api";
import { HomeShell } from "./HomeShell";
import {
  FACTORY_HOME_CARD_GROUPS,
  FACTORY_HOME_CARDS,
  FACTORY_HOME_CARDS_BY_ID,
} from "./home-registry-factory";

export const FACTORY_HOME_STORAGE_KEY = "barong-home-cards-v2:factory";

/** 制造公司主页 = 通用骨架 + 制造公司的卡片注册表。作用域类仍是 home-store，差异放 home-factory。 */
export function FactoryHome({ bootstrap }: { bootstrap: HomeBootstrapRead }) {
  return (
    <HomeShell
      bootstrap={bootstrap}
      cardsById={FACTORY_HOME_CARDS_BY_ID}
      extraClass="home-factory"
      eyebrow="工作台 · 制造公司"
      groups={FACTORY_HOME_CARD_GROUPS}
      registry={FACTORY_HOME_CARDS}
      storageKey={FACTORY_HOME_STORAGE_KEY}
      title="控制台概览"
    />
  );
}
