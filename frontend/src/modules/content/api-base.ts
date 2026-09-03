/**
 * 内容台 / GEO / SEO 面板的请求入口。
 *
 * 历史：这里的 `API_PROXY_BASE` / `buildHeaders` / `readJson` 三段原本在
 * LinkNetPanel、ContentHealthPanel、SiteNavPanel 里**各复制一份**，内容台是
 * 第四处；那一轮把四份合成了这一份。2026-09-02 再往上收一层——传输层交给
 * `lib/api.ts`（超时、GET 重试、路由切换取消、401 派发、并发闸门、中文兜底），
 * 错误口径又跟另外四个模块合并进了
 * `lib/labelled-api.ts`（B 式：`${label}（${status}）：${说明}`）。
 *
 * 那个口径要原样保住 —— 四个面板的 catch 分支直接把 message 显示给人看，
 * 「站内入口加载失败（502）」比一句笼统的中文兜底信息量大得多。
 *
 * 于是本文件只剩两件东西：一个改名转发，和下面这两个超时常量。
 */

export { requestWithLabel as contentRequest } from "@/lib/labelled-api";

/**
 * 同步跑 AI / 同步打 WP.com 的接口的超时预算。
 *
 * `lib/api.ts` 给非 GET 的默认值是 15 秒，而这个模块里有几个接口**不是派单、
 * 是当场等结果**：内容台的「重写」「解读」同步等 DeepSeek 返回（后端注释写着
 * 「同步，两边都是」，实测约 30 秒）；站内入口同步和内链网刷新要连着打 WP.com。
 * 收口前它们一个超时都没有，照默认值收口 = 这几个按钮从此必然超时失败。
 */
export const SLOW_AI_TIMEOUT_MS = 180_000;
export const SLOW_WP_TIMEOUT_MS = 120_000;

