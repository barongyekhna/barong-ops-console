"""Rainforest competition enrichment for R-A AI selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import os
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.ra.profit_service import _json_bind
from r_system_v2.ra.providers import RAnalysisProviderBinding
from r_system_v2.ra.quota_ledger import (
    PROVIDER_RAINFOREST,
    RAQuotaExhaustedError,
    refund,
    try_consume,
)


DEFAULT_RAINFOREST_BASE_URL = "https://api.rainforestapi.com"
DEFAULT_RAINFOREST_RECHECK_DAYS = 30
DEFAULT_NEW_REVIEW_THRESHOLD = 50
DEFAULT_RAINFOREST_TIMEOUT_SECONDS = 40


class RACompetitionError(RuntimeError):
    pass


def ensure_ra_competition_schema(db: Session) -> None:
    """Create the R-A competition cache table when migrations have not run yet."""

    try:
        dialect = db.get_bind().dialect.name
    except Exception:
        dialect = "postgresql"
    json_type = "JSONB" if dialect == "postgresql" else "TEXT"
    timestamp_type = "TIMESTAMPTZ" if dialect == "postgresql" else "TEXT"
    db.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS ra_competition_snapshots (
              id TEXT PRIMARY KEY,
              org_id TEXT NOT NULL,
              asin TEXT,
              keyword TEXT NOT NULL,
              top3_review_count {json_type} NOT NULL DEFAULT '[]',
              review_wall_max INTEGER,
              single_brand_share NUMERIC(6, 4),
              dominant_brand TEXT,
              new_entrant_ratio_est NUMERIC(6, 4),
              page_one_sample {json_type} NOT NULL DEFAULT '[]',
              mode TEXT NOT NULL DEFAULT 'cheap',
              credits_used INTEGER,
              source TEXT NOT NULL DEFAULT 'rainforest_search',
              payload {json_type} NOT NULL DEFAULT '{{}}',
              fetched_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_ra_competition_snapshots_cache
            ON ra_competition_snapshots (org_id, keyword, mode, fetched_at)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_ra_competition_snapshots_asin
            ON ra_competition_snapshots (asin)
            """
        )
    )


def ensure_competition_snapshot(
    db: Session,
    *,
    org_id: str,
    context: dict[str, Any],
    keyword: str | None = None,
) -> dict[str, Any]:
    ensure_ra_competition_schema(db)
    keyword_info = _competition_keyword(context, keyword=keyword)
    cleaned_keyword = keyword_info["keyword"]
    mode = _rainforest_mode()
    cached = _load_cached_snapshot(
        db,
        org_id=org_id,
        keyword=cleaned_keyword,
        mode=mode,
    )
    if cached is not None:
        return {**cached, "cache_hit": True, "credits_used_this_call": 0}

    db.commit()
    try:
        client = RainforestClient.from_binding(db=db, org_id=org_id)
        db.commit()
        # search = 2 credits；缓存未命中才走到这里，先向日预算账本记账。
        try_consume(db, PROVIDER_RAINFOREST, amount=2)
        try:
            raw = client.search(keyword=cleaned_keyword)
        except Exception:
            refund(db, PROVIDER_RAINFOREST, amount=2)
            raise
        snapshot = _snapshot_from_rainforest(
            raw,
            org_id=org_id,
            asin=str(context.get("asin") or ""),
            keyword=cleaned_keyword,
            keyword_source=keyword_info["source"],
            mode=mode,
            context=context,
        )
    except RAQuotaExhaustedError as exc:
        # 预算耗尽不是数据错误：缺竞争数据不误杀，产品照进 AI 链。
        snapshot = _failure_snapshot(
            org_id=org_id,
            asin=str(context.get("asin") or ""),
            keyword=cleaned_keyword,
            keyword_source=keyword_info["source"],
            mode=mode,
            error=str(exc),
        )
        snapshot["source"] = "rainforest_budget_exhausted"
    except Exception as exc:
        snapshot = _failure_snapshot(
            org_id=org_id,
            asin=str(context.get("asin") or ""),
            keyword=cleaned_keyword,
            keyword_source=keyword_info["source"],
            mode=mode,
            error=str(exc),
        )
    _insert_snapshot(db, snapshot)
    return {**snapshot, "cache_hit": False, "credits_used_this_call": snapshot.get("credits_used")}


