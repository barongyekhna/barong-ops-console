"use client";

import { ApprovalsCard, ApprovalsDrawer } from "./cards/Approvals";
import { MfgCapacityCard, MfgCapacityDrawer } from "./cards/MfgCapacity";
import { MfgDocsCard, MfgDocsDrawer } from "./cards/MfgDocs";
import { MfgStockCard, MfgStockDrawer } from "./cards/MfgStock";
import { NijingCard, NijingDrawer } from "./cards/Nijing";
import type { HomeCardDef } from "./home-types";

/**
 * 制造公司主页的五张卡，顺序即设计顺序。独立文件：`home-store.test.mjs` 会用正则扫
 * `home-registry.tsx` 里所有卡 id，放一起会把贸易公司那条测试打断。
 * `module_key` 与后端 `home/factory_registry.py` 和侧边栏 `mfg.inventory` 同一套字符串。
 */
export const FACTORY_HOME_CARDS: readonly HomeCardDef[] = [
  {
    id: "mfg-stock",
    title: "库存总览",
    desc: "成品库存 + 断货物料，库存 = 流水求和",
    group: "库存",
    module_key: "mfg.inventory",
    moduleHref: "/mfg-inventory",
    moduleLabel: "库存",
    Card: MfgStockCard,
    Drawer: MfgStockDrawer,
    defaultVisible: true,
    wide: true,
  },
  {
    id: "mfg-capacity",
    title: "生产能力 · 缺料",
    desc: "按配件清单和现有库存算每个成品最多还能产多少",
    group: "库存",
    module_key: "mfg.inventory",
    moduleHref: "/mfg-inventory",
    moduleLabel: "库存",
    Card: MfgCapacityCard,
    Drawer: MfgCapacityDrawer,
    defaultVisible: true,
  },
  {
    id: "mfg-docs",
    title: "今日单据",
    desc: "入库 / 生产 / 发货 / 盘点调整，按工厂时间",
    group: "库存",
    module_key: "mfg.inventory",
    moduleHref: "/mfg-inventory",
    moduleLabel: "库存",
    Card: MfgDocsCard,
    Drawer: MfgDocsDrawer,
    defaultVisible: true,
  },
  {
    id: "nijing",
    title: "霓旌 · 库管员",
    desc: "心跳 + 今天办了什么、被拦了什么",
    group: "数字员工",
    module_key: null,
    moduleHref: "/c19",
    moduleLabel: "C19",
    Card: NijingCard,
    Drawer: NijingDrawer,
    defaultVisible: true,
  },
  {
    id: "approvals",
    title: "审批与通知",
    desc: "待批审批 + 未读通知",
    group: "治理",
    module_key: null,
    moduleHref: "/approvals",
    moduleLabel: "审批",
    Card: ApprovalsCard,
    Drawer: ApprovalsDrawer,
    defaultVisible: true,
  },
];

export const FACTORY_HOME_CARDS_BY_ID: ReadonlyMap<string, HomeCardDef> = new Map(
  FACTORY_HOME_CARDS.map((def) => [def.id, def]),
);

export const FACTORY_HOME_CARD_GROUPS = ["库存", "数字员工", "治理"] as const;
