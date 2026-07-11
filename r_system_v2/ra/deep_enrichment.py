"""利润通过者的深度富化：Keepa 12 个月历史 + Rainforest 全量深数据 + 差评主题。

只对利润硬门幸存者运行（每天几十个），补齐终审最饥渴的三类证据：
1. Keepa 历史（1 token）→ 12 个月 BSR 趋势、价格地板轨迹、历史长度、viral 嫌疑；
2. Rainforest type=product + type=reviews(critical)（~2 credits）→ 品牌/卖点/
   评分分布/变体 + 真实差评原文；
3. DeepSeek 提炼差评主题 → 反复被骂的点 = 差异化改款方向（开模层的金矿）。

结果按 ASIN 缓存 30 天；全部数据注入 GPT/Opus 上下文并展示在产品详情浮层。
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager
from r_system_v2.ra.profit_service import _is_postgres, _json_bind
from r_system_v2.ra.providers import RAnalysisProviderBinding
from r_system_v2.ra.quota_ledger import PROVIDER_RAINFOREST, try_consume

KEEPA_API_URL = "https://api.keepa.com/product"
KEEPA_EPOCH_OFFSET_MIN = 21_564_000  # keepaTime(分钟) → unix 的偏移
RECHECK_DAYS_DEFAULT = 30
CSV_NEW_PRICE = 1
CSV_SALES_RANK = 3


class RADeepEnrichmentError(RuntimeError):
    pass


def ensure_deep_schema(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ra_deep_enrichment (
              id TEXT PRIMARY KEY,
              org_id TEXT NOT NULL,
              asin TEXT NOT NULL,
              keepa JSONB NOT NULL DEFAULT '{}',
              rainforest_product JSONB NOT NULL DEFAULT '{}',
              reviews JSONB NOT NULL DEFAULT '[]',
              review_themes JSONB NOT NULL DEFAULT '{}',
              errors JSONB NOT NULL DEFAULT '{}',
              fetched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_ra_deep_enrichment_asin
            ON ra_deep_enrichment (org_id, asin, fetched_at DESC)
            """
        )
    )