class RainforestClient:
    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        self.api_key = api_key.strip()
        self.base_url = (base_url or DEFAULT_RAINFOREST_BASE_URL).rstrip("/")
        if not self.api_key:
            raise RACompetitionError("Rainforest key 未绑定。")

    @classmethod
    def from_binding(cls, *, db: Session, org_id: str) -> "RainforestClient":
        binding = RAnalysisProviderBinding(
            org_id=org_id,
            secret_manager=SecretManager(db_session=db),
        )
        try:
            config = binding.rainforest_config()
        except SecretManagerError as exc:
            raise RACompetitionError("Rainforest key 未绑定。") from exc
        parsed = _secret_payload(str(config.get("value") or ""))
        key = (
            str(parsed.get("api_key") or parsed.get("key") or parsed.get("token") or "").strip()
            or str(config.get("value") or "").strip()
        )
        base_url = (
            str(parsed.get("base_url") or parsed.get("baseUrl") or "").strip()
            or str(config.get("url") or "").strip()
            or os.getenv("RAINFOREST_BASE_URL", "").strip()
            or DEFAULT_RAINFOREST_BASE_URL
        )
        return cls(api_key=key, base_url=base_url)

    def search(self, *, keyword: str) -> dict[str, Any]:
        params = {
            "api_key": self.api_key,
            "type": "search",
            "amazon_domain": "amazon.com",
            "search_term": keyword,
        }
        url = f"{self.base_url}/request?{urlencode(params)}"
        last_error: Exception | None = None
        for attempt in range(3):
            request = Request(
                url,
                method="GET",
                headers={"Accept": "application/json", "User-Agent": "barong-ra/1.0"},
            )
            try:
                with urlopen(request, timeout=_rainforest_timeout_seconds()) as response:
                    body = response.read().decode("utf-8", errors="replace")
                parsed = json.loads(body)
                if not isinstance(parsed, dict):
                    raise RACompetitionError("Rainforest 返回结构异常。")
                return parsed
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                last_error = RACompetitionError(f"Rainforest 请求失败：HTTP {exc.code} {detail}")
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = RACompetitionError(f"Rainforest 请求失败：{exc}")
            if attempt < 2:
                time.sleep(0.8 * (2**attempt))
        raise last_error or RACompetitionError("Rainforest 请求失败。")


def _load_cached_snapshot(
    db: Session,
    *,
    org_id: str,
    keyword: str,
    mode: str,
) -> dict[str, Any] | None:
    cutoff = datetime.now(UTC) - timedelta(days=_rainforest_recheck_days())
    row = db.execute(
        text(
            """
            SELECT id, org_id, asin, keyword, top3_review_count, review_wall_max,
                   single_brand_share, dominant_brand, new_entrant_ratio_est,
                   page_one_sample, mode, credits_used, source, payload, fetched_at
            FROM ra_competition_snapshots
            WHERE org_id = :org_id AND keyword = :keyword AND mode = :mode
              AND fetched_at >= :cutoff
              AND source = 'rainforest_search'
            ORDER BY fetched_at DESC
            LIMIT 1
            """
        ),
        {"org_id": org_id, "keyword": keyword, "mode": mode, "cutoff": cutoff},
    ).mappings().first()
    if row is None:
        return None
    return _snapshot_from_row(dict(row))


