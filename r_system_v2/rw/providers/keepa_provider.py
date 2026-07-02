"""Keepa adapter for the R-W production ingestion path."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.rw.core.models import KeepaProductData


MOCK_MODE = False
USE_REAL_KEEPA_API = True
MAX_REQUESTS_PER_MINUTE = 20
NO_BURST_MODE = True
QUEUE_BASED_INGESTION_REQUIRED = True
DEFAULT_KEEPA_BASE_URL = "https://api.keepa.com"
DEFAULT_KEEPA_DOMAIN = 1

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
                "stats": 90,
            },
            self.timeout_sec,
        )
        return _parse_product_payload(payload, asin=asin, source_query=source_query)

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
            mock_generated=True,
        )


def _default_http_get_json(
    url: str,
    params: dict[str, str | int],
    timeout_sec: float,
) -> dict[str, Any]:
    target = f"{url}?{urlencode(params)}"
    request = Request(target, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout_sec) as response:  # nosec B310 - fixed Keepa URL.
        payload = response.read().decode("utf-8")
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


def _stats_current(product: dict[str, Any], index: int) -> Any:
    stats = product.get("stats")
    if not isinstance(stats, dict):
        return None
    current = stats.get("current")
    if not isinstance(current, list) or len(current) <= index:
        return None
    return current[index]


def _category_name(product: dict[str, Any]) -> str:
    category_tree = product.get("categoryTree")
    if isinstance(category_tree, list) and category_tree:
        first = category_tree[0]
        if isinstance(first, dict) and isinstance(first.get("name"), str):
            return first["name"]
    root_category = product.get("rootCategory")
    if root_category is not None:
        return str(root_category)
    return "Unknown"


def _parse_product_payload(
    payload: dict[str, Any],
    *,
    asin: str,
    source_query: str | None,
) -> KeepaProductData:
    product = _first_product(payload)
    price = (
        _money_from_cents(_stats_current(product, 1))
        or _money_from_cents(_stats_current(product, 0))
    )
    if price is None:
        raise KeepaResponseError("keepa_price_unavailable")

    bsr = _int_from_payload(product, "salesRank", "bsr", default=0)
    if bsr == 0:
        bsr = _int_from_payload({"value": _stats_current(product, 3)}, "value", default=0)

    reviews = _int_from_payload(product, "reviewCount", "reviews", default=0)
    if reviews == 0:
        reviews = _int_from_payload({"value": _stats_current(product, 17)}, "value", default=0)

    seller_count = _int_from_payload(product, "offerCount", "sellerCount", default=0)
    brand_share = float(product.get("brandShare", 0) or 0)
    landed_cost = round(price * 0.35, 2)
    title = str(product.get("title") or source_query or asin)
    brand = str(product.get("brand") or "Unknown")

    return KeepaProductData(
        asin=str(product.get("asin") or asin),
        price=price,
        bsr=bsr,
        reviews=reviews,
        seller_count=seller_count,
        category=_category_name(product),
        title=title,
        brand=brand,
        landed_cost=landed_cost,
        brand_share=brand_share,
        price_trend=str(product.get("priceTrend") or "unknown"),
        marketplace="US",
        rating=None,
        mock_generated=False,
    )
