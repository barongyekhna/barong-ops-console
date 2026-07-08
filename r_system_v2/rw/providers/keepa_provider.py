"""Keepa adapter for the R-W production ingestion path."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.rw.category.category_tree import (
    holiday_search_terms,
    is_holiday_category_id,
)
from r_system_v2.rw.core.models import KeepaProductData


MOCK_MODE = False
USE_REAL_KEEPA_API = True
MAX_REQUESTS_PER_MINUTE = 20
# --- Keepa token economics -------------------------------------------------
# A /product fetch with rating=1 costs 2 tokens (base 1 + rating 1); the image
# backfill re-fetches the same endpoint so it also costs 2. A Product Finder
# /query costs ~10. The 45 EUR plan regenerates 20 tokens/min, so the true
# sustainable *request* rate is 20 / 2 = 10 req/min -- NOT 20. Every budget and
# the wall-clock rate limiter must count these real costs or the pool drains at
# 2x the regen rate and collapses into 429 backoff.
KEEPA_TOKENS_PER_PRODUCT = max(1, int(os.getenv("KEEPA_TOKENS_PER_PRODUCT", "2")))
KEEPA_TOKENS_PER_DISCOVERY = max(1, int(os.getenv("KEEPA_TOKENS_PER_DISCOVERY", "10")))
KEEPA_TOKEN_REGEN_PER_MIN = max(1, int(os.getenv("KEEPA_TOKENS_PER_MIN", "20")))
KEEPA_TOKEN_RESERVE = max(0, int(os.getenv("KEEPA_TOKEN_RESERVE", "2")))
KEEPA_SUSTAINABLE_REQUESTS_PER_MIN = max(
    1, KEEPA_TOKEN_REGEN_PER_MIN // KEEPA_TOKENS_PER_PRODUCT
)
NO_BURST_MODE = True
QUEUE_BASED_INGESTION_REQUIRED = True
DEFAULT_KEEPA_BASE_URL = "https://api.keepa.com"
DEFAULT_KEEPA_DOMAIN = 1
MIN_PRODUCT_FINDER_PER_PAGE = 50
DISCOVERY_PRICE_BUCKETS = ((2500, 3500), (3501, 5000), (5001, 7000))
DISCOVERY_SALES_RANK_BUCKETS = ((1, 5000), (5001, 20000), (20001, 50000))
DISCOVERY_WINDOWS = tuple(
    {
        "price_min": price_min,
        "price_max": price_max,
        "sales_rank_min": sales_rank_min,
        "sales_rank_max": sales_rank_max,
    }
    for price_min, price_max in DISCOVERY_PRICE_BUCKETS
    for sales_rank_min, sales_rank_max in DISCOVERY_SALES_RANK_BUCKETS
)
DEFAULT_CATEGORY_ID_MAP = {
    "home-kitchen": 1055398,
    "home-draft-proofing": 1055398,
    "home-storage-organization": 1055398,
    "home-small-tools": 1055398,
    "patio-lawn-garden": 2972638011,
    "garden-lightweight-tools": 2972638011,
    "garden-seasonless-accessories": 2972638011,
    "office-products": 1064954,
    "office-organization": 1064954,
    "office-ergonomic-accessories": 1064954,
    "home-kitchen-root": 1055398,
    "tools-home-improvement-root": 228013,
    "patio-lawn-garden-root": 2972638011,
    "office-products-root": 1064954,
    "sports-outdoors-root": 3375251,
    "arts-crafts-sewing-root": 2617941011,
    "pet-supplies-root": 2619533011,
    "toys-games-root": 165793011,
    "beauty-personal-care-root": 3760911,
    "health-household-root": 3760901,
    "industrial-scientific-root": 16310091,
    "appliances-root": 2619525011,
}

HttpGetJSON = Callable[[str, dict[str, str | int], float], dict[str, Any]]


class KeepaConfigurationError(RuntimeError):
    """Raised when production Keepa mode is requested without credentials."""


class KeepaResponseError(RuntimeError):
    """Raised when Keepa returns an unusable response."""


@dataclass(frozen=True)
class KeepaStatus:
    tokens_left: int
    refill_rate_per_min: int
    refill_in_sec: int
    mock_mode: bool
    max_requests_per_min: int = MAX_REQUESTS_PER_MINUTE
    no_burst_mode: bool = NO_BURST_MODE
    queue_based_ingestion_required: bool = QUEUE_BASED_INGESTION_REQUIRED

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "tokens_left": self.tokens_left,
            "refill_rate_per_min": self.refill_rate_per_min,
            "refill_in_sec": self.refill_in_sec,
            "mock_mode": self.mock_mode,
            "max_requests_per_min": self.max_requests_per_min,
            "no_burst_mode": self.no_burst_mode,
            "queue_based_ingestion_required": self.queue_based_ingestion_required,
        }


class KeepaProvider:
    """Production-first Keepa adapter.

    Production mode never falls back to mock data. Tests can still pass
    ``force_mock=True`` explicitly, but the module-level production switches
    remain ``MOCK_MODE=False`` and ``USE_REAL_KEEPA_API=True``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        tokens_per_min: int | None = None,
        force_mock: bool = False,
        base_url: str | None = None,
        domain: int | None = None,
        org_id: str | None = None,
        secret_manager: SecretManager | None = None,
        timeout_sec: float = 10.0,
        http_get_json: HttpGetJSON | None = None,
        use_real_api: bool = USE_REAL_KEEPA_API,
    ) -> None:
        self.org_id = org_id or os.getenv("R_SYSTEM_ORG_ID", "")
        self.secret_manager = secret_manager or SecretManager()
        self._explicit_api_key = api_key
        self._api_key = api_key or ""
        if api_key is None:
            self.reload_secret()
        requested_tokens = tokens_per_min or int(os.getenv("KEEPA_TOKENS_PER_MIN", "20"))
        self.tokens_per_min = min(requested_tokens, MAX_REQUESTS_PER_MINUTE)
        self.mock_mode = bool(force_mock)
        self.base_url = (base_url or os.getenv("KEEPA_BASE_URL") or DEFAULT_KEEPA_BASE_URL).rstrip("/")
        self.domain = domain or int(os.getenv("KEEPA_DOMAIN", str(DEFAULT_KEEPA_DOMAIN)))
        self.timeout_sec = timeout_sec
        self.http_get_json = http_get_json or _default_http_get_json
        self.use_real_api = use_real_api

    @property
    def api_key(self) -> str:
        return self._explicit_api_key or self._api_key

    def reload_secret(self) -> str:
        if self._explicit_api_key is not None:
            self._api_key = self._explicit_api_key
            return self._api_key
        self._api_key = self._resolve_api_key()
        return self._api_key

    def current_api_key(self) -> str:
        if self._explicit_api_key is not None:
            return self._explicit_api_key
        return self.reload_secret()

    def _resolve_api_key(self) -> str:
        if not self.org_id:
            return ""
        try:
            return self.secret_manager.get_key("keepa", self.org_id)
        except SecretManagerError:
            return ""

    def status(self) -> KeepaStatus:
        if self.mock_mode:
            return KeepaStatus(
                tokens_left=self.tokens_per_min,
                refill_rate_per_min=self.tokens_per_min,
                refill_in_sec=0,
                mock_mode=True,
            )
        self._require_real_api()
        api_key = self.current_api_key()
        payload = self.http_get_json(
            f"{self.base_url}/token",
            {"key": api_key},
            self.timeout_sec,
        )
        return _parse_status_payload(payload)

    def fetch_product(self, asin: str, source_query: str | None = None) -> KeepaProductData:
        if self.mock_mode:
            return self._mock_product(asin=asin, source_query=source_query)
        self._require_real_api()
        api_key = self.current_api_key()
        payload = self.http_get_json(
            f"{self.base_url}/product",
            {
                "key": api_key,
                "domain": self.domain,
                "asin": asin,
                "history": 1,
                "rating": 1,
                "stats": 90,
            },
            self.timeout_sec,
        )
        return _parse_product_payload(payload, asin=asin, source_query=source_query)

    def discover_asins(
        self,
        *,
        category_id: str,
        limit: int = MAX_REQUESTS_PER_MINUTE,
        page: int = 0,
    ) -> list[str]:
        """Discover ASINs for a Keepa category through Product Finder.

        Category slugs from the UI can be mapped to Keepa numeric category ids
        through ``RW_KEEPA_CATEGORY_MAP``:
        ``{"home-kitchen": 1055398}``.
        """

        if self.mock_mode:
            return [
                f"B0{hashlib.sha1(f'{category_id}:{index}'.encode('utf-8')).hexdigest()[:8].upper()}"
                for index in range(max(0, min(limit, MAX_REQUESTS_PER_MINUTE)))
            ]
        self._require_real_api()
        if is_holiday_category_id(category_id):
            return self._discover_holiday_asins(
                category_id=category_id,
                limit=limit,
                page=page,
            )
        keepa_category = _resolve_keepa_category_id(category_id)
        if keepa_category is None:
            raise KeepaConfigurationError(f"keepa_category_mapping_missing:{category_id}")
        api_key = self.current_api_key()
        selection = _product_finder_selection(
            keepa_category=keepa_category,
            page=max(0, int(page)),
        )
        try:
            return self._query_discovery(api_key=api_key, selection=selection, limit=limit)
        except Exception as query_error:
            raise KeepaResponseError(
                f"keepa_prefilter_discovery_failed:{query_error}"
            ) from query_error

    def discovery_window_for_page(self, page: int) -> dict[str, int]:
        """Expose the Product Finder window for observability/tests."""

        return _discovery_window_for_page(page)

    def _query_discovery(
        self,
        *,
        api_key: str,
        selection: dict[str, Any],
        limit: int,
    ) -> list[str]:
        payload = self.http_get_json(
            f"{self.base_url}/query",
            {
                "key": api_key,
                "domain": self.domain,
                "selection": json.dumps(selection, separators=(",", ":")),
            },
            self.timeout_sec,
        )
        return _parse_discovery_payload(payload, limit=limit)

    def _discover_bestseller_asins(
        self,
        *,
        api_key: str,
        keepa_category: int,
        limit: int,
    ) -> list[str]:
        payload = self.http_get_json(
            f"{self.base_url}/bestsellers",
            {
                "key": api_key,
                "domain": self.domain,
                "category": keepa_category,
                "range": 0,
            },
            self.timeout_sec,
        )
        return _extract_asins(payload, limit=limit)

    def _discover_holiday_asins(
        self,
        *,
        category_id: str,
        limit: int,
        page: int,
    ) -> list[str]:
        api_key = self.current_api_key()
        terms = holiday_search_terms(category_id)
        if not terms:
            raise KeepaConfigurationError(f"holiday_category_mapping_missing:{category_id}")
        term_index = max(0, int(page)) % len(terms)
        term_page = max(0, int(page)) // len(terms)
        term = terms[term_index]
        selection = {
            "title": term,
            "current_SALES_gte": 1,
            "current_SALES_lte": 50000,
            "perPage": MIN_PRODUCT_FINDER_PER_PAGE,
            "page": term_page,
            "sort": [["current_SALES", "asc"]],
        }
        payload = self.http_get_json(
            f"{self.base_url}/query",
            {
                "key": api_key,
                "domain": self.domain,
                "selection": json.dumps(selection, separators=(",", ":")),
            },
            self.timeout_sec,
        )
        return _parse_discovery_payload(payload, limit=limit)

    async def fetch_product_async(
        self,
        asin: str,
        source_query: str | None = None,
    ) -> KeepaProductData:
        if self.mock_mode:
            return self._mock_product(asin=asin, source_query=source_query)
        return await asyncio.to_thread(
            self.fetch_product,
            asin,
            source_query=source_query,
        )

    def _require_real_api(self) -> None:
        if not self.use_real_api:
            raise KeepaConfigurationError("real_keepa_api_disabled")
        if not self.current_api_key():
            raise KeepaConfigurationError("keepa_api_key_missing")

    def _mock_product(self, asin: str, source_query: str | None = None) -> KeepaProductData:
        query = (source_query or "warehouse product").strip()
        seed = int(hashlib.sha1(f"{asin}:{query}".encode("utf-8")).hexdigest()[:8], 16)

        if query.lower() == "portable door draft stopper":
            return KeepaProductData(
                asin=asin,
                price=34.99,
                bsr=8421,
                reviews=214,
                seller_count=7,
                category="Home & Kitchen",
                title="Portable Door Draft Stopper",
                brand="DraftGuard",
                landed_cost=12.50,
                brand_share=0.32,
                price_trend="stable",
                rating=4.4,
                image_url=_fallback_image_url(asin),
                monthly_sales=420,
                parent_category_rank=1_240,
                parent_category_name="Home & Kitchen",
                subcategory_rank=8421,
                subcategory_name="Draft Stoppers",
                category_id="13679381",
                category_path=["Home & Kitchen", "Draft Stoppers"],
                category_id_path=["1055398", "13679381"],
                image_candidates=[_fallback_image_url(asin)] if _fallback_image_url(asin) else [],
                mock_generated=True,
            )

        price = round(25.0 + (seed % 4_000) / 100, 2)
        landed_cost = round(price * 0.38, 2)
        bsr = 5_000 + seed % 25_000
        reviews = 80 + seed % 650
        seller_count = 4 + seed % 10
        brand_share = round(0.20 + ((seed // 10) % 25) / 100, 2)
        trend = ("stable", "slightly_up", "stable")[seed % 3]

        return KeepaProductData(
            asin=asin,
            price=price,
            bsr=bsr,
            reviews=reviews,
            seller_count=seller_count,
            category="Home & Kitchen",
            title=query.title(),
            brand=f"MockBrand{seed % 97}",
            landed_cost=landed_cost,
            brand_share=brand_share,
            price_trend=trend,
            rating=round(4.0 + (seed % 8) / 10, 1),
            image_url=_fallback_image_url(asin),
            monthly_sales=50 + seed % 600,
            parent_category_rank=1_000 + seed % 30_000,
            parent_category_name="Home & Kitchen",
            subcategory_rank=bsr,
            subcategory_name="Mock Category",
            category_id="1055398",
            category_path=["Home & Kitchen", "Mock Category"],
            category_id_path=["1055398"],
            image_candidates=[_fallback_image_url(asin)] if _fallback_image_url(asin) else [],
            mock_generated=True,
        )


def _product_finder_selection(*, keepa_category: int, page: int) -> dict[str, Any]:
    window = _discovery_window_for_page(page)
    return {
            "categories_include": [keepa_category],
            "current_NEW_gte": window["price_min"],
            "current_NEW_lte": window["price_max"],
            "current_SALES_gte": window["sales_rank_min"],
            "current_SALES_lte": window["sales_rank_max"],
            "current_COUNT_NEW_lte": 15,
            "current_COUNT_REVIEWS_lte": 500,
            "perPage": MIN_PRODUCT_FINDER_PER_PAGE,
            "page": _window_page(page),
            "sort": [["current_SALES", "asc"]],
        }


def _discovery_window_for_page(page: int) -> dict[str, int]:
    return DISCOVERY_WINDOWS[max(0, int(page)) % len(DISCOVERY_WINDOWS)]


def _window_page(page: int) -> int:
    return max(0, int(page)) // len(DISCOVERY_WINDOWS)


def _default_http_get_json(
    url: str,
    params: dict[str, str | int],
    timeout_sec: float,
) -> dict[str, Any]:
    target = f"{url}?{urlencode(params)}"
    request = Request(
        target,
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
    )
    with urlopen(request, timeout=timeout_sec) as response:  # nosec B310 - fixed Keepa URL.
        body = response.read()
        content_encoding = response.headers.get("Content-Encoding", "").lower()
    if "gzip" in content_encoding or body.startswith(b"\x1f\x8b"):
        body = gzip.decompress(body)
    payload = body.decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise KeepaResponseError("keepa_response_not_json_object")
    return data


def _int_from_payload(payload: dict[str, Any], *keys: str, default: int = 0) -> int:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return max(0, int(value))
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return default


def _parse_status_payload(payload: dict[str, Any]) -> KeepaStatus:
    tokens_left = _int_from_payload(payload, "tokensLeft", "tokens_left")
    refill_rate = _int_from_payload(
        payload,
        "refillRate",
        "refill_rate",
        default=MAX_REQUESTS_PER_MINUTE,
    )
    refill_in_sec = _int_from_payload(payload, "refillIn", "refill_in", "refillInSec")
    return KeepaStatus(
        tokens_left=tokens_left,
        refill_rate_per_min=min(refill_rate, MAX_REQUESTS_PER_MINUTE),
        refill_in_sec=refill_in_sec,
        mock_mode=False,
    )


def _resolve_keepa_category_id(category_id: str) -> int | None:
    cleaned = category_id.strip()
    if cleaned.isdigit():
        return int(cleaned)
    if cleaned in DEFAULT_CATEGORY_ID_MAP:
        return DEFAULT_CATEGORY_ID_MAP[cleaned]
    raw_map = os.getenv("RW_KEEPA_CATEGORY_MAP", "").strip()
    if not raw_map:
        return None
    try:
        mapping = json.loads(raw_map)
    except json.JSONDecodeError:
        return None
    value = mapping.get(cleaned) if isinstance(mapping, dict) else None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _parse_discovery_payload(payload: dict[str, Any], *, limit: int) -> list[str]:
    if payload.get("error") or payload.get("errors"):
        raise KeepaResponseError("keepa_query_error")
    raw_asins = payload.get("asinList") or payload.get("asins") or payload.get("asin_list")
    if not isinstance(raw_asins, list):
        asins = _extract_asins(payload, limit=limit)
        if asins:
            return asins
        return []
    return _extract_asins(raw_asins, limit=limit)


def _extract_asins(value: Any, *, limit: int) -> list[str]:
    asins: list[str] = []

    def visit(item: Any) -> None:
        if len(asins) >= limit:
            return
        if isinstance(item, str):
            asin = item.strip().upper()
            if len(asin) == 10 and asin.isalnum() and asin not in asins:
                asins.append(asin)
            return
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
                if len(asins) >= limit:
                    return
            return
        if isinstance(item, list):
            for nested in item:
                visit(nested)
                if len(asins) >= limit:
                    return

    visit(value)
    return asins


def _first_product(payload: dict[str, Any]) -> dict[str, Any]:
    products = payload.get("products")
    if not isinstance(products, list) or not products:
        raise KeepaResponseError("keepa_products_empty")
    product = products[0]
    if not isinstance(product, dict):
        raise KeepaResponseError("keepa_product_not_object")
    return product


def _money_from_cents(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return round(float(value) / 100, 2)
    return None


def _positive_int_from_product(product: dict[str, Any], key: str) -> int | None:
    value = product.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _positive_float_from_product(product: dict[str, Any], key: str) -> float | None:
    value = product.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _fba_fee_details(product: dict[str, Any]) -> dict[str, int | float | None]:
    fees = product.get("fbaFees")
    if not isinstance(fees, dict):
        return {"fba_fee_usd": None, "fba_fee_last_update": None}
    fee_usd = _money_from_cents(fees.get("pickAndPackFee"))
    last_update = fees.get("lastUpdate")
    return {
        "fba_fee_usd": fee_usd,
        "fba_fee_last_update": int(last_update)
        if isinstance(last_update, (int, float)) and not isinstance(last_update, bool)
        else None,
    }


def _price_from_product(product: dict[str, Any]) -> float | None:
    for key in (
        "newPrice",
        "buyBoxPrice",
        "buyBox",
        "current_NEW",
        "current_NEW_FBA",
        "current_NEW_FBM_SHIPPING",
    ):
        money = _money_from_cents(product.get(key))
        if money is not None:
            return money
    for index in (1, 10, 7, 18, 0):
        money = _money_from_cents(_stats_current(product, index))
        if money is not None:
            return money
    return None


def _stats_current(product: dict[str, Any], index: int) -> Any:
    stats = product.get("stats")
    if not isinstance(stats, dict):
        return None
    current = stats.get("current")
    if not isinstance(current, list) or len(current) <= index:
        return None
    return current[index]


def _stats_value(product: dict[str, Any], key: str, index: int) -> Any:
    stats = product.get("stats")
    if not isinstance(stats, dict):
        return None
    values = stats.get(key)
    if not isinstance(values, list) or len(values) <= index:
        return None
    return values[index]


def _category_name(product: dict[str, Any]) -> str:
    details = _category_tree_details(product)
    if details["names"]:
        return details["names"][-1]
    root_category = product.get("rootCategory")
    if root_category is not None:
        return str(root_category)
    return "Unknown"


def _category_tree_details(product: dict[str, Any]) -> dict[str, list[str]]:
    category_tree = product.get("categoryTree")
    names: list[str] = []
    ids: list[str] = []
    if isinstance(category_tree, list):
        for node in category_tree:
            if not isinstance(node, dict):
                continue
            name = str(node.get("name") or "").strip()
            category_id = _category_id_from_node(node)
            if name:
                names.append(name)
            if category_id:
                ids.append(category_id)
    return {"names": names, "ids": ids}


def _category_rank_details(product: dict[str, Any], *, default_bsr: int) -> dict[str, Any]:
    del default_bsr
    details = _category_tree_details(product)
    parent_name: str | None = None
    parent_id: str | None = None
    leaf_name: str | None = None
    leaf_id: str | None = None
    if details["names"]:
        parent_name = details["names"][0]
        leaf_name = details["names"][-1]
    if details["ids"]:
        parent_id = details["ids"][0]
        leaf_id = details["ids"][-1]
    parent_rank = _rank_for_sales_rank_category(product, parent_id)
    subcategory_rank = _rank_for_sales_rank_category(product, leaf_id)
    return {
        "parent_category_name": parent_name,
        "parent_category_rank": parent_rank,
        "subcategory_name": leaf_name or _category_name(product),
        "subcategory_rank": subcategory_rank,
        "amazon_leaf_category_id": leaf_id,
        "amazon_parent_category_id": parent_id,
        "amazon_category_path": details["names"],
        "amazon_category_id_path": details["ids"],
    }


def _category_id_from_node(node: dict[str, Any]) -> str | None:
    for key in ("catId", "categoryId", "id"):
        value = node.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(int(value))
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _rank_for_sales_rank_category(product: dict[str, Any], category_id: str | None) -> int | None:
    if not category_id:
        return None
    sales_ranks = product.get("salesRanks")
    if not isinstance(sales_ranks, dict):
        return None
    raw_rank = sales_ranks.get(category_id)
    if raw_rank is None:
        raw_rank = sales_ranks.get(str(category_id))
    rank = _latest_rank_value(raw_rank)
    return rank if rank and rank > 0 else None


def _latest_rank_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    if isinstance(value, list):
        for item in reversed(value):
            rank = _latest_rank_value(item)
            if rank:
                return rank
    return None


def _monthly_sales_from_product(product: dict[str, Any]) -> int | None:
    direct = _int_from_payload(
        product,
        "monthlySold",
        "monthly_sold",
        "monthlySales",
        "monthly_sales",
        default=0,
    )
    if _plausible_monthly_sales(direct):
        return direct
    history = product.get("monthlySoldHistory") or product.get("monthly_sold_history")
    if isinstance(history, list):
        for item in reversed(history):
            if isinstance(item, bool):
                continue
            if isinstance(item, (int, float)) and _plausible_monthly_sales(item):
                return int(item)
            if isinstance(item, list):
                nested = _latest_monthly_sales_value(item)
                if nested:
                    return nested
    return None


def _latest_monthly_sales_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if _plausible_monthly_sales(value) else None
    if isinstance(value, list):
        for item in reversed(value):
            parsed = _latest_monthly_sales_value(item)
            if parsed:
                return parsed
    return None


def _plausible_monthly_sales(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return 0 < int(value) <= 100_000


def _image_candidates_from_product(product: dict[str, Any], *, asin: str | None = None) -> list[str]:
    candidates: list[str] = []
    direct = product.get("imageUrl") or product.get("image_url")
    if isinstance(direct, str) and direct.startswith(("http://", "https://")):
        candidates.append(direct)
    images = product.get("images")
    if isinstance(images, list):
        for item in images:
            if isinstance(item, dict):
                for key in ("m", "l", "large", "medium", "image", "url"):
                    _append_keepa_image_candidate(candidates, item.get(key))
            else:
                _append_keepa_image_candidate(candidates, item)
    elif isinstance(images, dict):
        for key in ("m", "l", "large", "medium", "image", "url"):
            _append_keepa_image_candidate(candidates, images.get(key))
    elif isinstance(images, str):
        for raw_name in images.split(","):
            _append_keepa_image_candidate(candidates, raw_name)
    images_csv = product.get("imagesCSV")
    if isinstance(images_csv, str) and images_csv.strip():
        for raw_name in images_csv.split(","):
            _append_keepa_image_candidate(candidates, raw_name)
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _image_url_from_product(product: dict[str, Any], *, asin: str | None = None) -> str | None:
    candidates = _image_candidates_from_product(product, asin=asin)
    return candidates[0] if candidates else None


def _fallback_image_url(asin: str) -> str | None:
    cleaned = asin.strip().upper()
    if len(cleaned) != 10 or not cleaned.isalnum():
        return None
    return f"https://images-na.ssl-images-amazon.com/images/P/{cleaned}.01._SCLZZZZZZZ_.jpg"


def _append_keepa_image_candidate(candidates: list[str], value: Any) -> None:
    if not isinstance(value, str):
        return
    image_name = value.strip()
    if not image_name:
        return
    if image_name.startswith("//"):
        image_name = f"https:{image_name}"
    if image_name.startswith(("http://", "https://")):
        candidates.append(image_name)
        return
    if "/" in image_name:
        return
    encoded_name = quote(image_name, safe="+._-")
    candidates.append(f"https://images-na.ssl-images-amazon.com/images/I/{encoded_name}")
    candidates.append(f"https://m.media-amazon.com/images/I/{encoded_name}")


def _parse_product_payload(
    payload: dict[str, Any],
    *,
    asin: str,
    source_query: str | None,
) -> KeepaProductData:
    product = _first_product(payload)
    price = _price_from_product(product)
    price_unavailable = price is None
    if price_unavailable:
        price = 0.0

    bsr = _int_from_payload(product, "salesRank", "bsr", default=0)
    if bsr == 0:
        bsr = _int_from_payload({"value": _stats_current(product, 3)}, "value", default=0)

    reviews = _int_from_payload(product, "reviewCount", "reviews", default=0)
    if reviews == 0:
        reviews = _int_from_payload({"value": _stats_current(product, 17)}, "value", default=0)
    if reviews == 0:
        reviews = _int_from_payload({"value": _stats_value(product, "avg90", 17)}, "value", default=0)

    seller_count = _int_from_payload(product, "offerCount", "sellerCount", default=0)
    if seller_count == 0:
        seller_count = _int_from_payload({"value": _stats_current(product, 11)}, "value", default=0)
    if seller_count == 0:
        seller_count = _int_from_payload({"value": _stats_value(product, "avg90", 11)}, "value", default=0)
    brand_share = float(product.get("brandShare", 0) or 0)
    title = str(product.get("title") or source_query or asin)
    brand = str(product.get("brand") or "Unknown")
    parsed_asin = str(product.get("asin") or asin)
    fulfillment_method = _fulfillment_method(product)
    lithium_warning = _has_lithium_warning(product)
    category_details = _category_rank_details(product, default_bsr=bsr)
    monthly_sales = _monthly_sales_from_product(product)
    image_candidates = _image_candidates_from_product(product, asin=parsed_asin)
    fba_fee = _fba_fee_details(product)

    return KeepaProductData(
        asin=parsed_asin,
        price=price,
        bsr=bsr,
        reviews=reviews,
        seller_count=seller_count,
        category=_category_name(product),
        title=title,
        brand=brand,
        landed_cost=None,
        brand_share=brand_share,
        price_trend=str(product.get("priceTrend") or "unknown"),
        marketplace="US",
        rating=_rating_from_product(product),
        image_url=image_candidates[0] if image_candidates else None,
        fulfillment_method=fulfillment_method,
        lithium_battery_warning=lithium_warning,
        margin_source="missing_landed_cost",
        margin_confidence="price_unavailable" if price_unavailable else "unknown",
        monthly_sales=monthly_sales,
        parent_category_rank=category_details["parent_category_rank"],
        parent_category_name=category_details["parent_category_name"],
        subcategory_rank=category_details["subcategory_rank"],
        subcategory_name=category_details["subcategory_name"],
        category_id=category_details["amazon_leaf_category_id"],
        category_path=category_details["amazon_category_path"],
        category_id_path=category_details["amazon_category_id_path"],
        image_candidates=image_candidates,
        fba_fee_usd=fba_fee["fba_fee_usd"],
        fba_fee_last_update=fba_fee["fba_fee_last_update"],
        referral_fee_percentage=_positive_float_from_product(
            product,
            "referralFeePercentage",
        ),
        package_weight_g=_positive_int_from_product(product, "packageWeight"),
        package_length_mm=_positive_int_from_product(product, "packageLength"),
        package_width_mm=_positive_int_from_product(product, "packageWidth"),
        package_height_mm=_positive_int_from_product(product, "packageHeight"),
        item_weight_g=_positive_int_from_product(product, "itemWeight"),
        item_length_mm=_positive_int_from_product(product, "itemLength"),
        item_width_mm=_positive_int_from_product(product, "itemWidth"),
        item_height_mm=_positive_int_from_product(product, "itemHeight"),
        mock_generated=False,
    )


def _fulfillment_method(product: dict[str, Any]) -> str | None:
    stats = product.get("stats")
    if isinstance(stats, dict):
        for key in ("buyBoxIsFBA", "isFBA", "buyBoxFBA"):
            value = stats.get(key)
            if isinstance(value, bool):
                return "FBA" if value else "FBM"
            if isinstance(value, (int, float)) and value in {0, 1}:
                return "FBA" if int(value) == 1 else "FBM"
    for key in ("isFBA", "buyBoxIsFBA", "fba"):
        value = product.get(key)
        if isinstance(value, bool):
            return "FBA" if value else "FBM"
        if isinstance(value, (int, float)) and value in {0, 1}:
            return "FBA" if int(value) == 1 else "FBM"
    return None


def _rating_from_product(product: dict[str, Any]) -> float | None:
    raw_rating = product.get("rating") or product.get("reviewsRating")
    if isinstance(raw_rating, str):
        try:
            raw_rating = float(raw_rating)
        except ValueError:
            raw_rating = None
    if isinstance(raw_rating, (int, float)) and raw_rating > 0:
        rating = float(raw_rating)
        return round(rating / 10 if rating > 5 else rating, 1)
    stats_rating = _stats_current(product, 16)
    if isinstance(stats_rating, (int, float)) and stats_rating > 0:
        return round(float(stats_rating) / 10 if stats_rating > 5 else float(stats_rating), 1)
    avg_rating = _stats_value(product, "avg90", 16)
    if isinstance(avg_rating, (int, float)) and avg_rating > 0:
        return round(float(avg_rating) / 10 if avg_rating > 5 else float(avg_rating), 1)
    return None


def _is_keepa_429(exc: Exception) -> bool:
    message = str(exc)
    return "429" in message or "Too Many Requests" in message


def _has_lithium_warning(product: dict[str, Any]) -> bool:
    text_parts = [
        str(product.get("title") or ""),
        str(product.get("brand") or ""),
        _category_name(product),
    ]
    hazardous = product.get("hazardousMaterials")
    if isinstance(hazardous, list):
        text_parts.extend(str(item) for item in hazardous)
    elif hazardous is not None:
        text_parts.append(str(hazardous))
    haystack = " ".join(text_parts).lower()
    return any(term in haystack for term in ("lithium", "li-ion", "li ion", "battery", "batteries", "锂电", "电池"))
