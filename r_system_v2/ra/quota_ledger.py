"""Daily provider quota ledger for R-A paid external calls.

Monthly quotas (1688 image search / Rainforest) are enforced as daily budgets
so a single run can never burn the month.  Consumption is recorded per
provider per UTC day; the worker asks the ledger *before* spending.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
import math
import os
import threading
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


# 跨境图搜（alibaba.cross.similar.offer.search）：约 5000 次的一次性套餐，
# 2026-07-24 打完最后一次，09-05 起远端只回 gw.NoUsageLeftError。用户拍板不续，
# 默认通道列表里没有它（RA_1688_IMAGE_CHANNELS），台账常量留着以便切回。
PROVIDER_1688_IMAGE_SEARCH = "alibaba1688_image_search"
# ¥1500 图搜分销功能包：50 万次 / 6 个月（至 2027-01-17）。日额度不再写死，
# 按「包总量 − 台账累计 ÷ 到期剩余天数 × 余量系数」每天推算（见 cps_dynamic_daily_budget）。
PROVIDER_1688_CPS_IMAGE_SEARCH = "alibaba1688_cps_image_search"
# 1688 应用全局调用总闸：2026-07-11 发布审核通过，正式额度 10 万/天，留余 10%。
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

# 数字员工(白苏婉)在 C19 通讯里的每次 DeepSeek 调用。常驻聊天没有天然的
# 调用次数上界——人聊多久就烧多久,所以照死规矩当天接台账。先只记数不设闸
# (预算 0 = 不限量),看两周真实用量再决定要不要封顶;现在就设一个拍脑袋的
# 上限,只会在老板正问话时把她掐哑,那比多花几块钱糟得多。
PROVIDER_AGENT_CHAT = "agent_chat_deepseek"
# 霓旌(制造库管员)的聊天调用,同上:单独一桶,先只记数。
PROVIDER_AGENT_CHAT_NIJING = "agent_chat_nijing_deepseek"
# 殷承岳(贸易公司产品助理)的聊天调用:一次判类目 = 两次 flash,同上单独一桶,先只记数。
PROVIDER_AGENT_CHAT_YINCHENGYUE = "agent_chat_yinchengyue_deepseek"
# SM 社媒写手(DeepSeek 生成一条帖子 = 1 次)。新出网付费调用当天接台账(铁律)。
# 默认 200/天:mock 期四周日历满打满算约 150 格,够一次性写完还留余量。
PROVIDER_SM_WRITER = "sm_writer_deepseek"

DEFAULT_DAILY_BUDGETS = {
    PROVIDER_1688_IMAGE_SEARCH: 330,
    # 只在拿不到 db（无法查台账累计）时的兜底；正常路径走动态推算。
    PROVIDER_1688_CPS_IMAGE_SEARCH: 2600,
    PROVIDER_1688_APP_CALLS: 90000,
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
    PROVIDER_AGENT_CHAT: 0,
    PROVIDER_AGENT_CHAT_NIJING: 0,
    PROVIDER_AGENT_CHAT_YINCHENGYUE: 0,
    PROVIDER_SM_WRITER: 200,
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
    PROVIDER_AGENT_CHAT: "AGENT_CHAT_DAILY_BUDGET",
    PROVIDER_AGENT_CHAT_NIJING: "NIJING_CHAT_DAILY_BUDGET",
    PROVIDER_AGENT_CHAT_YINCHENGYUE: "YINCHENGYUE_CHAT_DAILY_BUDGET",
    PROVIDER_SM_WRITER: "SM_WRITER_DAILY_BUDGET",
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
        PROVIDER_B2B_SERPER_PLACES: "B2B 客户挖掘",
        PROVIDER_B2B_SERPER_ENRICH: "B2B 客户筛选",
        PROVIDER_AGENT_CHAT: "白苏婉对话",
        PROVIDER_AGENT_CHAT_NIJING: "霓旌对话",
        PROVIDER_AGENT_CHAT_YINCHENGYUE: "殷承岳对话",
        PROVIDER_SM_WRITER: "SM 社媒写手",
    }.get(provider, provider)


# ---------------------------------------------------------------- 图搜通道
# 图搜走哪些通道、按什么顺序。默认只走分销包（cps）；要临时切回双通道就配
# RA_1688_IMAGE_CHANNELS="cps,cross"。未知名字一律忽略，空配置回落默认。
IMAGE_CHANNEL_PROVIDERS = {
    "cps": PROVIDER_1688_CPS_IMAGE_SEARCH,
    "cross": PROVIDER_1688_IMAGE_SEARCH,
}
DEFAULT_IMAGE_CHANNELS: tuple[str, ...] = ("cps",)


def image_search_channels() -> tuple[str, ...]:
    raw = os.getenv("RA_1688_IMAGE_CHANNELS", "")
    channels: list[str] = []
    for item in raw.split(","):
        name = item.strip().lower()
        if name in IMAGE_CHANNEL_PROVIDERS and name not in channels:
            channels.append(name)
    return tuple(channels) or DEFAULT_IMAGE_CHANNELS


def image_search_providers() -> tuple[str, ...]:
    return tuple(IMAGE_CHANNEL_PROVIDERS[channel] for channel in image_search_channels())


# ------------------------------------------------------- 分销包动态日额度
# 分销包是「总量 + 到期日」型套餐，不是月配额。日额度 = 剩余量 ÷ 剩余天数 × 余量
# 系数：前面用得少后面自动放大，永远不会在到期前把包剩下。台账只记本系统
# 打过的次数，包外消耗（台账上线前/对账差额）用 RA_1688_CPS_PACKAGE_USED_OFFSET 补。
CPS_PACKAGE_TOTAL_ENV = "RA_1688_CPS_PACKAGE_TOTAL"
CPS_PACKAGE_EXPIRES_ENV = "RA_1688_CPS_PACKAGE_EXPIRES_ON"
CPS_PACKAGE_USED_OFFSET_ENV = "RA_1688_CPS_PACKAGE_USED_OFFSET"
CPS_BUDGET_MARGIN_ENV = "RA_1688_CPS_BUDGET_MARGIN"
DEFAULT_CPS_PACKAGE_TOTAL = 500_000
DEFAULT_CPS_PACKAGE_EXPIRES_ON = "2027-01-17"
DEFAULT_CPS_BUDGET_MARGIN = 0.9
# 所有吃分销包 credit 的台账桶（R-A 主通道 + F 找货图搜接力）。
CPS_POOL_PROVIDERS: tuple[str, ...] = (
    PROVIDER_1688_CPS_IMAGE_SEARCH,
    PROVIDER_F_1688_IMAGE_SEARCH,
)

_cps_budget_cache: dict[str, int] = {}
_cps_budget_lock = threading.Lock()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def cps_package_expires_on() -> date:
    raw = os.getenv(CPS_PACKAGE_EXPIRES_ENV, "").strip() or DEFAULT_CPS_PACKAGE_EXPIRES_ON
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return date.fromisoformat(DEFAULT_CPS_PACKAGE_EXPIRES_ON)


def cps_pool_used_before(db: Session, day: str) -> int:
    """台账里分销包 credit 在 `day` 之前（不含当天）的累计消耗。"""
    ensure_quota_schema(db)
    row = db.execute(
        text(
            """
            SELECT COALESCE(SUM(used), 0)
            FROM ra_provider_quota_usage
            WHERE day < :day AND provider IN :providers
            """
        ).bindparams(bindparam("providers", expanding=True)),
        {"day": day, "providers": list(CPS_POOL_PROVIDERS)},
    ).first()
    return int(row[0] or 0) if row else 0


def cps_package_summary(db: Session, *, today: date | None = None) -> dict[str, Any]:
    """分销包账面：总量 / 已用 / 剩余 / 剩余天数 / 今日推算额度。"""
    current = today or datetime.now(UTC).date()
    total = max(0, _int_env(CPS_PACKAGE_TOTAL_ENV, DEFAULT_CPS_PACKAGE_TOTAL))
    offset = max(0, _int_env(CPS_PACKAGE_USED_OFFSET_ENV, 0))
    margin = min(1.0, max(0.1, _float_env(CPS_BUDGET_MARGIN_ENV, DEFAULT_CPS_BUDGET_MARGIN)))
    expires_on = cps_package_expires_on()
    ledger_used = cps_pool_used_before(db, current.isoformat())
    remaining = max(0, total - offset - ledger_used)
    # 含今天：到期当天仍可用。
    days_left = (expires_on - current).days + 1
    if days_left <= 0 or remaining <= 0:
        # 0 在这张台账里是「不限量」，到期/用尽必须给一个会被拒的正数。
        budget = 1
    else:
        budget = max(1, math.floor(remaining / days_left * margin))
    return {
        "total": total,
        "used_offset": offset,
        "ledger_used": ledger_used,
        "remaining": remaining,
        "expires_on": expires_on.isoformat(),
        "days_left": max(0, days_left),
        "margin": margin,
        "daily_budget": budget,
    }


def cps_dynamic_daily_budget(db: Session) -> int:
    """今天的分销图搜额度；一天算一次缓存在进程里，当天用量不影响当天额度。"""
    day = _today()
    with _cps_budget_lock:
        cached = _cps_budget_cache.get(day)
    if cached is not None:
        return cached
    budget = int(cps_package_summary(db)["daily_budget"])
    with _cps_budget_lock:
        _cps_budget_cache.clear()
        _cps_budget_cache[day] = budget
    return budget


def daily_budget(provider: str, db: Session | None = None) -> int:
    env_name = BUDGET_ENV_NAMES.get(provider)
    default = DEFAULT_DAILY_BUDGETS.get(provider, 0)
    if env_name:
        raw = os.getenv(env_name)
        if raw:
            try:
                return max(0, int(raw))
            except ValueError:
                return default
    if provider == PROVIDER_1688_CPS_IMAGE_SEARCH and db is not None:
        try:
            return cps_dynamic_daily_budget(db)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
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
    budget = daily_budget(provider, db)
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
            SET used = CASE WHEN used - :amount < 0 THEN 0 ELSE used - :amount END,
                updated_at = CURRENT_TIMESTAMP
            WHERE provider = :provider AND day = :day
            """
        ),
        {"provider": provider, "day": _today(), "amount": amount},
    )
    db.commit()