def _insert_snapshot(db: Session, snapshot: dict[str, Any]) -> None:
    db.execute(
        text(
            f"""
            INSERT INTO ra_competition_snapshots (
              id, org_id, asin, keyword, top3_review_count, review_wall_max,
              single_brand_share, dominant_brand, new_entrant_ratio_est,
              page_one_sample, mode, credits_used, source, payload, fetched_at
            )
            VALUES (
              :id, :org_id, :asin, :keyword, {_json_bind(db, "top3_review_count")},
              :review_wall_max, :single_brand_share, :dominant_brand,
              :new_entrant_ratio_est, {_json_bind(db, "page_one_sample")},
              :mode, :credits_used, :source, {_json_bind(db, "payload")},
              :fetched_at
            )
            """
        ),
        {
            "id": snapshot["id"],
            "org_id": snapshot["org_id"],
            "asin": snapshot.get("asin"),
            "keyword": snapshot["keyword"],
            "top3_review_count": json.dumps(
                snapshot.get("top3_review_count") or [],
                ensure_ascii=False,
            ),
            "review_wall_max": snapshot.get("review_wall_max"),
            "single_brand_share": _decimal_or_none(snapshot.get("single_brand_share")),
            "dominant_brand": snapshot.get("dominant_brand"),
            "new_entrant_ratio_est": _decimal_or_none(snapshot.get("new_entrant_ratio_est")),
            "page_one_sample": json.dumps(
                snapshot.get("page_one_sample") or [],
                ensure_ascii=False,
            ),
            "mode": snapshot.get("mode") or "cheap",
            "credits_used": snapshot.get("credits_used"),
            "source": snapshot.get("source") or "rainforest_search",
            "payload": json.dumps(snapshot.get("payload") or {}, ensure_ascii=False),
            "fetched_at": snapshot.get("fetched_at") or datetime.now(UTC),
        },
    )


def _snapshot_from_rainforest(
    raw: dict[str, Any],
    *,
    org_id: str,
    asin: str,
    keyword: str,
    keyword_source: str,
    mode: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    rows = raw.get("search_results")
    if not isinstance(rows, list):
        rows = []
    organic = [
        _organic_sample(item)
        for item in rows
        if isinstance(item, dict) and not bool(item.get("sponsored"))
    ]
    organic = [item for item in organic if item]
    expected_tokens = _expected_product_tokens(context=context, keyword=keyword)
    organic = [
        {
            **item,
            "relevance_score": _title_relevance_score(
                title=str(item.get("title") or ""),
                expected_tokens=expected_tokens,
            ),
        }
        for item in organic
    ]
    relevant_organic = [
        item
        for item in organic
        if int(item.get("relevance_score") or 0) >= _min_relevance_score(expected_tokens)
    ]
    organic_for_metrics = relevant_organic or organic
    top3_reviews = [int(item.get("ratings_total") or 0) for item in organic_for_metrics[:3]]
    brand_counts: dict[str, int] = {}
    for item in organic_for_metrics[:20]:
        brand = _infer_brand(str(item.get("title") or ""))
        brand_counts[brand] = brand_counts.get(brand, 0) + 1
    dominant_brand = None
    single_brand_share = None
    if brand_counts and organic_for_metrics:
        dominant_brand, dominant_count = sorted(
            brand_counts.items(),
            key=lambda value: value[1],
            reverse=True,
        )[0]
        single_brand_share = round(dominant_count / max(1, len(organic_for_metrics[:20])), 4)
        if dominant_brand == "generic":
            dominant_brand = None
    threshold = _new_review_threshold()
    new_count = sum(
        1 for item in organic_for_metrics[:20] if int(item.get("ratings_total") or 0) < threshold
    )
    new_ratio = round(new_count / max(1, len(organic_for_metrics[:20])), 4) if organic_for_metrics else None
    request_info = raw.get("request_info") if isinstance(raw.get("request_info"), dict) else {}
    valid = _competition_result_valid(
        expected_tokens=expected_tokens,
        organic=organic,
        relevant_organic=relevant_organic,
    )
    invalid_reason = None if valid else "Rainforest 返回结果与产品核心关键词弱相关，竞品数据不可直接用于淘汰。"
    non_generic_brands = {brand for brand in brand_counts if brand and brand != "generic"}
    return {
        "id": str(uuid4()),
        "org_id": org_id,
        "asin": asin or None,
        "keyword": keyword,
        "top3_review_count": top3_reviews,
        "review_wall_max": max(top3_reviews) if top3_reviews else None,
        "single_brand_share": single_brand_share,
        "dominant_brand": dominant_brand,
        "new_entrant_ratio_est": new_ratio,
        "page_one_sample": organic_for_metrics[:10],
        "mode": mode,
        "credits_used": _int_or_none(request_info.get("credits_used")),
        "source": "rainforest_search" if valid else "rainforest_search_invalid",
        "payload": {
            "request_info": request_info,
            "total_results": raw.get("total_results"),
            "organic_count": len(organic),
            "relevant_organic_count": len(relevant_organic),
            "valid": valid,
            "invalid_reason": invalid_reason,
            "keyword_source": keyword_source,
            "expected_tokens": expected_tokens,
            "market_seller_count_est": len(organic_for_metrics[:20]),
            "market_brand_count_est": len(non_generic_brands),
            "new_review_threshold": threshold,
        },
        "competition_data_valid": valid,
        "competition_invalid_reason": invalid_reason,
        "market_seller_count_est": len(organic_for_metrics[:20]),
        "market_brand_count_est": len(non_generic_brands),
        "keyword_source": keyword_source,
        "fetched_at": datetime.now(UTC),
    }


def _failure_snapshot(
    *,
    org_id: str,
    asin: str,
    keyword: str,
    keyword_source: str,
    mode: str,
    error: str,
) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "org_id": org_id,
        "asin": asin or None,
        "keyword": keyword,
        "top3_review_count": [],
        "review_wall_max": None,
        "single_brand_share": None,
        "dominant_brand": None,
        "new_entrant_ratio_est": None,
        "page_one_sample": [],
        "mode": mode,
        "credits_used": 0,
        "source": "rainforest_error",
        "payload": {
            "error": error[:500],
            "valid": False,
            "keyword_source": keyword_source,
        },
        "competition_data_valid": False,
        "competition_invalid_reason": error[:500],
        "market_seller_count_est": None,
        "market_brand_count_est": None,
        "keyword_source": keyword_source,
        "fetched_at": datetime.now(UTC),
    }


