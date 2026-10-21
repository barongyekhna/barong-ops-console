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
from typing import Any

from sqlalchemy import text

from .data_isolation import SKIP_ORG_DATA_ISOLATION

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
    from ..db.session import SessionLocal

    return SessionLocal()


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
) -> None:
    """记一次调用。失败的调用也记（token 为 0），这样「一天失败了多少次」也能查。"""
    usage = usage or AIUsage()
    cost = estimate_cost_usd(model, usage)
    db = None
    try:
        db = _session()
        db.execute(
            text(
                f"""
                INSERT INTO {_TABLE} (
                    usage_day, provider, model, module, task, org_ref,
                    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                    cost_usd, success, degraded, latency_ms, error_code
                ) VALUES (
                    (now() AT TIME ZONE 'UTC')::date, :provider, :model, :module, :task, :org_ref,
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
            execution_options=SKIP_ORG_DATA_ISOLATION,
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
            execution_options=SKIP_ORG_DATA_ISOLATION,
        ).scalar()
        return float(value or 0)
    except Exception:  # noqa: BLE001
        logger.exception("ai usage ledger read failed")
        return None
    finally:
        if db is not None:
            db.close()


def claude_budget_exhausted() -> bool:
    spent = claude_spend_today_usd()
    if spent is None:
        return True
    return spent >= claude_daily_budget_usd()
