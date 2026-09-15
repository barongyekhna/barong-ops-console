"""A 系列固定常量。改这里的值 = 改门禁,走版本号。"""

from __future__ import annotations

MODULE_KEY = "amz.ops"

PERMISSION_READ = "amz.ops.read"
PERMISSION_EXECUTE = "amz.ops.execute"
PERMISSION_MANAGE = "amz.ops.manage"
PERMISSION_KEYS: tuple[str, ...] = (PERMISSION_READ, PERMISSION_EXECUTE, PERMISSION_MANAGE)

AMAZON_ORG_TYPE = "amazon"

# 店铺 = 卖家账号 × 区域。code 是全卖通里的编号习惯(01=龙杰 03=利连 04=会学 05=宇州)。
STORE_ROLE_VIEW = "view"
STORE_ROLE_OPERATE = "operate"
STORE_ROLE_GRANT = "grant"
STORE_ROLES: tuple[str, ...] = (STORE_ROLE_VIEW, STORE_ROLE_OPERATE, STORE_ROLE_GRANT)
STORE_ROLE_RANK: dict[str, int] = {STORE_ROLE_VIEW: 1, STORE_ROLE_OPERATE: 2, STORE_ROLE_GRANT: 3}

REGION_NA = "na"
REGION_EU = "eu"
REGION_FE = "fe"
REGIONS: tuple[str, ...] = (REGION_NA, REGION_EU, REGION_FE)

# 数字员工 A/B/C/D(名字用户以后起;先用字母)。
EMPLOYEE_A = "A"
EMPLOYEE_B = "B"
EMPLOYEE_C = "C"
EMPLOYEE_D = "D"
EMPLOYEES: tuple[str, ...] = (EMPLOYEE_A, EMPLOYEE_B, EMPLOYEE_C, EMPLOYEE_D)
EMPLOYEE_ROLE_LABELS: dict[str, str] = {
    EMPLOYEE_A: "Listing 文案",
    EMPLOYEE_B: "图片",
    EMPLOYEE_C: "竞品",
    EMPLOYEE_D: "广告",
}
EMPLOYEE_USERNAMES: dict[str, str] = {
    EMPLOYEE_A: "amz_a",
    EMPLOYEE_B: "amz_b",
    EMPLOYEE_C: "amz_c",
    EMPLOYEE_D: "amz_d",
}
EMPLOYEE_PASSWORD_ENVS: dict[str, str] = {
    EMPLOYEE_A: "AMZ_AGENT_A_PASSWORD",
    EMPLOYEE_B: "AMZ_AGENT_B_PASSWORD",
    EMPLOYEE_C: "AMZ_AGENT_C_PASSWORD",
    EMPLOYEE_D: "AMZ_AGENT_D_PASSWORD",
}
EMPLOYEE_AGENT_ID_PREFIX = "amz."

# 密钥管理里的 key 类型与别名约定(全部绑在公司组织 × amz.ops)。
KEY_TYPE_SP_API = "amazon_sp_api"
KEY_TYPE_ADS_API = "amazon_ads_api"
KEY_ALIAS_SP_API = "sp_api"          # 每公司一把,龙杰 NA/EU 共用
KEY_ALIAS_ADS_PREFIX = "ads:"        # ads:01us
KEY_ALIAS_KEEPA = "keepa"

# 心跳命名:amz-worker:{store}:{job}(最长 32 字符 < worker_name String(64))。
WORKER_NAME = "amz-worker"
AGENTS_WORKER_NAME = "amz-agents-worker"

SEED_KIND_ADS_SEARCH_TERMS = "ads_search_terms"
SEED_KIND_TRANSACTIONS = "transactions"

__all__ = [name for name in dir() if name.isupper()]
