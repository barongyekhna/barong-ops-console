/**
 * B2B 各面板的请求入口。口径见 `lib/labelled-api.ts`：
 * 后端给了人话 detail 就原样显示，没给就退回 `${label}（${status}）`。
 */

export { requestPreferDetail as b2bRequest } from "@/lib/labelled-api";
