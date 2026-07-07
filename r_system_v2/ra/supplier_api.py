"""Supplier source provider abstraction for R-A.

The real 1688 Open Platform integration will plug into this contract once the
AppKey/AppSecret/access token are available. Until then R-A uses the local mock
provider so the downstream candidate, supplier-offer, and profit engines can be
tested without Serper-driven cost search.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha1
import json
import os
from typing import Any, Protocol

from r_system_v2.ra.profit_engine import decimal_value


DEFAULT_SUPPLIER_SOURCE_MODE = "mock_1688_api"


class RASupplierApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class Alibaba1688Credentials:
    app_key: str | None = None
    app_secret: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: str | None = None

    @classmethod
    def from_secret_value(cls, value: str) -> "Alibaba1688Credentials":
        cleaned = str(value or "").strip()
        if not cleaned:
            return cls()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return cls(access_token=cleaned)
        if not isinstance(payload, dict):
            return cls(access_token=cleaned)
        return cls(
            app_key=_optional_string(payload.get("app_key") or payload.get("appKey")),
            app_secret=_optional_string(
                payload.get("app_secret") or payload.get("appSecret")
            ),
            access_token=_optional_string(
                payload.get("access_token") or payload.get("accessToken")
            ),
            refresh_token=_optional_string(
                payload.get("refresh_token") or payload.get("refreshToken")
            ),
            expires_at=_optional_string(payload.get("expires_at") or payload.get("expiresAt")),
        )

    @property
    def ready(self) -> bool:
        return bool(self.app_key and self.app_secret and self.access_token)


@dataclass(frozen=True)
class SupplierApiOffer:
    supplier_name: str
    supplier_url: str
    title: str
    unit_price_cny: Decimal
    domestic_shipping_cny: Decimal | None
    moq: int
    rating: Decimal | None
    match_score: int
    stock: int | None
    monthly_sales: int | None
    one_piece_hint: bool
    platform: str = "1688"
    platform_label: str = "1688"
    source: str = "mock_1688_api"
    payload: dict[str, Any] | None = None


class SupplierApiProvider(Protocol):
    provider_name: str

    def search_offers(
        self,
        *,
        product: dict[str, Any],
        keyword_profile: dict[str, Any],
        limit: int,
    ) -> list[SupplierApiOffer]:
        ...


class Mock1688OfficialApiProvider:
    provider_name = "mock_1688_api"

    def search_offers(
        self,
        *,
        product: dict[str, Any],
        keyword_profile: dict[str, Any],
        limit: int,
    ) -> list[SupplierApiOffer]:
        bounded_limit = max(3, min(int(limit), 5))
        base_keyword = _base_keyword(product, keyword_profile)
        asin = str(product.get("asin") or "UNKNOWN").upper()
        sell_price_usd = decimal_value(product.get("price")) or Decimal("29.99")
        sell_price_cny = sell_price_usd * Decimal("7.20")
        factors = (Decimal("0.16"), Decimal("0.19"), Decimal("0.22"), Decimal("0.25"), Decimal("0.28"))
        shipping_values = (Decimal("0.00"), Decimal("6.00"), Decimal("8.00"), Decimal("12.00"), Decimal("0.00"))
        moq_values = (1, 1, 2, 1, 3)
        offers: list[SupplierApiOffer] = []
        for index in range(bounded_limit):
            unit_price = _money(max(Decimal("6.80"), sell_price_cny * factors[index]))
            shipping = shipping_values[index]
            offer_id = _stable_offer_id(asin, base_keyword, index)
            supplier_name = f"{base_keyword}源头工厂{index + 1}"
            title = f"{base_keyword} 一件代发 现货供应"
            offers.append(
                SupplierApiOffer(
                    supplier_name=supplier_name,
                    supplier_url=f"https://detail.1688.com/offer/{offer_id}.html",
                    title=title,
                    unit_price_cny=unit_price,
                    domestic_shipping_cny=shipping,
                    moq=moq_values[index],
                    rating=Decimal(f"{4.8 - index * 0.1:.1f}"),
                    match_score=max(72, 94 - index * 4),
                    stock=1000 - index * 120,
                    monthly_sales=360 - index * 35,
                    one_piece_hint=True,
                    payload={
                        "official_api_mock": True,
                        "api_family": "alibaba.cross.similar.offer.search + alibaba.cross.productInfo",
                        "base_keyword": base_keyword,
                        "offer_id": offer_id,
                        "cost_basis": "deterministic_mock_until_official_1688_api_ready",
                    },
                )
            )
        return offers


class Alibaba1688OfficialApiProvider:
    provider_name = "alibaba1688_official_api"

    def __init__(self, *, credentials: Alibaba1688Credentials) -> None:
        self.credentials = credentials

    def search_offers(
        self,
        *,
        product: dict[str, Any],
        keyword_profile: dict[str, Any],
        limit: int,
    ) -> list[SupplierApiOffer]:
        del product, keyword_profile, limit
        if not self.credentials.ready:
            raise RASupplierApiError("1688 官方 API 密钥尚未完整绑定。")
        raise RASupplierApiError("1688 官方 API 接口已预留，等待真实 API 凭证后接入。")


def supplier_source_mode() -> str:
    mode = os.getenv("RA_SUPPLIER_SOURCE_MODE", DEFAULT_SUPPLIER_SOURCE_MODE)
    normalized = mode.strip().lower().replace("-", "_")
    return normalized or DEFAULT_SUPPLIER_SOURCE_MODE


def _base_keyword(product: dict[str, Any], keyword_profile: dict[str, Any]) -> str:
    for value in (
        keyword_profile.get("product_type_zh"),
        product.get("title_zh"),
        product.get("category"),
        product.get("title"),
    ):
        text = _optional_string(value)
        if text:
            cleaned = text.split(",")[0].split("，")[0].strip()
            return cleaned[:40] or "跨境产品"
    return "跨境产品"


def _stable_offer_id(asin: str, keyword: str, index: int) -> str:
    digest = sha1(f"{asin}:{keyword}:{index}".encode("utf-8")).hexdigest()
    return str(int(digest[:14], 16))[:12].ljust(12, "0")


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
