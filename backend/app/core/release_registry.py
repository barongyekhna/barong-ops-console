"""发布元数据。

`SYSTEM_RELEASE_VERSION` 是产品版本的**权威来源**——`core/config.py` 的
`app_version` 读它，前端 `lib/release-metadata.ts` 和「版本更新」面板与它对齐
（有测试钉住三处一致）。改版本号只需改这一行。

⚠️ 下面从 `SYSTEM_RELEASE_TYPE` 开始的 9 个常量是 **2026-06 「C20 冻结」时代的
历史快照，全仓零引用，不构成任何实际门禁**。当时控制台只有 RBAC / 模块 /
API 密钥那一块，所以才敢写 `feature_addition_disabled: True`；此后 K/P/GEO/SEO/
B2B/W/H/M/VPN 十几个系列全是新长出来的，产品早已走出那个范围。
保留它们只为不切断这段 git 历史——**读到时不要当成还在执行的约束**。
"""

from typing import Final

# 2026-09-02：C-SERIES-V1.1.0 → 2.0.0。
# 去掉 "C-SERIES" 前缀是因为那是子系统代号，早已不描述整个产品；
# 跨大版本是因为这一版是九阶段全量修复的总结（主链 12/19→19/19、
# 删死代码 22,730 行、请求延迟 950ms→11-14ms）。
# 格式须满足 ^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$（备份脚本会校验）。
SYSTEM_RELEASE_VERSION: Final = "2.1.0"

# ── 以下为历史快照，零引用，见模块 docstring ──────────────────────────────
SYSTEM_RELEASE_TYPE: Final = "final_release"
SYSTEM_RELEASE_STATUS: Final = "production_frozen"
SYSTEM_RELEASE_STAGE: Final = "c20-final-closure"
SYSTEM_STATE: Final = "FROZEN"

SYSTEM_RELEASE_FLAGS: Final = {
    "is_production_ready": True,
    "is_v1_release": True,
    "is_audit_complete": True,
    "is_production_release": True,
    "is_c_series_closed": True,
    "is_system_mutable": False,
    "structural_changes_disabled": True,
    "feature_addition_disabled": True,
}

SYSTEM_RELEASE_MARKERS: Final = (
    "C-series V1 release",
    "production-ready state",
    "full system audit passed",
    "C20 final production lock",
    "C-series final closure",
)

SYSTEM_FREEZE_SCOPE: Final = (
    "RBAC system: owner / super_admin / viewer",
    "module system",
    "API key system",
    "execution gate",
    "webhook integration",
    "org/user/permission model",
)

STRUCTURAL_AUTO_MODIFICATION_ALLOWED: Final = False
FEATURE_ADDITION_ALLOWED: Final = False
