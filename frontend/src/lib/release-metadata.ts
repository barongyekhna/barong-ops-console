/**
 * 前端侧的发布元数据。
 *
 * `RELEASE_VERSION` 必须与后端 `backend/app/core/release_registry.py` 的
 * `SYSTEM_RELEASE_VERSION` **完全一致**——后端是权威来源，这里是手抄副本。
 *
 * 2026-09-02 之前这个文件全仓零 import，是纯死代码，两边靠人手同步、
 * 漂了也没人知道。现在「版本更新」面板从这里读版本号，它第一次有了真正的
 * 消费者：号错了顶栏上肉眼可见。另有一条测试钉住三处一致
 * （后端常量 / 这里 / RELEASE_NOTES 首条），把静默漂移变成测试期就报的错。
 *
 * ⚠️ 下面 5 个常量是 2026-06「C20 冻结」时代的历史快照，零引用、
 * 不构成任何约束，详见后端 release_registry.py 的说明。
 */

export const RELEASE_VERSION = "2.1.0";

// ── 以下为历史快照，零引用 ────────────────────────────────────────────────
export const RELEASE_TYPE = "final_release";
export const RELEASE_STATUS = "production_frozen";
export const RELEASE_STAGE = "c20-final-closure";
export const SYSTEM_STATE = "FROZEN";
export const IS_SYSTEM_MUTABLE = false;