def mark_exhausted_today(db: Session, provider: str) -> int:
    """远端说「没额度了」时把今天本地台账直接记满。

    本地台账只数自己打过的次数，看不见供应商那头的套餐余量；失败又会退款，
    结果就是台账永远 0/N、永远不切通道（2026-09-05 跨境图搜就是这样空转
    了三天）。记满之后当天后续 try_consume 本地就拒，UI 也诚实显示 N/N。
    预算 0（不限量）没有「满」可记，原样返回。
    """
    budget = daily_budget(provider, db)
    if budget <= 0:
        return 0
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
    db.execute(
        text(
            """
            UPDATE ra_provider_quota_usage
            SET used = CASE WHEN used < :budget THEN :budget ELSE used END,
                updated_at = CURRENT_TIMESTAMP
            WHERE provider = :provider AND day = :day
            """
        ),
        {"provider": provider, "day": day, "budget": budget},
    )
    db.commit()
    return budget


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
    active_image_providers = set(image_search_providers())
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
        if provider in IMAGE_CHANNEL_PROVIDERS.values() and provider not in active_image_providers:
            # 不在通道列表里的图搜通道不出芯片，免得 UI 挂一个永远 0/330 的死牌。
            continue
        budget = daily_budget(provider, db)
        used = used_map.get(provider, 0)
        payload[provider] = {
            "label": provider_label(provider),
            "used": used,
            "budget": budget,
            "remaining": max(0, budget - used) if budget > 0 else None,
            "unlimited": budget <= 0,
        }
        if provider == PROVIDER_1688_CPS_IMAGE_SEARCH:
            try:
                payload[provider]["package"] = cps_package_summary(db)
            except Exception:
                pass
    return payload


def remaining_today(db: Session, provider: str) -> int | None:
    """Remaining units today, or None when unlimited."""
    budget = daily_budget(provider, db)
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
