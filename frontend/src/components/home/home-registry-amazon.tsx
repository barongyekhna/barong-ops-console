"use client";

import { AmzAgentsCard, AmzAgentsDrawer } from "./cards/AmzAgents";
import { AmzStoresCard, AmzStoresDrawer } from "./cards/AmzStores";
import { ApprovalsCard, ApprovalsDrawer } from "./cards/Approvals";
import type { HomeCardDef } from "./home-types";

/**
 * 亚马逊公司主页(A 系列)的三张卡。独立文件,与贸易/制造注册表互不覆盖。
 * `module_key` 与后端 `home/factory_registry.py::AMAZON_CARDS` 同一套字符串。
 */
export const AMAZON_HOME_CARDS: readonly HomeCardDef[] = [
  {
    id: "amz-stores",
    title: "店铺",
    desc: "本公司的店铺 · 已导入期的广告花费 / 销售 / ACOS",
    group: "模块",
    module_key: "amz.ops",
    moduleHref: "/amz",
    moduleLabel: "亚马逊运营",
    Card: AmzStoresCard,
    Drawer: AmzStoresDrawer,
    defaultVisible: true,
    wide: true,
  },
  {
    id: "amz-agents",
    title: "运营员工",
    desc: "A 文案 · B 图片 · C 竞品 · D 广告,心跳与在岗",
    group: "数字员工",
    module_key: null,
    moduleHref: "/c19",
    moduleLabel: "C19",
    Card: AmzAgentsCard,
    Drawer: AmzAgentsDrawer,
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

export const AMAZON_HOME_CARDS_BY_ID: ReadonlyMap<string, HomeCardDef> = new Map(
  AMAZON_HOME_CARDS.map((def) => [def.id, def]),
);

export const AMAZON_HOME_CARD_GROUPS = ["模块", "数字员工", "治理"] as const;