def _snapshot_from_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = _json_value(row.get("payload"))
    return {
        "id": row.get("id"),
        "org_id": row.get("org_id"),
        "asin": row.get("asin"),
        "keyword": row.get("keyword"),
        "top3_review_count": _json_list(row.get("top3_review_count")),
        "review_wall_max": row.get("review_wall_max"),
        "single_brand_share": _float_or_none(row.get("single_brand_share")),
        "dominant_brand": row.get("dominant_brand"),
        "new_entrant_ratio_est": _float_or_none(row.get("new_entrant_ratio_est")),
        "page_one_sample": _json_list(row.get("page_one_sample")),
        "mode": row.get("mode"),
        "credits_used": row.get("credits_used"),
        "source": row.get("source"),
        "payload": payload,
        "competition_data_valid": bool(payload.get("valid", row.get("source") == "rainforest_search")),
        "competition_invalid_reason": payload.get("invalid_reason") or payload.get("error"),
        "market_seller_count_est": _int_or_none(payload.get("market_seller_count_est")),
        "market_brand_count_est": _int_or_none(payload.get("market_brand_count_est")),
        "keyword_source": payload.get("keyword_source"),
        "fetched_at": _iso(row.get("fetched_at")),
    }


def _competition_keyword(context: dict[str, Any], *, keyword: str | None) -> dict[str, str]:
    explicit = _clean_competition_keyword(keyword)
    if explicit:
        return {"keyword": explicit, "source": "explicit"}
    product = context.get("product") if isinstance(context.get("product"), dict) else {}
    supplier = context.get("supplier") if isinstance(context.get("supplier"), dict) else {}
    title_keyword = _keyword_from_product_title(product)
    if title_keyword:
        return {"keyword": title_keyword, "source": "product_title_non_brand"}
    for value in (
        supplier.get("product_keyword"),
        supplier.get("base_keyword"),
        product.get("title_zh"),
        product.get("source_query"),
        product.get("category"),
    ):
        cleaned = _clean_competition_keyword(value)
        if cleaned:
            return {"keyword": cleaned, "source": "fallback"}
    return {"keyword": "generic product", "source": "fallback_generic"}


def _organic_sample(item: dict[str, Any]) -> dict[str, Any]:
    title = item.get("title")
    return {
        "position": _int_or_none(item.get("position")),
        "asin": item.get("asin"),
        "title": title,
        "brand": _infer_brand(str(title or "")),
        "rating": _float_or_none(item.get("rating")),
        "ratings_total": _int_or_none(item.get("ratings_total")) or 0,
        "sponsored": bool(item.get("sponsored")),
    }


