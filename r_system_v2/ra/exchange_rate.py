"""USD/CNY exchange-rate provider for R-A profit calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
import os
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from r_system_v2.ra.profit_engine import DEFAULT_USD_CNY_RATE, decimal_value


DEFAULT_EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/USD"
DEFAULT_CACHE_SECONDS = 30 * 60
FALLBACK_CACHE_SECONDS = 5 * 60


@dataclass(frozen=True)
class ExchangeRateQuote:
    rate: Decimal
    source: str
    fetched_at: str | None
    live: bool
    warning: str | None = None


_CACHE: tuple[float, ExchangeRateQuote] | None = None


def get_usd_cny_quote(*, force_refresh: bool = False) -> ExchangeRateQuote:
    """Return a cached live USD/CNY quote, falling back safely when unavailable."""

    global _CACHE
    now = time.monotonic()
    if _CACHE is not None and not force_refresh and _CACHE[0] > now:
        return _CACHE[1]

    static_rate = decimal_value(os.getenv("RA_USD_CNY_RATE"))
    live_enabled = os.getenv("RA_EXCHANGE_RATE_LIVE_ENABLED", "1").strip().lower()
    if live_enabled in {"0", "false", "no", "off"}:
        quote = ExchangeRateQuote(
            rate=static_rate or DEFAULT_USD_CNY_RATE,
            source="env_static",
            fetched_at=None,
            live=False,
            warning="实时汇率已关闭，使用环境变量或默认汇率。",
        )
        _CACHE = (now + DEFAULT_CACHE_SECONDS, quote)
        return quote

    try:
        quote = _fetch_live_quote()
    except Exception as exc:
        quote = ExchangeRateQuote(
            rate=static_rate or DEFAULT_USD_CNY_RATE,
            source="fallback",
            fetched_at=None,
            live=False,
            warning=f"实时汇率获取失败，已使用备用汇率：{exc}",
        )
        _CACHE = (now + FALLBACK_CACHE_SECONDS, quote)
        return quote

    _CACHE = (now + DEFAULT_CACHE_SECONDS, quote)
    return quote


def _fetch_live_quote() -> ExchangeRateQuote:
    url = os.getenv("RA_EXCHANGE_RATE_URL", DEFAULT_EXCHANGE_RATE_URL)
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "barong-r-a-profit/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=1.8) as response:
            payload = response.read(1_000_000).decode("utf-8", errors="replace")
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("汇率接口返回非 JSON 内容") from exc

    rate = _extract_cny_rate(data)
    if rate is None or rate <= 0:
        raise RuntimeError("汇率接口未返回 CNY 汇率")
    return ExchangeRateQuote(
        rate=rate,
        source=url,
        fetched_at=datetime.now(UTC).isoformat(),
        live=True,
    )


def _extract_cny_rate(data: Any) -> Decimal | None:
    if not isinstance(data, dict):
        return None

    rates = data.get("rates")
    if isinstance(rates, dict):
        parsed = decimal_value(rates.get("CNY"))
        if parsed is not None:
            return parsed

    conversion_rates = data.get("conversion_rates")
    if isinstance(conversion_rates, dict):
        parsed = decimal_value(conversion_rates.get("CNY"))
        if parsed is not None:
            return parsed

    parsed = decimal_value(data.get("CNY") or data.get("cny"))
    return parsed