def ensure_deep_enrichment(
    db: Session,
    *,
    org_id: str,
    asin: str,
) -> dict[str, Any]:
    """取（或生成）该 ASIN 的深度富化包；30 天缓存。失败字段留 error 不阻断。"""
    cleaned_asin = str(asin or "").strip().upper()
    if not cleaned_asin:
        return {}
    ensure_deep_schema(db)
    db.commit()  # DDL 立即落盘：后面的 rollback 不能吃掉建表。
    recheck_days = _env_int("RA_DEEP_RECHECK_DAYS", RECHECK_DAYS_DEFAULT, 1, 365)
    # 两档缓存：全成功 30 天；带错误的行只挡 1 天——差评端点恢复后次日自动补拉。
    no_errors_predicate = (
        "errors = '{}'::jsonb" if _is_postgres(db) else "errors IN ('{}', 'null')"
    )
    row = db.execute(
        text(
            f"""
            SELECT keepa, rainforest_product, reviews, review_themes, errors, fetched_at
            FROM ra_deep_enrichment
            WHERE org_id = :org_id AND asin = :asin
              AND (
                ({no_errors_predicate}
                 AND fetched_at > CURRENT_TIMESTAMP - INTERVAL '{recheck_days} days')
                OR fetched_at > CURRENT_TIMESTAMP - INTERVAL '1 day'
              )
            ORDER BY fetched_at DESC
            LIMIT 1
            """
        ),
        {"org_id": org_id, "asin": cleaned_asin},
    ).mappings().first()
    if row is not None:
        return {
            "keepa": row["keepa"] or {},
            "rainforest_product": row["rainforest_product"] or {},
            "reviews": row["reviews"] or [],
            "review_themes": row["review_themes"] or {},
            "errors": row["errors"] or {},
            "cache_hit": True,
            "fetched_at": str(row["fetched_at"]),
        }

    binding = RAnalysisProviderBinding(
        org_id=org_id, secret_manager=SecretManager(db_session=db)
    )
    errors: dict[str, str] = {}

    # 先把所有 key/凭据解析完（都是 DB 读），再统一结束事务，
    # 之后的外部 HTTP 要几十秒——不能让连接挂在 idle-in-transaction 上。
    keepa_key_value = ""
    try:
        keepa_key_value = binding.keepa_key().strip()
        if not keepa_key_value:
            errors["keepa"] = "Keepa key 为空。"
    except Exception as exc:
        errors["keepa"] = f"Keepa key 未绑定到 R-A：{exc}"[:300]

    rf_key = rf_base = ""
    try:
        from r_system_v2.ra.competition import RainforestClient

        client = RainforestClient.from_binding(db=db, org_id=org_id)
        rf_key, rf_base = client.api_key, client.base_url
        # 记账：product 1 + reviews 1（Rainforest 积分大量闲置，放心花）。
        # try_consume 内部自提交。
        try_consume(db, PROVIDER_RAINFOREST, amount=2)
    except Exception as exc:
        rf_key = ""
        errors["rainforest"] = str(exc)[:300]

    try:
        db.rollback()
    except Exception:
        pass

    keepa_block: dict[str, Any] = {}
    if keepa_key_value:
        try:
            keepa_block = _fetch_keepa_history(keepa_key_value, asin=cleaned_asin)
        except Exception as exc:
            errors["keepa"] = str(exc)[:300]

    product_block: dict[str, Any] = {}
    reviews_block: list[dict[str, Any]] = []
    if rf_key:
        try:
            product_block = _fetch_rainforest(
                rf_key, rf_base, {"type": "product", "asin": cleaned_asin}
            )
            product_block = _normalize_rainforest_product(product_block)
            raw_reviews = _fetch_rainforest(
                rf_key,
                rf_base,
                {
                    "type": "reviews",
                    "asin": cleaned_asin,
                    "review_stars": "all_critical",
                    "sort_by": "most_helpful",
                },
            )
            reviews_block = _normalize_reviews(raw_reviews)
        except Exception as exc:
            errors["rainforest"] = str(exc)[:300]

    themes_block: dict[str, Any] = {}
    if reviews_block:
        try:
            themes_block = _summarize_review_themes(
                db,
                org_id=org_id,
                reviews=reviews_block,
                product_title=str(product_block.get("title") or ""),
            )
        except Exception as exc:
            errors["review_themes"] = str(exc)[:300]

    db.execute(
        text(
            f"""
            INSERT INTO ra_deep_enrichment (
              id, org_id, asin, keepa, rainforest_product, reviews,
              review_themes, errors
            )
            VALUES (
              :id, :org_id, :asin, {_json_bind(db, "keepa")},
              {_json_bind(db, "rainforest_product")}, {_json_bind(db, "reviews")},
              {_json_bind(db, "review_themes")}, {_json_bind(db, "errors")}
            )
            """
        ),
        {
            "id": str(uuid4()),
            "org_id": org_id,
            "asin": cleaned_asin,
            "keepa": json.dumps(keepa_block, ensure_ascii=False, default=str),
            "rainforest_product": json.dumps(
                product_block, ensure_ascii=False, default=str
            ),
            "reviews": json.dumps(reviews_block, ensure_ascii=False, default=str),
            "review_themes": json.dumps(themes_block, ensure_ascii=False, default=str),
            "errors": json.dumps(errors, ensure_ascii=False, default=str),
        },
    )
    db.commit()
    return {
        "keepa": keepa_block,
        "rainforest_product": product_block,
        "reviews": reviews_block,
        "review_themes": themes_block,
        "errors": errors,
        "cache_hit": False,
        "fetched_at": datetime.now(UTC).isoformat(),
    }


