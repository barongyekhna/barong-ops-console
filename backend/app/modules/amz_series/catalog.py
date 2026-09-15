"""四家公司、五个店铺的固定名单。org_id 一次生成后钉死(与 20260821_03 的吉林工厂 org_id 同一做法)。

02 号店(前厂长)不在名单里,永远不进 A 系列。
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import REGION_EU, REGION_NA


@dataclass(frozen=True)
class CompanySpec:
    org_id: str
    org_name: str
    short_name: str


@dataclass(frozen=True)
class StoreSpec:
    store_code: str
    company: CompanySpec
    display_name: str
    marketplace_id: str
    region: str
    country: str
    currency: str
    timezone: str


LONGJIE = CompanySpec("org_f94c68fd09674e92bd18fce64a4feab2", "广州龙杰电子商务有限公司", "龙杰")
LILIAN = CompanySpec("org_bc53f07f27594360b6dd85ea1e980ddc", "广州利连电子商务有限公司", "利连")
HUIXUE = CompanySpec("org_a26707563d7241a68c8459819de3cf4b", "广州会学电子商务有限公司", "会学")
YUZHOU = CompanySpec("org_efb94f960f6b40e9a0264fa02ba0675b", "广州宇州电子商务有限公司", "宇州")

COMPANIES: tuple[CompanySpec, ...] = (LONGJIE, LILIAN, HUIXUE, YUZHOU)

# 亚马逊 marketplace id:美国 ATVPDKIKX0DER,德国 A1PA6795UKMFR9。
STORES: tuple[StoreSpec, ...] = (
    StoreSpec("01us", LONGJIE, "龙杰 美国", "ATVPDKIKX0DER", REGION_NA, "US", "USD", "America/Los_Angeles"),
    StoreSpec("01de", LONGJIE, "龙杰 德国", "A1PA6795UKMFR9", REGION_EU, "DE", "EUR", "Europe/Berlin"),
    StoreSpec("03us", LILIAN, "利连 美国", "ATVPDKIKX0DER", REGION_NA, "US", "USD", "America/Los_Angeles"),
    StoreSpec("04us", HUIXUE, "会学 美国", "ATVPDKIKX0DER", REGION_NA, "US", "USD", "America/Los_Angeles"),
    StoreSpec("05us", YUZHOU, "宇州 美国", "ATVPDKIKX0DER", REGION_NA, "US", "USD", "America/Los_Angeles"),
)

STORE_CODES: tuple[str, ...] = tuple(store.store_code for store in STORES)
COMPANY_ORG_IDS: tuple[str, ...] = tuple(company.org_id for company in COMPANIES)

# 王创鑫(user_id=2)是五店的 grant;owner(user_id=1)天然全通,不需要行。
OWNER_USER_ID = 1
MANAGER_USER_ID = 2
# 四个机器人的主组织(users.organization_id)。四组织都有 membership,
# 多成员时 _resolve_org 走 users.organization_id 兜底,所以这里必须填。
AGENT_HOME_COMPANY = LONGJIE


def store_spec(store_code: str) -> StoreSpec | None:
    code = (store_code or "").strip().lower()
    for store in STORES:
        if store.store_code == code:
            return store
    return None


__all__ = [
    "AGENT_HOME_COMPANY",
    "COMPANIES",
    "COMPANY_ORG_IDS",
    "CompanySpec",
    "HUIXUE",
    "LILIAN",
    "LONGJIE",
    "MANAGER_USER_ID",
    "OWNER_USER_ID",
    "STORES",
    "STORE_CODES",
    "StoreSpec",
    "YUZHOU",
    "store_spec",
]
