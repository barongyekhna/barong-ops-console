"use client";

// B2B 产品页小窗 + 批发站点发布的接口层。请求统一走 `lib/api.ts`。
//
// **超时是这里唯一需要动脑的地方。** 收口前这四个调用一个超时都没有(无限等);
// `lib/api.ts` 给非 GET 的默认值是 15 秒,而下面两个写接口都会连着打 WP.com:
//   · `/b2b/website/publish` = 1 个主页 + N 个店型子页 + 指南回链 + 小窗文案,
//     生产上现在 N=6,也就是至少 9 次跨公网往返 —— 15 秒必被掐断。
//   · `/b2b/widget-push` = 按产品逐个推,规模随产品数长。
// 所以这两处显式放宽。留一个有限上限而不是照抄「无限等」:WP 挂了的时候,
// 无限等会让按钮永远转圈、连一句话都给不出。

import { b2bRequest } from "../api-base";

const LABEL = "B2B 产品页小窗";

/** WP.com 往返慢,发布一次要打 9+ 次。见文件头。 */
const WHOLESALE_PUBLISH_TIMEOUT_MS = 180_000;
const WIDGET_PUSH_TIMEOUT_MS = 120_000;

export type WidgetJob = {
  job_id: string;
  status: "queued" | "dispatched" | "success" | "failed";
  targets: number;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
};

export type WidgetPushResult = {
  job_id: string;
  status: string;
  targets: number;
};

export async function getWidgetJobs(): Promise<WidgetJob[]> {
  return b2bRequest<WidgetJob[]>("/b2b/widget-jobs", LABEL);
}

/** 全量重推。政策文案改了之后用这个——每产品的数据平时保存即自动推。 */
export async function pushWidgets(): Promise<WidgetPushResult> {
  return b2bRequest<WidgetPushResult>("/b2b/widget-push", LABEL, {
    method: "POST",
    timeoutMs: WIDGET_PUSH_TIMEOUT_MS,
  });
}

export type WholesaleSiteStatus = {
  main_page_id: string | null;
  last_published_at: string | null;
  store_types: {
    key: string;
    label: string;
    count: number;
    url: string;
    page_id: string | null;
    /** 上次生成时真的挂上去的指南篇数（已向 WP 核过是不是已发布）。 */
    guides: number;
  }[];
  /** 反向回链覆盖了几个 WP 类目。 */
  guide_categories_mapped: number;
};

export type WholesalePublishResult = {
  main_page_id: number;
  main_link: string | null;
  groups: number;
  store_type_pages: { label: string; count: number; link: string | null }[];
};

export async function getWholesaleSiteStatus(): Promise<WholesaleSiteStatus> {
  return b2bRequest<WholesaleSiteStatus>("/b2b/website/status", LABEL);
}

/** 重新生成 /wholesale/ 主页和全部店型子页。幂等。 */
export async function publishWholesaleSite(): Promise<WholesalePublishResult> {
  return b2bRequest<WholesalePublishResult>("/b2b/website/publish", LABEL, {
    method: "POST",
    timeoutMs: WHOLESALE_PUBLISH_TIMEOUT_MS,
  });
}