# --------------------------------------------------------------- Keepa 部分
def _fetch_keepa_history(
    keepa_key: str,
    *,
    asin: str,
) -> dict[str, Any]:
    params = {
        "key": keepa_key,
        "domain": "1",
        "asin": asin,
        "stats": "365",
        "history": "1",
    }
    url = f"{KEEPA_API_URL}?{urlencode(params)}"
    parsed = _keepa_request_with_429_wait(url)
    products = parsed.get("products") or []
    if not products:
        raise RADeepEnrichmentError("Keepa 未返回产品数据。")
    return _analyze_keepa_product(products[0])


def _keepa_body_to_json(raw: bytes) -> dict[str, Any]:
    # Keepa 全部响应默认 gzip 压缩。
    if raw[:2] == b"\x1f\x8b":
        import gzip

        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8", errors="replace"))


def _keepa_request_with_429_wait(url: str) -> dict[str, Any]:
    """Keepa 429 = token 用尽：按响应里的 refillIn 等待补给后重试（老板指令）。"""
    last_error: Exception | None = None
    for attempt in range(4):
        request = Request(url, headers={"User-Agent": "barong-ra/1.0"})
        try:
            with urlopen(request, timeout=45) as response:
                return _keepa_body_to_json(response.read())
        except HTTPError as exc:
            raw_body = exc.read()
            try:
                body = json.dumps(_keepa_body_to_json(raw_body), ensure_ascii=False)
            except Exception:
                body = raw_body.decode("utf-8", errors="replace")
            last_error = RADeepEnrichmentError(
                f"Keepa 请求失败：HTTP {exc.code} {body[:200]}"
            )
            if exc.code == 429 and attempt < 3:
                refill_ms = 60_000
                try:
                    refill_ms = int(json.loads(body).get("refillIn") or 60_000)
                except Exception:
                    pass
                # 等待补给 +1s 余量；上限 70s，避免无限挂起。
                time.sleep(min(refill_ms / 1000 + 1, 70))
                continue
            raise last_error from exc
        except (URLError, TimeoutError) as exc:
            last_error = RADeepEnrichmentError(f"Keepa 网络失败：{exc}")
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise last_error from exc
    raise last_error or RADeepEnrichmentError("Keepa 请求失败。")


def _keepa_time_to_unix(keepa_minutes: int) -> int:
    return (int(keepa_minutes) + KEEPA_EPOCH_OFFSET_MIN) * 60


def _csv_series(csv_block: Any, index: int) -> list[tuple[int, float]]:
    """Keepa csv[index] = [keepaTime, value, keepaTime, value, ...]；-1 = 无值。"""
    if not isinstance(csv_block, list) or index >= len(csv_block):
        return []
    raw = csv_block[index]
    if not isinstance(raw, list):
        return []
    series: list[tuple[int, float]] = []
    for i in range(0, len(raw) - 1, 2):
        ts, value = raw[i], raw[i + 1]
        if value is None or value == -1:
            continue
        try:
            series.append((_keepa_time_to_unix(int(ts)), float(value)))
        except (TypeError, ValueError):
            continue
    return series


