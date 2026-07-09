"""R-A channel routing signals for Amazon, DTC ads, and DTC SEO.

The expensive AI chain still makes the final product-selection judgment.  This
module provides a deterministic evidence block so every candidate is classified
against the three R-series routes before the model sees it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.ra.profit_engine import decimal_value
from r_system_v2.ra.profit_service import _json_bind
from r_system_v2.ra.providers import RAnalysisProviderBinding, google_ads_runtime_gate


SERPER_SEARCH_URL = "https://google.serper.dev/search"
WEAK_SERP_DOMAINS = {
    "reddit.com",
    "quora.com",
    "forum",
    "forums",
    "stackexchange.com",
    "medium.com",
    "pinterest.com",
}
MARKETPLACE_DOMAINS = {
    "amazon.com",
    "walmart.com",
    "target.com",
    "homedepot.com",
    "lowes.com",
    "wayfair.com",
    "etsy.com",
    "ebay.com",
    "aliexpress.com",
}
BUYER_INTENT_TERMS = {
    "best",
    "buy",
    "for",
    "review",
    "reviews",
    "top",
    "vs",
    "alternative",
    "kit",
    "set",
}
VISUAL_HOOK_TERMS = {
    "portable",
    "foldable",
    "adjustable",
    "magnetic",
    "led",
    "decor",
    "organizer",
    "storage",
    "fan",
    "light",
    "tool",
    "cleaner",
    "rack",
    "holder",
    "camping",
    "outdoor",
    "pet",
}


def ensure_channel_signal_schema(db: Session) -> None:
    try:
        dialect = db.get_bind().dialect.name
    except Exception:
        dialect = "postgresql"
    json_type = "JSONB" if dialect == "postgresql" else "TEXT"
    timestamp_type = "TIMESTAMPTZ" if dialect == "postgresql" else "TEXT"
    db.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS ra_channel_signals (
              id TEXT PRIMARY KEY,
              org_id TEXT NOT NULL,
              run_id TEXT,
              candidate_id TEXT,
              asin TEXT,
              payload {json_type} NOT NULL DEFAULT '{{}}',
              provider_modes {json_type} NOT NULL DEFAULT '{{}}',
              created_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_ra_channel_signals_candidate
            ON ra_channel_signals (candidate_id, created_at)
            """
        )
    )


