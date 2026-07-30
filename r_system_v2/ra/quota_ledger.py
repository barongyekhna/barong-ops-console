"""Daily provider quota ledger for R-A paid external calls.

Monthly quotas (1688 image search / Rainforest) are enforced as daily budgets
so a single run can never burn the month.  Consumption is recorded per
provider per UTC day; the worker asks the ledger *before* spending.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


PROVIDER_1688_IMAGE_SEARCH = "alibaba1688_image_search"
# ¥1500 图搜分销功能包：50 万次 / 6 个月（至 2027-01-17）→ ~2600/天 均匀吃满。
PROVIDER_1688_CPS_IMAGE_SEARCH = "alibaba1688_cps_image_search"
# 1688 应用全局调用总闸：测试期 5000/天（留余量 4500）；应用发布审核
# 通过后（10 万/天）把 RA_1688_APP_CALLS_DAILY_BUDGET 改 90000。
# 每个产品按 ~10 次 App 调用估算记账（词搜重试+图搜+供应商详情/运费探测）。
PROVIDER_1688_APP_CALLS = "alibaba1688_app_calls"
PROVIDER_RAINFOREST = "rainforest_search"
PROVIDER_SERPER = "serper_search"
# Google Ads Keyword Planner：Basic 套餐 15000 operations/天（2026-07-14 过审），
# 留余 10% 防撞顶（用户死命令：不要超）。
PROVIDER_GOOGLE_ADS_PLANNER = "google_ads_planner"
# F 系列独立 1688 总闸：全局 10 万/天中划 1 万给 F（用户 2026-07-14 拍板，
# R-A 用 9 万）。F 是低频人工触发功能，额度敞开用。
PROVIDER_F_1688_APP_CALLS = "f_1688_app_calls"
# F 图搜接力台账：只记数不设闸（用户 2026-07-14 拍板——F 半年用不上两次，
# 不限量；CPS credit 池的真正守门人是"凑够即停"early-stop）。
PROVIDER_F_1688_IMAGE_SEARCH = "f_1688_image_search"
# B2B 客户挖掘走 Serper 的 Places(谷歌地图)接口找实体店。独立额度桶,
# 不和 R-A/F 抢——它们是选品链路,断了影响上品;这条是获客,可以慢慢跑。
PROVIDER_B2B_SERPER_PLACES = "b2b_serper_places"
# B2B 客户筛选:补官网用的 Serper 网页搜索。和 places 分桶,方便看清
# 「抓店铺」和「筛店铺」各烧了多少。铁律:新出网付费调用当天接台账。
PROVIDER_B2B_SERPER_ENRICH = "b2b_serper_enrich"
# GEO 阵地监测:每条买家问句一次 Serper 自然搜索。按类目监测而非逐 SKU,
# 所以量随类目走不随产品数涨;新出网调用当天接台账(2026-07-22 Serper 事故的死规矩)。
PROVIDER_GEO_SERPER_MONITOR = "geo_serper_monitor"

# GEO 类目级选题深挖:一个类目一次约 15-25 发(种子 + PAA 二级展开)。
# 死规矩(Serper 烧光 5 万次那次换来的):新增出网付费调用**当天**接台账。
PROVIDER_GEO_SERPER_TOPICS = "geo_serper_topics"

DEFAULT_DAILY_BUDGETS = {
    PROVIDER_1688_IMAGE_SEARCH: 330,
    PROVIDER_1688_CPS_IMAGE_SEARCH: 2600,
    PROVIDER_1688_APP_CALLS: 4500,
    PROVIDER_RAINFOREST: 330,
    PROVIDER_SERPER: 2000,
    PROVIDER_GOOGLE_ADS_PLANNER: 13500,
    PROVIDER_F_1688_APP_CALLS: 10000,
    PROVIDER_F_1688_IMAGE_SEARCH: 0,
    PROVIDER_B2B_SERPER_PLACES: 1000,
    PROVIDER_B2B_SERPER_ENRICH: 500,
    # 一个类目一轮约 10-20 条问句,每周跑一次绰绰有余;
    # 上限压得低,是因为监测永远不该成为烧钱的那一路。
    PROVIDER_GEO_SERPER_MONITOR: 200,
    PROVIDER_GEO_SERPER_TOPICS: 300,
}

BUDGET_ENV_NAMES = {
    PROVIDER_1688_IMAGE_SEARCH: "RA_1688_IMAGE_SEARCH_DAILY_BUDGET",
    PROVIDER_1688_CPS_IMAGE_SEARCH: "RA_1688_CPS_IMAGE_SEARCH_DAILY_BUDGET",
    PROVIDER_1688_APP_CALLS: "RA_1688_APP_CALLS_DAILY_BUDGET",
    PROVIDER_RAINFOREST: "RA_RAINFOREST_DAILY_BUDGET",
    PROVIDER_SERPER: "RA_SERPER_DAILY_BUDGET",
    PROVIDER_GOOGLE_ADS_PLANNER: "RA_GOOGLE_ADS_PLANNER_DAILY_BUDGET",
    PROVIDER_F_1688_APP_CALLS: "F_1688_APP_CALLS_DAILY_BUDGET",
    PROVIDER_F_1688_IMAGE_SEARCH: "F_1688_IMAGE_SEARCH_DAILY_BUDGET",
    PROVIDER_B2B_SERPER_PLACES: "B2B_SERPER_DAILY_BUDGET",
    PROVIDER_B2B_SERPER_ENRICH: "B2B_SERPER_ENRICH_DAILY_BUDGET",
    PROVIDER_GEO_SERPER_MONITOR: "GEO_SERPER_MONITOR_DAILY_BUDGET",
    PROVIDER_GEO_SERPER_TOPICS: "GEO_SERPER_TOPICS_DAILY_BUDGET",
}


class RAQuotaExhaustedError(RuntimeError):
    """Raised when a paid provider's daily budget is used up."""

    def __init__(self, provider: str, *, used: int, budget: int) -> None:
        self.provider = provider
        self.used = used
        self.budget = budget
        super().__init__(
            f"今日 {provider_label(provider)} 预算已用完（{used}/{budget}），"
            "任务将暂停，明天自动继续。"
        )


