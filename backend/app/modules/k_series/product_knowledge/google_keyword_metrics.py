"""K 关键词终筛后的谷歌指标富化。

终筛(Opus)选出的关键词,批量调 Google Ads Keyword Planner 的
historical metrics 接口拿真实月搜索量 / 竞争度 / CPC 区间。

- 一个产品一次批量调用(≤200 词),与 R-A 共用同一本额度台账
  (PROVIDER_GOOGLE_ADS_PLANNER,13500/天),额度尽则优雅降级。
- fail-safe:任何失败只留 trace,绝不阻塞关键词管线。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

GOOGLE_ADS_API_VERSION = "v24"
_MAX_KEYWORDS_PER_CALL = 200


def _credentials(db: Session) -> dict[str, Any]:
    from ...w_series.logistics import _target_org_id
    from r_system_v2.core.secret_manager import SecretManager

    org_id = _target_org_id(db)
    if not org_id:
        raise RuntimeError("目标组织不存在")
    return json.loads(SecretManager(db_session=db).get_key("google_ads", org_id))


def fetch_keyword_metrics(
    db: Session,
    keywords: list[str],
) -> dict[str, dict[str, Any]]:
    """批量取关键词历史指标;键为小写关键词。额度尽/失败抛异常由调用方兜底。"""

    cleaned = [k.strip() for k in keywords if k and k.strip()][:_MAX_KEYWORDS_PER_CALL]
    if not cleaned:
        return {}

    from r_system_v2.ra.quota_ledger import (
        PROVIDER_GOOGLE_ADS_PLANNER,
        try_consume,
    )

    try_consume(db, PROVIDER_GOOGLE_ADS_PLANNER, amount=1)
    # 注意:不做 rollback——K 工作流引擎调用本函数时正处于带未提交状态的
    # 事务中(R-A 那套出网前 rollback 在这里会炸掉管线半成品)。两跳 HTTP
    # 合计 <10s,短暂 idle-in-transaction 可接受。

    payload = _credentials(db)
    token_response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": payload["client_id"],
            "client_secret": payload["client_secret"],
            "refresh_token": payload["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    token_response.raise_for_status()
    access_token = token_response.json()["access_token"]

    customer_id = str(payload["customer_id"]).replace("-", "")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": payload["developer_token"],
        "Content-Type": "application/json",
    }
    login_customer_id = str(payload.get("login_customer_id") or "").replace("-", "")
    if login_customer_id:
        headers["login-customer-id"] = login_customer_id

    response = httpx.post(
        f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}/"
        f"customers/{customer_id}:generateKeywordHistoricalMetrics",
        headers=headers,
        timeout=40,
        json={
            "keywords": cleaned,
            "language": "languageConstants/1000",
            "geoTargetConstants": ["geoTargetConstants/2840"],
        },
    )
    response.raise_for_status()

    metrics: dict[str, dict[str, Any]] = {}
    for item in response.json().get("results", []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        raw = item.get("keywordMetrics")
        raw = raw if isinstance(raw, dict) else {}
        low = _int_or_none(raw.get("lowTopOfPageBidMicros"))
        high = _int_or_none(raw.get("highTopOfPageBidMicros"))
        metrics[text.lower()] = {
            "avg_monthly_searches": _int_or_none(raw.get("avgMonthlySearches")),
            "competition": raw.get("competition"),
            "competition_index": _int_or_none(raw.get("competitionIndex")),
            "cpc_low_usd": round(low / 1e6, 2) if low else None,
            "cpc_high_usd": round(high / 1e6, 2) if high else None,
        }
    return metrics


def metrics_reason_text(metric: dict[str, Any]) -> str:
    """一行人话:写进关键词行的 reason,列表页一眼可读。"""

    volume = metric.get("avg_monthly_searches")
    parts = [f"月搜 {volume:,}" if volume else "月搜 -"]
    if metric.get("competition"):
        parts.append(f"竞争 {metric['competition']}")
    low, high = metric.get("cpc_low_usd"), metric.get("cpc_high_usd")
    if low or high:
        parts.append(f"CPC ${low or 0}-{high or 0}")
    return "[Google] " + " · ".join(parts)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