def _clean_competition_keyword(value: Any) -> str | None:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered.startswith("keepa_category:"):
        return None
    if re.fullmatch(r"B0[A-Z0-9]{8}|[A-Z0-9]{10}", cleaned.upper()):
        return None
    if re.search(r"[\u4e00-\u9fff]", cleaned):
        return cleaned[:80]
    cleaned = re.sub(r"[^A-Za-z0-9 +&/-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_/")
    return cleaned[:120] or None


def _keyword_from_product_title(product: dict[str, Any]) -> str | None:
    title = str(product.get("title") or "").strip()
    if not title:
        return None
    brand = str(product.get("brand") or "").strip()
    text = re.sub(r"[®™©]", " ", title)
    if brand:
        text = re.sub(re.escape(brand), " ", text, flags=re.IGNORECASE)
    text = re.split(r"[,|:;\\(\\[]", text, maxsplit=1)[0]
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{1,}", text)
    ]
    brand_tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{1,}", brand)
    }
    generic = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "new",
        "best",
        "seller",
        "amazon",
        "series",
        "eco",
        "pink",
        "black",
        "white",
        "blue",
        "red",
        "green",
        "small",
        "medium",
        "large",
        "xl",
        "xxl",
        "pack",
        "set",
    }
    kept: list[str] = []
    for token in tokens:
        normalized = token.strip("-").lower()
        if not normalized or normalized in generic or normalized in brand_tokens:
            continue
        if normalized.isdigit():
            continue
        kept.append(normalized)
        if len(kept) >= 6:
            break
    if len(kept) < 2:
        return None
    return " ".join(kept)[:120]


def _expected_product_tokens(context: dict[str, Any], *, keyword: str) -> list[str]:
    product = context.get("product") if isinstance(context.get("product"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            keyword,
            product.get("title"),
            product.get("category"),
        )
    )
    generic = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "new",
        "amazon",
        "pack",
        "set",
        "small",
        "medium",
        "large",
    }
    tokens = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{2,}", text.lower()):
        if token in generic or token.isdigit():
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens[:10]


def _title_relevance_score(*, title: str, expected_tokens: list[str]) -> int:
    lowered = title.lower()
    return sum(1 for token in expected_tokens if token and token in lowered)


def _min_relevance_score(expected_tokens: list[str]) -> int:
    if len(expected_tokens) <= 2:
        return 1
    return 2


def _competition_result_valid(
    *,
    expected_tokens: list[str],
    organic: list[dict[str, Any]],
    relevant_organic: list[dict[str, Any]],
) -> bool:
    if not organic:
        return False
    if not expected_tokens:
        return True
    return len(relevant_organic) >= max(2, min(5, len(organic[:10]) // 2))


def _infer_brand(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff ]+", " ", title).strip()
    if not cleaned:
        return "generic"
    first = cleaned.split()[0].lower()
    generic = {
        "the",
        "a",
        "an",
        "new",
        "upgraded",
        "portable",
        "heavy",
        "premium",
        "generic",
        "amazon",
        "for",
        "with",
        "set",
        "pack",
    }
    if first in generic or len(first) <= 2:
        return "generic"
    return first[:40]


def _rainforest_mode() -> str:
    mode = os.getenv("RAINFOREST_MODE", "cheap").strip().lower()
    return mode if mode in {"cheap", "deep"} else "cheap"


def _rainforest_recheck_days() -> int:
    return _bounded_int(os.getenv("RAINFOREST_RECHECK_DAYS"), DEFAULT_RAINFOREST_RECHECK_DAYS, 1, 365)


def _new_review_threshold() -> int:
    return _bounded_int(
        os.getenv("RAINFOREST_NEW_REVIEW_THRESHOLD"),
        DEFAULT_NEW_REVIEW_THRESHOLD,
        1,
        10000,
    )


def _rainforest_timeout_seconds() -> int:
    return _bounded_int(
        os.getenv("RAINFOREST_TIMEOUT_SECONDS"),
        DEFAULT_RAINFOREST_TIMEOUT_SECONDS,
        5,
        120,
    )


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _secret_payload(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _decimal_or_none(value: Any) -> Decimal | None:
    parsed = _float_or_none(value)
    return Decimal(str(parsed)) if parsed is not None else None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return str(value)
