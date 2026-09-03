/**
 * 带模块标签的请求包装。
 *
 * 传输层（超时、GET 重试、路由切换取消、401 派发、并发闸门、中文兜底）全在
 * `lib/api.ts`；这里只做一件事：把 `ApiError` 拼成各模块面板要显示给人看的
 * 那句话。**状态码必须留在用户看得见的地方** —— 用户报「跳转管理（502）」
 * 能立刻定位，报「服务暂时不可用」就只能猜。
 *
 * 全仓历史上存在两种口径，各占一半。不合并成一种（那会改掉八个模块的
 * 用户可见文案，超出「收口传输层」的范围），但收进同一个文件、写清区别：
 *
 *   A 式 `detail || 标签（状态）`  —— b2b、h/sitehealth、p/upload
 *   B 式 `标签（状态）：detail`    —— content、f、seo、geo、w
 *
 * 收口前这两段各自被复制了 8 份。副本必然分叉，这就是它们该在一处的理由。
 */

import { ApiError, apiRequest } from "@/lib/api";

export type LabelledOptions = {
  body?: unknown;
  method?: string;
  timeoutMs?: number;
};

/** 后端 detail 里的人话，取不到就空串。也认发布门禁那种 `{blockers: []}`。 */
function humanDetail(error: ApiError): string {
  const raw = error.detail;
  if (typeof raw === "string" && raw) {
    return raw;
  }
  if (
    raw &&
    typeof raw === "object" &&
    Array.isArray((raw as { blockers?: unknown }).blockers)
  ) {
    // 发布门禁的 409 是结构化的：把「为什么发不出去」逐条原样说出来。
    return (raw as { blockers: string[] }).blockers.join("；");
  }
  return "";
}

/** A 式：后端给了人话就只显示人话，没给才退回带状态码的标签。 */
export async function requestPreferDetail<T>(
  path: string,
  label: string,
  options: LabelledOptions = {},
): Promise<T> {
  try {
    return await apiRequest<T>(path, options);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    const detail = humanDetail(error);
    throw new Error(detail || `${label}（${error.status}）`);
  }
}

/** B 式：标签和状态码始终在前，后端的人话追加在冒号后面。 */
export async function requestWithLabel<T>(
  path: string,
  label: string,
  options: LabelledOptions = {},
): Promise<T> {
  try {
    return await apiRequest<T>(path, options);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    const detail = humanDetail(error);
    throw new Error(
      `${label}（${error.status}）${detail ? `：${detail}` : ""}`,
    );
  }
}
