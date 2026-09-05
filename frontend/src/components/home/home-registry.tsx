"use client";

import { ApprovalsCard, ApprovalsDrawer } from "./cards/Approvals";
import { B2bDraftsCard, B2bDraftsDrawer } from "./cards/B2bDrafts";
import { GeoTodoCard, GeoTodoDrawer, SeoTodoCard, SeoTodoDrawer } from "./cards/ContentTodo";
import { CsInboxCard, CsInboxDrawer } from "./cards/CsInbox";
import { SiteHealthCard, SiteHealthDrawer } from "./cards/SiteHealth";
import { SiteTrafficCard, SiteTrafficDrawer } from "./cards/SiteTraffic";
import { SmTodoCard, SmTodoDrawer } from "./cards/SmTodo";
import { WOrdersCard, WOrdersDrawer } from "./cards/WOrders";
import type { HomeCardDef } from "./home-types";

export type { HomeCardDef, HomeCardProps, HomeDrawerProps } from "./home-types";

/**
 * 贸易公司主页的八张卡，顺序即设计稿顺序：外部数据置顶，再是模块待办，最后治理。
 * `module_key` 与后端 `modules/home/registry.py` 和侧边栏 `sidebarItems[].module_key`
 * 是同一套字符串——卡片可见 = 服务端给了 且 侧边栏认为这个模块可进。
 */
export const STORE_HOME_CARDS: readonly HomeCardDef[] = [
  {
    id: "site-traffic",
    title: "独立站流量",
    desc: "Jetpack · 10 分钟一轮 · 默认最近 7 天",
    group: "外部",
    module_key: null,
    moduleHref: null,
    moduleLabel: null,
    Card: SiteTrafficCard,
    Drawer: SiteTrafficDrawer,
    defaultVisible: true,
    wide: true,
  },
  {
    id: "site-health",
    title: "站点健康",
    desc: "H 哨兵最近一次巡检 + worker 心跳",
    group: "外部",
    module_key: null,
    moduleHref: "/h-site-health",
    moduleLabel: "站点健康",
    Card: SiteHealthCard,
    Drawer: SiteHealthDrawer,
    defaultVisible: true,
  },
  {
    id: "cs-inbox",
    title: "客服新消息",
    desc: "零售 + 批发两路新消息，浮窗直接回",
    group: "模块",
    module_key: "cs.customer_service",
    moduleHref: "/cs",
    moduleLabel: "客服",
    Card: CsInboxCard,
    Drawer: CsInboxDrawer,
    defaultVisible: true,
  },
  {
    id: "w-orders",
    title: "W 新订单",
    desc: "待发货订单与物流异常",
    group: "模块",
    module_key: "w.site_ops",
    moduleHref: "/w-s",
    moduleLabel: "发货",
    Card: WOrdersCard,
    Drawer: WOrdersDrawer,
    defaultVisible: true,
  },
  {
    id: "geo-todo",
    title: "GEO 待办",
    desc: "待批评 / 已批未发 / 发布任务卡住",
    group: "模块",
    module_key: "geo.content",
    moduleHref: "/geo",
    moduleLabel: "GEO",
    Card: GeoTodoCard,
    Drawer: GeoTodoDrawer,
    defaultVisible: true,
  },
  {
    id: "seo-todo",
    title: "SEO 待办",
    desc: "待批评 / 已批未发 / 发布任务卡住",
    group: "模块",
    module_key: "seo.content",
    moduleHref: "/seo",
    moduleLabel: "SEO",
    Card: SeoTodoCard,
    Drawer: SeoTodoDrawer,
    defaultVisible: true,
  },
  {
    id: "b2b-drafts",
    title: "B2B 开发信待审",
    desc: "待人工审核的草稿；浮窗只能看和驳回",
    group: "模块",
    module_key: "b2b.wholesale",
    moduleHref: "/b2b-wholesale",
    moduleLabel: "B2B",
    Card: B2bDraftsCard,
    Drawer: B2bDraftsDrawer,
    defaultVisible: true,
  },
  {
    id: "sm-todo",
    title: "社媒待办",
    desc: "待审帖子 / 真照片缺口 / 排不出来的格子",
    group: "模块",
    module_key: "sm.social",
    moduleHref: "/sm",
    moduleLabel: "社媒",
    Card: SmTodoCard,
    Drawer: SmTodoDrawer,
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

export const HOME_CARDS_BY_ID: ReadonlyMap<string, HomeCardDef> = new Map(
  STORE_HOME_CARDS.map((def) => [def.id, def]),
);

export const HOME_CARD_GROUPS = ["外部", "模块", "治理"] as const;