def _analyze_keepa_product(product: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    year_ago = now - 365 * 86400
    csv_block = product.get("csv")
    sales = [p for p in _csv_series(csv_block, CSV_SALES_RANK) if p[0] >= year_ago]
    prices = [
        (ts, value / 100.0)
        for ts, value in _csv_series(csv_block, CSV_NEW_PRICE)
        if ts >= year_ago
    ]
    all_sales = _csv_series(csv_block, CSV_SALES_RANK)
    history_days = (
        int((now - all_sales[0][0]) / 86400) if all_sales else 0
    )

    # BSR 12 个月趋势：前 1/3 时段均值 vs 后 1/3 时段均值（排名越小越好）。
    bsr_trend = "unknown"
    bsr_change_pct = None
    if len(sales) >= 6:
        third = max(1, len(sales) // 3)
        early = sum(v for _, v in sales[:third]) / third
        late = sum(v for _, v in sales[-third:]) / third
        if early > 0:
            bsr_change_pct = round((late - early) / early * 100, 1)
            bsr_trend = (
                "improving" if late < early * 0.8
                else "declining" if late > early * 1.25
                else "stable"
            )

    # 价格地板：月度最低价序列 → 首末季度对比。
    price_floor_declining = None
    price_floor_change_pct = None
    monthly_floor: dict[int, float] = {}
    for ts, price in prices:
        bucket = int(ts // (30 * 86400))
        if bucket not in monthly_floor or price < monthly_floor[bucket]:
            monthly_floor[bucket] = price
    floors = [monthly_floor[k] for k in sorted(monthly_floor)]
    if len(floors) >= 4:
        head = sum(floors[:3]) / min(3, len(floors))
        tail = sum(floors[-3:]) / min(3, len(floors))
        if head > 0:
            price_floor_change_pct = round((tail - head) / head * 100, 1)
            price_floor_declining = tail < head * 0.92

    min_price_12m = round(min((p for _, p in prices), default=0), 2) or None
    current_price = round(prices[-1][1], 2) if prices else None
    viral_suspect = bool(history_days and history_days < 180 and bsr_trend == "improving")

    return {
        "history_days": history_days,
        "has_12m_history": history_days >= 350,
        "bsr_trend_12m": bsr_trend,
        "bsr_change_pct_12m": bsr_change_pct,
        "price_floor_declining": price_floor_declining,
        "price_floor_change_pct_12m": price_floor_change_pct,
        "min_price_12m": min_price_12m,
        "current_new_price": current_price,
        "monthly_price_floors": [round(v, 2) for v in floors[-12:]],
        "viral_suspect": viral_suspect,
        "data_points": {"sales": len(sales), "prices": len(prices)},
        "source": "keepa_history_365",
    }


# ---------------------------------------------------------- Rainforest 部分
def _fetch_rainforest(
    api_key: str,
    base_url: str,
    params: dict[str, str],
) -> dict[str, Any]:
    query = {
        "api_key": api_key,
        "amazon_domain": "amazon.com",
        **params,
    }
    url = f"{base_url.rstrip('/')}/request?{urlencode(query)}"
    last_error: Exception | None = None
    for attempt in range(3):
        request = Request(url, headers={"User-Agent": "barong-ra/1.0"})
        try:
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            last_error = RADeepEnrichmentError(
                f"Rainforest {params.get('type')} 失败：HTTP {exc.code} {detail}"
            )
            if exc.code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise last_error from exc
        except (URLError, TimeoutError) as exc:
            last_error = RADeepEnrichmentError(f"Rainforest 网络失败：{exc}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise last_error from exc
    raise last_error or RADeepEnrichmentError("Rainforest 请求失败。")


def _normalize_rainforest_product(payload: dict[str, Any]) -> dict[str, Any]:
    """老板指令「能拿的数据全拿来」：product 响应里所有有决策价值的字段全收。"""
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    if not product:
        return {}
    breakdown = (
        product.get("rating_breakdown")
        if isinstance(product.get("rating_breakdown"), dict)
        else {}
    )
    rating_dist = {}
    for star in ("five_star", "four_star", "three_star", "two_star", "one_star"):
        entry = breakdown.get(star)
        if isinstance(entry, dict):
            rating_dist[star] = entry.get("percentage")
    categories = [
        str(c.get("name"))
        for c in (product.get("categories") or [])
        if isinstance(c, dict) and c.get("name")
    ]
    ranks = []
    for entry in product.get("bestsellers_rank") or []:
        if isinstance(entry, dict) and entry.get("rank"):
            ranks.append({"category": entry.get("category"), "rank": entry.get("rank")})
    buybox = (
        product.get("buybox_winner")
        if isinstance(product.get("buybox_winner"), dict)
        else {}
    )
    buybox_price = (
        _dig(buybox, "price", "value")
        or _dig(buybox, "new_offers_from", "value")
    )
    a_plus = (
        product.get("a_plus_content")
        if isinstance(product.get("a_plus_content"), dict)
        else {}
    )
    return {
        "title": product.get("title"),
        "brand": product.get("brand"),
        "manufacturer": product.get("manufacturer"),
        "model_number": product.get("model_number"),
        "rating": product.get("rating"),
        "ratings_total": product.get("ratings_total"),
        "rating_breakdown": rating_dist,
        # 亚马逊自报的「过去一个月购买量」：需求最硬的证据。
        "recent_sales": product.get("recent_sales"),
        "bestsellers_rank": ranks[:3],
        "buybox_price": buybox_price,
        "buybox_is_prime": buybox.get("is_prime"),
        "buybox_fulfillment": _dig(buybox, "fulfillment", "type"),
        "listing_keywords": str(product.get("keywords") or "")[:400] or None,
        "has_coupon": product.get("has_coupon"),
        "coupon_text": product.get("coupon_text"),
        "has_a_plus_content": bool(a_plus.get("has_a_plus_content")),
        "videos_count": product.get("videos_count"),
        "proposition_65_warning": product.get("proposition_65_warning"),
        "feature_bullets": (product.get("feature_bullets") or [])[:8],
        "categories": categories[:5],
        "variant_count": len(product.get("variants") or []),
        "parent_asin": product.get("parent_asin"),
        "images_count": product.get("images_count")
        or len(product.get("images") or []),
        "material": product.get("material"),
        "dimensions": product.get("dimensions"),
        "weight": product.get("weight"),
        "first_available": (product.get("first_available") or {}).get("raw")
        if isinstance(product.get("first_available"), dict)
        else None,
        "source": "rainforest_product",
    }


def _dig(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _normalize_reviews(payload: dict[str, Any]) -> list[dict[str, Any]]:
    reviews = payload.get("reviews") if isinstance(payload.get("reviews"), list) else []
    output = []
    for review in reviews[:8]:
        if not isinstance(review, dict):
            continue
        body = str(review.get("body") or "").strip()
        if not body:
            continue
        output.append(
            {
                "rating": review.get("rating"),
                "title": str(review.get("title") or "")[:120],
                "body": body[:600],
                "date": (review.get("date") or {}).get("raw")
                if isinstance(review.get("date"), dict)
                else review.get("date"),
                "verified": review.get("verified_purchase"),
            }
        )
    return output


# ------------------------------------------------------------ 差评主题提炼
def _summarize_review_themes(
    db: Session,
    *,
    org_id: str,
    reviews: list[dict[str, Any]],
    product_title: str,
) -> dict[str, Any]:
    from r_system_v2.ra.ai_selection import (
        _execute_chat_request,
        _load_provider_configs,
        _try_parse_model_json,
    )

    provider = _load_provider_configs(db, org_id=org_id)["deepseek"]
    corpus = [
        {"stars": r.get("rating"), "title": r.get("title"), "text": r.get("body")}
        for r in reviews[:8]
    ]
    prompt = (
        f"产品：{product_title[:100]}\n"
        f"以下是该产品在亚马逊的真实差评：{json.dumps(corpus, ensure_ascii=False)}\n\n"
        "任务：提炼差评主题。反复被抱怨的点 = 小卖家差异化改款的机会。\n"
        '只输出 JSON：{"top_complaints":[{"theme":"中文主题","evidence":"引用差评关键句",'
        '"improvement_angle":"可执行的改进方向"}],"severity":"high|medium|low",'
        '"differentiation_summary":"一句话：改什么就能打赢"}\n'
        "top_complaints 按出现频率排序，最多 5 条。"
    )
    try:
        db.rollback()
    except Exception:
        pass
    response = _execute_chat_request(
        provider,
        spec={
            "endpoint": "/v1/chat/completions",
            "label": "review_themes",
            "payload": {
                "model": provider.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
        },
    )
    output = _try_parse_model_json(response.get("content")) or {}
    return {
        "top_complaints": (output.get("top_complaints") or [])[:5],
        "severity": output.get("severity"),
        "differentiation_summary": output.get("differentiation_summary"),
        "review_count_analyzed": len(corpus),
        "model": provider.model,
    }


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default
