"""AI 调用台账：每一次出网的大模型调用记一行 token 和美元。

**为什么需要这个**（2026-10-21 换血）：
此前路由只记一条 `ai_provider.execute` 事件（模型、耗时），token 和钱一概不记；
R-A / R-W / F / K 的直连调用连事件都没有。家规「出网付费调用当天接台账」在 AI 这条线上
从来没兑现过。换到 Claude 官方 API 以后，Max 订阅每月送的 $200 额度当期清零、
用超了自动降级给 DeepSeek（用户 10-21 拍板），这两件事都要求「今天已经花了多少」
是一个能查的数，而不是估计。

**设计取舍**：
- 表里没有 ``org_id`` 列。C18G 数据隔离会按会话组织自动过滤带这列的模型，而台账要
  跨组织汇总（Claude 额度是整个 Console 组织共用的一个池）。归属组织记在 ``org_ref``。
- 写台账用自己开的短会话，不借调用方的 session —— 调用方可能正处在一个要回滚的事务里，
  也可能根本没有 session（R-A 的直连）。
- 写不进去**绝不影响业务**：台账挂了是台账的事。但预算闸读不到今天的花费时按「已经
  用完」处理（降级给 DeepSeek），宁可少用 Claude，也不能在看不见账的时候放开花。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from time import monotonic
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

_TABLE = "ai_usage_ledger"

# 每百万 token 的美元价（输入 / 输出 / 缓存读 / 缓存写）。
# Claude 取自 platform.claude.com 价目页（2026-10-19 抓）；缓存写按输入价 1.25 倍。
# DeepSeek flash 取官方高峰价（低谷 $0.15/$0.60），按保守口径算；缓存命中按输入价一成估。
# 价格变了改这里，或用环境变量 AI_PRICE_<模型名大写、横杠换下划线>="入,出" 覆盖。
_PRICES_PER_MTOK: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "deepseek-flash": (0.30, 1.20, 0.03, 0.30),
}

CLAUDE_PROVIDER = "claude"


@dataclass(frozen=True)
class AIUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def usage_from_response(response: dict[str, Any]) -> AIUsage:
    """从供应商回包里读 token 数。Anthropic 和 OpenAI 兼容口（DeepSeek）字段名不同。"""
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return AIUsage()

    def _int(name: str) -> int:
        try:
            return max(0, int(usage.get(name) or 0))
        except (TypeError, ValueError):
            return 0

    if "input_tokens" in usage or "output_tokens" in usage:
        return AIUsage(
            input_tokens=_int("input_tokens"),
            output_tokens=_int("output_tokens"),
            cache_read_tokens=_int("cache_read_input_tokens"),
            cache_write_tokens=_int("cache_creation_input_tokens"),
        )
    # OpenAI 兼容口：prompt_tokens 含缓存命中部分，DeepSeek 另给 prompt_cache_hit_tokens。
    cache_hit = _int("prompt_cache_hit_tokens")
    return AIUsage(
        input_tokens=max(0, _int("prompt_tokens") - cache_hit),
        output_tokens=_int("completion_tokens"),
        cache_read_tokens=cache_hit,
    )


def price_per_mtok(model: str | None) -> tuple[float, float, float, float] | None:
    name = (model or "").strip()
    override = os.getenv("AI_PRICE_" + name.upper().replace("-", "_").replace(".", "_"), "").strip()
    if override:
        try:
            parts = [float(part) for part in override.split(",")]
        except ValueError:
            parts = []
        if len(parts) >= 2:
            cache_read = parts[2] if len(parts) > 2 else parts[0] * 0.1
            cache_write = parts[3] if len(parts) > 3 else parts[0] * 1.25
            return (parts[0], parts[1], cache_read, cache_write)
    return _PRICES_PER_MTOK.get(name)


def estimate_cost_usd(model: str | None, usage: AIUsage) -> float | None:
    """没有价目的模型返回 None（台账里记空，不瞎填 0）。"""
    prices = price_per_mtok(model)
    if prices is None:
        return None
    input_price, output_price, cache_read_price, cache_write_price = prices
    return (
        usage.input_tokens * input_price
        + usage.output_tokens * output_price
        + usage.cache_read_tokens * cache_read_price
        + usage.cache_write_tokens * cache_write_price
    ) / 1_000_000


def claude_daily_budget_usd() -> float:
    """Claude 每天的花费上限。默认 $6.4：Max 送的 $200 / 31 天，留一点余量。"""
    try:
        return max(0.0, float(os.getenv("AI_CLAUDE_DAILY_BUDGET_USD", "6.4")))
    except ValueError:
        return 6.4


def _session():
    # 数据库层和隔离层都在用到时才导入:R-W/R-A worker 先导入的是本模块,
    # 顶层导入 data_isolation 会和 db.session 形成循环导入,worker 一启动就崩(2026-10-21 发版踩到)。
    from ..db.session import SessionLocal

    return SessionLocal()


def _skip_isolation() -> dict[str, Any]:
    from .data_isolation import SKIP_ORG_DATA_ISOLATION

    return SKIP_ORG_DATA_ISOLATION


def record_ai_usage(
    *,
    provider: str,
    model: str | None,
    module: str,
    task: str,
    usage: AIUsage | None = None,
    success: bool = True,
    degraded: bool = False,
    latency_ms: float | None = None,
    org_ref: str | None = None,
    error_code: str | None = None,
    key_id: str | None = None,
) -> None:
    """记一次调用。失败的调用也记（token 为 0），这样「一天失败了多少次」也能查。

    ``key_id``:用的哪把钥匙(11-02 起两把 Claude 钥匙按动态配额分,见 claude_budget_overview)。
    直连调用方和历史行没有,算到默认钥匙头上。
    """
    usage = usage or AIUsage()
    cost = estimate_cost_usd(model, usage)
    db = None
    try:
        db = _session()
        db.execute(
            text(
                f"""
                INSERT INTO {_TABLE} (
                    usage_day, provider, model, module, task, org_ref, key_id,
                    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                    cost_usd, success, degraded, latency_ms, error_code
                ) VALUES (
                    (now() AT TIME ZONE 'UTC')::date, :provider, :model, :module, :task, :org_ref, :key_id,
                    :input_tokens, :output_tokens, :cache_read_tokens, :cache_write_tokens,
                    :cost_usd, :success, :degraded, :latency_ms, :error_code
                )
                """
            ),
            {
                "provider": provider[:32],
                "model": (model or "")[:96],
                "module": (module or "")[:64],
                "task": (task or "")[:64],
                "org_ref": (org_ref or None) and org_ref[:64],
                "key_id": (key_id or None) and key_id[:40],
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
                "cache_write_tokens": usage.cache_write_tokens,
                "cost_usd": cost,
                "success": success,
                "degraded": degraded,
                "latency_ms": int(latency_ms) if latency_ms is not None else None,
                "error_code": (error_code or None) and error_code[:64],
            },
            execution_options=_skip_isolation(),
        )
        db.commit()
    except Exception:  # noqa: BLE001
        # 台账写不进去绝不能把业务拖下水；但要留痕，不能悄悄吞掉。
        if db is not None:
            db.rollback()
        logger.exception("ai usage ledger write failed: %s %s %s", provider, model, module)
    finally:
        if db is not None:
            db.close()


def claude_spend_today_usd() -> float | None:
    """今天（UTC）Claude 已经花了多少美元。读不到返回 None，由调用方按「已用完」处理。"""
    db = None
    try:
        db = _session()
        value = db.execute(
            text(
                f"""
                SELECT COALESCE(SUM(cost_usd), 0) FROM {_TABLE}
                WHERE usage_day = (now() AT TIME ZONE 'UTC')::date AND provider = :provider
                """
            ),
            {"provider": CLAUDE_PROVIDER},
            execution_options=_skip_isolation(),
        ).scalar()
        return float(value or 0)
    except Exception:  # noqa: BLE001
        logger.exception("ai usage ledger read failed")
        return None
    finally:
        if db is not None:
            db.close()


def _legacy_claude_budget_exhausted() -> bool:
    spent = claude_spend_today_usd()
    if spent is None:
        return True
    return spent >= claude_daily_budget_usd()


# ---------------------------------------------------------------------------
# 两把钥匙按动态配额分(2026-11-02,老板拍板)
#
# 每把 Claude 钥匙都是一笔「当期清零」的月额度(桌面账号 $200/18 日重置,控制台账号 $100/11 日重置)。
# 不浪费 = 到重置日刚好花完;不超标 = 月中不能花光。做法:
#   当天可花 = (月额度 × (1 − 保留比例) − 本期到昨天为止已花) ÷ 本期剩余天数(含今天)
# 每天重算:前面省了后面自动放宽,前面花多了后面自动收紧。调用时挑「今天还剩得多」的钥匙,两把都到顶才降级。
# 额度和重置日在表 ai_key_budgets 里,改表不改代码。表里一行都没有时退回老的 AI_CLAUDE_DAILY_BUDGET_USD 总闸。
# ---------------------------------------------------------------------------

_BUDGET_TABLE = "ai_key_budgets"
_OVERVIEW_TTL_SECONDS = 10.0
_overview_cache: tuple[float, dict[str, Any] | None] | None = None


@dataclass(frozen=True)
class KeyBudget:
    key_id: str
    name: str
    monthly_usd: float
    reset_day: int
    reserve_pct: int
    is_default: bool


def cycle_bounds(reset_day: int, today: date) -> tuple[date, date]:
    """本期 [start, end):start 是今天或之前最近的一个重置日,end 是下一个重置日。reset_day 1–28。"""
    day = min(max(int(reset_day), 1), 28)
    if today.day >= day:
        start = today.replace(day=day)
    else:
        first = today.replace(day=1)
        prev_month_last = first - timedelta(days=1)
        start = prev_month_last.replace(day=day)
    year, month = (start.year + (start.month // 12), start.month % 12 + 1)
    end = date(year, month, day)
    return start, end


def allowance_today(*, monthly_usd: float, reserve_pct: int, spent_before_today: float, days_left: int) -> float:
    """今天可以花多少:把「还能花的」平均到剩余天数(含今天)。"""
    usable = monthly_usd * (1 - max(0, min(int(reserve_pct), 50)) / 100) - max(0.0, spent_before_today)
    return max(0.0, usable) / max(1, int(days_left))


def key_status(
    budget: KeyBudget,
    *,
    spent_cycle: float,
    spent_today: float,
    today: date,
    avg_daily_recent: float | None = None,
) -> dict[str, Any]:
    start, end = cycle_bounds(budget.reset_day, today)
    days_left = (end - today).days
    allowance = allowance_today(
        monthly_usd=budget.monthly_usd,
        reserve_pct=budget.reserve_pct,
        spent_before_today=spent_cycle - spent_today,
        days_left=days_left,
    )
    remaining = max(0.0, budget.monthly_usd - spent_cycle)
    # 「按现在的速度,到重置日会剩多少」:最近几天的日均 × 剩余天数。剩得多 = 要浪费
    projected_leftover = None
    if avg_daily_recent is not None:
        projected_leftover = max(0.0, remaining - avg_daily_recent * days_left)
    idle = days_left <= 5 and budget.monthly_usd > 0 and remaining / budget.monthly_usd >= 0.30
    return {
        "key_id": budget.key_id,
        "name": budget.name,
        "monthly_usd": round(budget.monthly_usd, 2),
        "reset_day": budget.reset_day,
        "cycle_start": start.isoformat(),
        "cycle_end": end.isoformat(),
        "days_left": days_left,
        "spent_cycle_usd": round(spent_cycle, 4),
        "spent_today_usd": round(spent_today, 4),
        "remaining_usd": round(remaining, 2),
        "allowance_today_usd": round(allowance, 4),
        "headroom_today_usd": round(allowance - spent_today, 4),
        "avg_daily_recent_usd": None if avg_daily_recent is None else round(avg_daily_recent, 4),
        "projected_leftover_usd": None if projected_leftover is None else round(projected_leftover, 2),
        "idle_warning": bool(idle),
        "is_default": budget.is_default,
    }


def pick_key(statuses: list[dict[str, Any]], preferred: str | None = None) -> str | None:
    """挑今天还剩得最多的钥匙;都没剩就 None。平手优先 preferred(模块本来绑的那把)。"""
    live = [s for s in statuses if float(s.get("headroom_today_usd") or 0) > 0]
    if not live:
        return None
    best = max(float(s["headroom_today_usd"]) for s in live)
    tied = [s["key_id"] for s in live if abs(float(s["headroom_today_usd"]) - best) < 1e-9]
    if preferred in tied:
        return preferred
    return tied[0]


def load_key_budgets(db: Any, provider: str = CLAUDE_PROVIDER) -> list[KeyBudget]:
    rows = db.execute(
        text(
            f"""
            SELECT b.key_id, COALESCE(k.name, b.key_id) AS name, b.monthly_usd, b.reset_day, b.reserve_pct, b.is_default
            FROM {_BUDGET_TABLE} b
            LEFT JOIN api_key_records k ON k.key_id = b.key_id AND k.deleted_at IS NULL AND k.status = 'active'
            WHERE b.provider = :provider AND k.key_id IS NOT NULL
            ORDER BY b.is_default DESC, b.key_id
            """
        ),
        {"provider": provider},
        execution_options=_skip_isolation(),
    ).all()
    return [KeyBudget(str(r[0]), str(r[1]), float(r[2]), int(r[3]), int(r[4]), bool(r[5])) for r in rows]


def _spend(db: Any, *, provider: str, key_ids: list[str], default_key_id: str | None, since: date, today: date) -> dict[str, dict[str, float]]:
    """每把钥匙:本期已花、今天已花、最近 7 天日均。key_id 为空的行算默认钥匙。"""
    rows = db.execute(
        text(
            f"""
            SELECT COALESCE(key_id, :default_key) AS k,
                   COALESCE(SUM(cost_usd), 0) AS cycle_usd,
                   COALESCE(SUM(CASE WHEN usage_day = :today THEN cost_usd ELSE 0 END), 0) AS today_usd,
                   COALESCE(SUM(CASE WHEN usage_day >= :recent_from AND usage_day < :today THEN cost_usd ELSE 0 END), 0) AS recent_usd
            FROM {_TABLE}
            WHERE provider = :provider AND usage_day >= :since
            GROUP BY 1
            """
        ),
        {"provider": provider, "default_key": default_key_id or "", "today": today, "since": since, "recent_from": today - timedelta(days=7)},
        execution_options=_skip_isolation(),
    ).all()
    out = {k: {"cycle": 0.0, "today": 0.0, "recent_avg": 0.0} for k in key_ids}
    for k, cycle_usd, today_usd, recent_usd in rows:
        if k in out:
            out[k] = {"cycle": float(cycle_usd or 0), "today": float(today_usd or 0), "recent_avg": float(recent_usd or 0) / 7.0}
    return out


def claude_budget_overview(*, today: date | None = None, db: Any = None, use_cache: bool = True) -> dict[str, Any] | None:
    """两把钥匙各自的额度状态。读不到返回 None(调用方按「用完」处理)。
    表里没有预算行 → mode=legacy,只给老总闸的数;有 → mode=dynamic。"""
    global _overview_cache
    now = monotonic()
    if use_cache and today is None and db is None and _overview_cache and now - _overview_cache[0] < _OVERVIEW_TTL_SECONDS:
        return _overview_cache[1]
    today = today or datetime.now(UTC).date()
    own = db is None
    try:
        db = db or _session()
        budgets = load_key_budgets(db)
        if not budgets:
            spent = claude_spend_today_usd()
            if spent is None:
                return None
            cap = claude_daily_budget_usd()
            overview = {"mode": "legacy", "keys": [], "total_spent_today_usd": round(spent, 4), "total_allowance_today_usd": cap, "exhausted": spent >= cap, "idle_warnings": []}
        else:
            default_key = next((b.key_id for b in budgets if b.is_default), budgets[0].key_id)
            since = min(cycle_bounds(b.reset_day, today)[0] for b in budgets) - timedelta(days=7)
            spend = _spend(db, provider=CLAUDE_PROVIDER, key_ids=[b.key_id for b in budgets], default_key_id=default_key, since=since, today=today)
            statuses = []
            for b in budgets:
                start, _ = cycle_bounds(b.reset_day, today)
                s = spend[b.key_id]
                # cycle 花费只算本期:上面的 since 为了日均多拉了几天,这里不用它(它只影响 recent_avg);本期从 start 起
                cycle_usd = _cycle_spend(db, key_id=b.key_id, default_key_id=default_key, start=start, today=today)
                statuses.append(key_status(b, spent_cycle=cycle_usd, spent_today=s["today"], today=today, avg_daily_recent=s["recent_avg"]))
            overview = {
                "mode": "dynamic",
                "keys": statuses,
                "total_spent_today_usd": round(sum(s["spent_today_usd"] for s in statuses), 4),
                "total_allowance_today_usd": round(sum(s["allowance_today_usd"] for s in statuses), 4),
                "exhausted": pick_key(statuses) is None,
                "idle_warnings": [{"key_id": s["key_id"], "name": s["name"], "remaining_usd": s["remaining_usd"], "days_left": s["days_left"]} for s in statuses if s["idle_warning"]],
            }
        if use_cache and own:
            _overview_cache = (now, overview)
        return overview
    except Exception:  # noqa: BLE001
        logger.exception("ai key budget overview read failed")
        return None
    finally:
        if own and db is not None:
            db.close()


def _cycle_spend(db: Any, *, key_id: str, default_key_id: str, start: date, today: date) -> float:
    value = db.execute(
        text(
            f"""
            SELECT COALESCE(SUM(cost_usd), 0) FROM {_TABLE}
            WHERE provider = :provider AND usage_day >= :start AND usage_day <= :today
              AND COALESCE(key_id, :default_key) = :key_id
            """
        ),
        {"provider": CLAUDE_PROVIDER, "start": start, "today": today, "default_key": default_key_id, "key_id": key_id},
        execution_options=_skip_isolation(),
    ).scalar()
    return float(value or 0)


def claude_budget_exhausted() -> bool:
    """Claude 还能不能用:动态模式下两把钥匙今天都没剩才算用完;读不到按用完。"""
    overview = claude_budget_overview()
    if overview is None:
        return True
    if overview.get("mode") == "legacy":
        return _legacy_claude_budget_exhausted()
    return bool(overview.get("exhausted"))


def pick_claude_key(candidate_key_ids: list[str], preferred: str | None = None) -> str | None:
    """路由用:候选钥匙里挑今天还剩得多的。legacy 模式(没预算表)→ 没用完就用 preferred;用完 → None。
    动态模式下不在预算表里的候选不参加(没登记额度的钥匙不知道能花多少)。"""
    overview = claude_budget_overview()
    if overview is None:
        return None
    if overview.get("mode") == "legacy":
        return None if _legacy_claude_budget_exhausted() else (preferred or (candidate_key_ids[0] if candidate_key_ids else None))
    statuses = [s for s in overview["keys"] if s["key_id"] in set(candidate_key_ids)]
    return pick_key(statuses, preferred)


def invalidate_budget_cache() -> None:
    global _overview_cache
    _overview_cache = None