def provider_label(provider: str) -> str:
    return {
        PROVIDER_1688_IMAGE_SEARCH: "1688 跨境图搜",
        PROVIDER_1688_CPS_IMAGE_SEARCH: "1688 分销图搜",
        PROVIDER_1688_APP_CALLS: "1688 应用总调用",
        PROVIDER_F_1688_APP_CALLS: "F系列 1688 找货",
        PROVIDER_F_1688_IMAGE_SEARCH: "F系列 CPS 图搜",
        PROVIDER_RAINFOREST: "Rainforest",
        PROVIDER_SERPER: "Serper",
        PROVIDER_GOOGLE_ADS_PLANNER: "Google Ads 关键词规划",
        PROVIDER_GEO_SERPER_MONITOR: "GEO 阵地监测",
        PROVIDER_GEO_SERPER_TOPICS: "GEO 选题深挖",
    }.get(provider, provider)


def daily_budget(provider: str) -> int:
    env_name = BUDGET_ENV_NAMES.get(provider)
    default = DEFAULT_DAILY_BUDGETS.get(provider, 0)
    if env_name:
        raw = os.getenv(env_name)
        if raw:
            try:
                return max(0, int(raw))
            except ValueError:
                return default
    return default


def ensure_quota_schema(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ra_provider_quota_usage (
              provider TEXT NOT NULL,
              day DATE NOT NULL,
              used INTEGER NOT NULL DEFAULT 0,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (provider, day)
            )
            """
        )
    )


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def try_consume(db: Session, provider: str, *, amount: int = 1) -> int:
    """Reserve `amount` units of today's budget.

    Returns the new `used` total, or raises RAQuotaExhaustedError when the
    daily budget cannot cover the request.  A budget of 0 means unlimited.
    """
    budget = daily_budget(provider)
    ensure_quota_schema(db)
    day = _today()
    db.execute(
        text(
            """
            INSERT INTO ra_provider_quota_usage (provider, day, used)
            VALUES (:provider, :day, 0)
            ON CONFLICT (provider, day) DO NOTHING
            """
        ),
        {"provider": provider, "day": day},
    )
    if budget <= 0:
        row = db.execute(
            text(
                """
                UPDATE ra_provider_quota_usage
                SET used = used + :amount, updated_at = CURRENT_TIMESTAMP
                WHERE provider = :provider AND day = :day
                RETURNING used
                """
            ),
            {"provider": provider, "day": day, "amount": amount},
        ).first()
        db.commit()
        return int(row[0]) if row else amount
    row = db.execute(
        text(
            """
            UPDATE ra_provider_quota_usage
            SET used = used + :amount, updated_at = CURRENT_TIMESTAMP
            WHERE provider = :provider AND day = :day AND used + :amount <= :budget
            RETURNING used
            """
        ),
        {"provider": provider, "day": day, "amount": amount, "budget": budget},
    ).first()
    if row is None:
        used_row = db.execute(
            text(
                """
                SELECT used FROM ra_provider_quota_usage
                WHERE provider = :provider AND day = :day
                """
            ),
            {"provider": provider, "day": day},
        ).first()
        db.commit()
        raise RAQuotaExhaustedError(
            provider,
            used=int(used_row[0]) if used_row else 0,
            budget=budget,
        )
    db.commit()
    return int(row[0])


def refund(db: Session, provider: str, *, amount: int = 1) -> None:
    """Return unused reserved units (e.g. the external call itself failed)."""
    ensure_quota_schema(db)
    db.execute(
        text(
            """
            UPDATE ra_provider_quota_usage
            SET used = GREATEST(0, used - :amount), updated_at = CURRENT_TIMESTAMP
            WHERE provider = :provider AND day = :day
            """
        ),
        {"provider": provider, "day": _today(), "amount": amount},
    )
    db.commit()


def usage_today(db: Session) -> dict[str, dict[str, Any]]:
    ensure_quota_schema(db)
    rows = db.execute(
        text(
            """
            SELECT provider, used FROM ra_provider_quota_usage
            WHERE day = :day
            """
        ),
        {"day": _today()},
    ).mappings()
    used_map = {str(row["provider"]): int(row["used"] or 0) for row in rows}
    payload: dict[str, dict[str, Any]] = {}
    for provider in (
        PROVIDER_1688_IMAGE_SEARCH,
        PROVIDER_1688_CPS_IMAGE_SEARCH,
        PROVIDER_1688_APP_CALLS,
        PROVIDER_F_1688_APP_CALLS,
        PROVIDER_F_1688_IMAGE_SEARCH,
        PROVIDER_RAINFOREST,
        PROVIDER_SERPER,
        PROVIDER_GOOGLE_ADS_PLANNER,
    ):
        budget = daily_budget(provider)
        used = used_map.get(provider, 0)
        payload[provider] = {
            "label": provider_label(provider),
            "used": used,
            "budget": budget,
            "remaining": max(0, budget - used) if budget > 0 else None,
            "unlimited": budget <= 0,
        }
    return payload


def remaining_today(db: Session, provider: str) -> int | None:
    """Remaining units today, or None when unlimited."""
    budget = daily_budget(provider)
    if budget <= 0:
        return None
    ensure_quota_schema(db)
    row = db.execute(
        text(
            """
            SELECT used FROM ra_provider_quota_usage
            WHERE provider = :provider AND day = :day
            """
        ),
        {"provider": provider, "day": _today()},
    ).first()
    used = int(row[0]) if row else 0
    return max(0, budget - used)