def ensure_channel_signals(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    context: dict[str, Any],
    competition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_channel_signal_schema(db)
    competition = competition or {}
    product = _dict_value(context.get("product"))
    profit = _dict_value(context.get("profit"))
    keyword = _keyword(product=product, competition=competition)
    serper_block = _serper_or_mock(db, org_id=org_id, keyword=keyword, product=product)
    keyword_planner_block = _google_keyword_planner_state(db, org_id=org_id)
    payload = {
        "version": "ra_channel_signals_v1",
        "keyword": keyword,
        "amazon": _amazon_signal(product=product, profit=profit, competition=competition),
        "dtc_ad": _dtc_ad_signal(product=product, profit=profit),
        "dtc_seo": _dtc_seo_signal(
            product=product,
            profit=profit,
            keyword=keyword,
            serper_block=serper_block,
            keyword_planner_block=keyword_planner_block,
        ),
        "provider_modes": {
            "amazon_competition": competition.get("source") or "rainforest_missing",
            "serper": serper_block.get("provider_mode"),
            "meta_ad_library": "mock_missing_provider",
            "tiktok_ads": "mock_missing_provider",
            "google_keyword_planner": keyword_planner_block.get("provider_mode"),
            "google_trends": "mock_missing_provider",
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
    payload["primary_route"] = _primary_route(payload)
    _insert_channel_signals(db, org_id=org_id, run_id=run_id, context=context, payload=payload)
    return payload


def _insert_channel_signals(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    context: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    db.execute(
        text(
            f"""
            INSERT INTO ra_channel_signals (
              id, org_id, run_id, candidate_id, asin, payload, provider_modes
            )
            VALUES (
              :id, :org_id, :run_id, :candidate_id, :asin,
              {_json_bind(db, "payload")}, {_json_bind(db, "provider_modes")}
            )
            """
        ),
        {
            "id": str(uuid4()),
            "org_id": org_id,
            "run_id": run_id,
            "candidate_id": context.get("candidate_id"),
            "asin": context.get("asin"),
            "payload": json.dumps(payload, ensure_ascii=False),
            "provider_modes": json.dumps(payload.get("provider_modes") or {}, ensure_ascii=False),
        },
    )


def _amazon_signal(
    *,
    product: dict[str, Any],
    profit: dict[str, Any],
    competition: dict[str, Any],
) -> dict[str, Any]:
    features = _dict_value(product.get("features"))
    score = 40
    reasons: list[str] = []
    risks: list[str] = []
    price = decimal_value(product.get("price") or profit.get("sell_price_usd"))
    margin = decimal_value(profit.get("gross_margin"))
    monthly_sales = _int_value(
        features.get("monthly_sales_value")
        or features.get("monthly_sales_estimate")
        or features.get("monthly_sales")
    )
    if price is not None and Decimal("25") <= price <= Decimal("70"):
        score += 13
        reasons.append("售价处于 Amazon 25-70 美金主力区间。")
    else:
        risks.append("售价不在 Amazon 主力价格带。")
    if margin is not None and margin >= Decimal("0.25"):
        score += 14
        reasons.append("利润率达到 Amazon 继续验证线。")
    elif margin is not None:
        score -= 8
        risks.append("利润率偏低，抗 PPC/退货能力不足。")
    if monthly_sales and monthly_sales >= 200:
        score += 12
        reasons.append(f"月销量约 {monthly_sales}，需求已被 Keepa/BSR 验证。")
    elif monthly_sales:
        score += 4
        risks.append(f"月销量约 {monthly_sales}，需求规模需复核。")
    review_wall = _int_value(competition.get("review_wall_max"))
    if review_wall is not None and review_wall <= 500:
        score += 10
        reasons.append("页一评论墙相对可攻。")
    elif review_wall is not None:
        score -= 8
        risks.append("页一评论墙偏高。")
    brand_share = decimal_value(competition.get("single_brand_share"))
    if brand_share is not None and brand_share <= Decimal("0.30"):
        score += 6
        reasons.append("单品牌集中度未明显锁死。")
    market_sellers = _int_value(competition.get("market_seller_count_est"))
    if market_sellers is not None and 3 <= market_sellers <= 20:
        score += 5
        reasons.append("页一自然位竞争样本数量适中。")
    return _signal(
        score=score,
        pass_score=70,
        review_score=55,
        label="亚马逊",
        reasons=reasons,
        risks=risks,
        provider_mode=str(competition.get("source") or "rainforest_missing"),
    )


def _dtc_ad_signal(*, product: dict[str, Any], profit: dict[str, Any]) -> dict[str, Any]:
    features = _dict_value(product.get("features"))
    title = _text_blob(product)
    score = 35
    reasons: list[str] = []
    risks: list[str] = []
    margin = decimal_value(profit.get("gross_margin"))
    price = decimal_value(product.get("price") or profit.get("sell_price_usd"))
    if margin is not None and margin >= Decimal("0.60"):
        score += 22
        reasons.append("毛利率达到 DTC 广告品 60% 生存线。")
    elif margin is not None and margin >= Decimal("0.50"):
        score += 8
        risks.append("毛利率接近广告品下限，CAC 空间紧。")
    else:
        score -= 10
        risks.append("毛利不足以支撑冷启动广告 CAC。")
    if price is not None and Decimal("25") <= price <= Decimal("65"):
        score += 10
        reasons.append("售价处于 DTC 冲动购买区间。")
    hook_hits = [term for term in VISUAL_HOOK_TERMS if term in title]
    if hook_hits:
        score += min(18, 6 + len(hook_hits) * 3)
        reasons.append("标题包含可演示/视觉化卖点，适合短视频验证。")
    else:
        risks.append("缺少明确 3 秒视觉钩子，广告适配度偏弱。")
    weight_g = _number(features.get("package_weight_g") or features.get("item_weight_g"))
    if weight_g is not None and weight_g <= 1200:
        score += 5
        reasons.append("重量相对友好，履约风险较低。")
    return _signal(
        score=score,
        pass_score=75,
        review_score=58,
        label="独立站广告",
        reasons=reasons,
        risks=risks,
        provider_mode="mock_missing_meta_ad_library",
    )


def _dtc_seo_signal(
    *,
    product: dict[str, Any],
    profit: dict[str, Any],
    keyword: str,
    serper_block: dict[str, Any],
    keyword_planner_block: dict[str, Any],
) -> dict[str, Any]:
    features = _dict_value(product.get("features"))
    score = 35
    reasons: list[str] = []
    risks: list[str] = []
    margin = decimal_value(profit.get("gross_margin"))
    monthly_sales = _int_value(
        features.get("monthly_sales_value")
        or features.get("monthly_sales_estimate")
        or features.get("monthly_sales")
    )
    if margin is not None and margin >= Decimal("0.40"):
        score += 14
        reasons.append("毛利率达到 SEO 路径 40% 下限。")
    elif margin is not None:
        score -= 8
        risks.append("毛利率低于 SEO 路径安全线。")
    if monthly_sales and monthly_sales >= 200:
        score += 10
        reasons.append("Amazon 侧需求已验证，可作为 SEO 迁移种子。")
    query_tokens = _keyword_tokens(keyword)
    if any(term in query_tokens for term in BUYER_INTENT_TERMS) or len(query_tokens) >= 2:
        score += 8
        reasons.append("关键词具备买家意图或可拓成长尾内容。")
    serp_score = _int_value(serper_block.get("serp_weakness_score"))
    if serp_score is not None:
        score += round((serp_score - 50) * 0.35)
        if serp_score >= 65:
            reasons.append("Serper 显示 Google 页一存在 SEO 可攻空位。")
        else:
            risks.append("Google 页一不算明显弱 SERP。")
    else:
        risks.append("缺少真实 Serper/Keyword Planner 搜索量数据。")
    if keyword_planner_block.get("runtime_status") == "pending_basic_review":
        risks.append("Google Ads Keyword Planner 已绑定但 Basic 审核待通过，搜索量 / CPC 暂不启用。")
    elif not keyword_planner_block.get("runtime_enabled"):
        risks.append("缺少 Google Ads Keyword Planner 搜索量 / CPC 数据。")
    signal = _signal(
        score=score,
        pass_score=68,
        review_score=54,
        label="独立站 SEO",
        reasons=reasons,
        risks=risks,
        provider_mode=str(serper_block.get("provider_mode") or "mock_missing_serper"),
    )
    signal["serp"] = serper_block
    signal["keyword_planner"] = keyword_planner_block
    return signal


def _serper_or_mock(
    db: Session,
    *,
    org_id: str,
    keyword: str,
    product: dict[str, Any],
) -> dict[str, Any]:
    try:
        key = RAnalysisProviderBinding(
            org_id=org_id,
            secret_manager=SecretManager(db_session=db),
        ).serper_key()
    except SecretManagerError:
        key = ""
    if not key:
        return _mock_serp(keyword=keyword, product=product, reason="serper_key_missing")
    raw = _serper_search(api_key=key, keyword=keyword)
    return _serp_signal_from_response(raw, keyword=keyword, provider_mode="real_serper")


def _google_keyword_planner_state(db: Session, *, org_id: str) -> dict[str, Any]:
    try:
        configured = bool(
            RAnalysisProviderBinding(
                org_id=org_id,
                secret_manager=SecretManager(db_session=db),
            ).google_ads_key()
        )
        source = "api_key_orchestration"
    except SecretManagerError:
        configured = False
        source = "api_key_orchestration_missing"
    gate = google_ads_runtime_gate(configured=configured)
    return {
        "provider_mode": gate["routing"],
        "configured": configured,
        "source": source,
        "review_status": gate["review_status"],
        "runtime_status": gate["runtime_status"],
        "runtime_enabled": gate["runtime_enabled"],
        "detail": gate["detail"],
        "avg_monthly_searches": None,
        "competition_index": None,
        "cpc_low_micros": None,
        "cpc_high_micros": None,
    }


def _serper_search(*, api_key: str, keyword: str) -> dict[str, Any]:
    payload = {"q": keyword, "gl": "us", "hl": "en", "num": 10}
    request = Request(
        os.getenv("RA_SERPER_SEARCH_URL", SERPER_SEARCH_URL),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-KEY": api_key},
        method="POST",
    )
    try:
        with urlopen(request, timeout=_serper_timeout_seconds()) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Serper 请求失败：HTTP {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Serper 网络失败：{exc.reason}") from exc
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise RuntimeError("Serper 返回结构异常。")
    return parsed


def _serp_signal_from_response(
    raw: dict[str, Any],
    *,
    keyword: str,
    provider_mode: str,
) -> dict[str, Any]:
    organic = raw.get("organic") if isinstance(raw.get("organic"), list) else []
    domains: list[str] = []
    weak = 0
    marketplace = 0
    for item in organic[:10]:
        if not isinstance(item, dict):
            continue
        domain = _domain(item.get("link"))
        if not domain:
            continue
        domains.append(domain)
        if _is_weak_domain(domain):
            weak += 1
        if _is_marketplace_domain(domain):
            marketplace += 1
    has_shopping = bool(raw.get("shopping"))
    score = _clamp_int(52 + weak * 10 + marketplace * 3 + (6 if has_shopping else 0), 0, 100)
    return {
        "provider_mode": provider_mode,
        "keyword": keyword,
        "serp_weakness_score": score,
        "serp_top_domains": domains[:10],
        "serp_has_forums": weak > 0,
        "serp_has_shopping": has_shopping,
        "weak_surface_count": weak,
        "marketplace_count": marketplace,
        "result_count": len(organic),
        "source": "serper_search",
    }


def _mock_serp(*, keyword: str, product: dict[str, Any], reason: str) -> dict[str, Any]:
    title = _text_blob(product)
    long_tail = len(_keyword_tokens(keyword)) >= 2
    score = 58 + (8 if long_tail else 0) + (5 if "for" in title else 0)
    return {
        "provider_mode": "mock_missing_serper",
        "keyword": keyword,
        "serp_weakness_score": _clamp_int(score, 0, 100),
        "serp_top_domains": [],
        "serp_has_forums": None,
        "serp_has_shopping": None,
        "weak_surface_count": None,
        "marketplace_count": None,
        "result_count": None,
        "source": "mock",
        "mock_reason": reason,
    }


def _signal(
    *,
    score: int,
    pass_score: int,
    review_score: int,
    label: str,
    reasons: list[str],
    risks: list[str],
    provider_mode: str,
) -> dict[str, Any]:
    bounded = _clamp_int(score, 0, 100)
    verdict = "pass" if bounded >= pass_score else "review" if bounded >= review_score else "reject"
    return {
        "label": label,
        "score": bounded,
        "verdict": verdict,
        "pass_score": pass_score,
        "provider_mode": provider_mode,
        "reasons": reasons[:6],
        "risks": risks[:6],
    }


def _primary_route(payload: dict[str, Any]) -> dict[str, Any]:
    routes = [
        ("amazon", _dict_value(payload.get("amazon"))),
        ("dtc_ad", _dict_value(payload.get("dtc_ad"))),
        ("dtc_seo", _dict_value(payload.get("dtc_seo"))),
    ]
    pass_routes = [(name, item) for name, item in routes if item.get("verdict") == "pass"]
    candidates = pass_routes or routes
    name, item = max(candidates, key=lambda pair: int(pair[1].get("score") or 0))
    return {
        "channel": name,
        "label": item.get("label") or name,
        "score": item.get("score"),
        "verdict": item.get("verdict"),
        "all_pass_channels": [route_name for route_name, route in pass_routes],
    }


def _keyword(*, product: dict[str, Any], competition: dict[str, Any]) -> str:
    for value in (
        competition.get("keyword"),
        product.get("source_query"),
        product.get("title"),
        product.get("title_zh"),
        product.get("category"),
    ):
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
        if cleaned and not re.fullmatch(r"B0[A-Z0-9]{8}|[A-Z0-9]{10}", cleaned.upper()):
            return cleaned[:120]
    return "product"


def _text_blob(product: dict[str, Any]) -> str:
    return " ".join(
        str(value or "").lower()
        for value in (
            product.get("title"),
            product.get("title_zh"),
            product.get("category"),
            product.get("source_query"),
        )
    )


def _keyword_tokens(keyword: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", keyword)}


def _domain(value: Any) -> str:
    parsed = urlparse(str(value or ""))
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_weak_domain(domain: str) -> bool:
    return any(pattern in domain for pattern in WEAK_SERP_DOMAINS)


def _is_marketplace_domain(domain: str) -> bool:
    return any(domain == value or domain.endswith(f".{value}") for value in MARKETPLACE_DOMAINS)


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _clamp_int(value: int | float, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(round(value))))


def _serper_timeout_seconds() -> float:
    try:
        return max(3.0, min(float(os.getenv("RA_DTC_SERPER_TIMEOUT_SECONDS", "10")), 30.0))
    except ValueError:
        return 10.0
