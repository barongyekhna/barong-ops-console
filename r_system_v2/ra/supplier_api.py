"""Supplier source provider abstraction for R-A.

The real 1688 Open Platform integration will plug into this contract once the
AppKey/AppSecret/access token are available. Until then R-A uses the local mock
provider so the downstream candidate, supplier-offer, and profit engines can be
tested without Serper-driven cost search.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha1
import hmac
import json
import os
import re
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from r_system_v2.ra.profit_engine import decimal_value
from r_system_v2.rw.product_images import primary_product_image_url, product_image_candidates


DEFAULT_SUPPLIER_SOURCE_MODE = "auto_1688_api"
DEFAULT_1688_OPEN_API_BASE_URL = "https://gw.open.1688.com/openapi/param2"
DEFAULT_1688_IMAGE_SEARCH_NAMESPACE = "com.alibaba.linkplus"
DEFAULT_1688_IMAGE_SEARCH_API_NAME = "alibaba.cross.similar.offer.search"
DEFAULT_1688_PRODUCT_INFO_NAMESPACE = "com.alibaba.product"
DEFAULT_1688_PRODUCT_INFO_API_NAME = "alibaba.cross.productInfo"
DEFAULT_1688_FREIGHT_NAMESPACE = "com.alibaba.fenxiao.crossborder"
DEFAULT_1688_FREIGHT_API_NAME = "product.freight.estimate"


class RASupplierApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class Alibaba1688Credentials:
    app_key: str | None = None
    app_secret: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: str | None = None
    api_base_url: str | None = None
    image_search_endpoint: str | None = None
    image_search_api_name: str | None = None
    image_search_namespace: str | None = None
    image_search_version: str | None = None
    image_search_mode: str | None = None
    timeout_seconds: int | None = None

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
            api_base_url=_optional_string(
                payload.get("api_base_url")
                or payload.get("apiBaseUrl")
                or payload.get("base_url")
                or payload.get("baseUrl")
            ),
            image_search_endpoint=_optional_string(
                payload.get("image_search_endpoint")
                or payload.get("imageSearchEndpoint")
                or payload.get("crossborder_image_search_endpoint")
                or payload.get("crossBorderImageSearchEndpoint")
            ),
            image_search_api_name=_optional_string(
                payload.get("image_search_api_name")
                or payload.get("imageSearchApiName")
                or payload.get("crossborder_image_search_api_name")
                or payload.get("crossBorderImageSearchApiName")
                or payload.get("api_name")
                or payload.get("apiName")
            ),
            image_search_namespace=_optional_string(
                payload.get("image_search_namespace")
                or payload.get("imageSearchNamespace")
                or payload.get("namespace")
            ),
            image_search_version=_optional_string(
                payload.get("image_search_version")
                or payload.get("imageSearchVersion")
                or payload.get("version")
            ),
            image_search_mode=_optional_string(
                payload.get("image_search_mode")
                or payload.get("imageSearchMode")
                or payload.get("mode")
            ),
            timeout_seconds=_optional_int(
                payload.get("timeout_seconds") or payload.get("timeoutSeconds")
            ),
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
        if not self.credentials.ready:
            raise RASupplierApiError("1688 官方 API 密钥尚未完整绑定。")

        image_url = _product_image_url(product)
        if not image_url:
            raise RASupplierApiError("该 R-W 产品缺少可用于 1688 图搜的图片。")

        payload = self._call_image_search(
            image_url=image_url,
            keyword_profile=keyword_profile,
            limit=limit,
        )
        offers = _normalize_image_search_offers(payload, limit=limit)
        if not offers:
            return []
        return [self._enrich_offer(offer) for offer in offers]

    def _call_image_search(
        self,
        *,
        image_url: str,
        keyword_profile: dict[str, Any],
        limit: int,
    ) -> dict[str, Any]:
        endpoint = _env_or_credential(
            "RA_1688_IMAGE_SEARCH_ENDPOINT",
            self.credentials.image_search_endpoint,
        )
        api_name = _env_or_credential(
            "RA_1688_IMAGE_SEARCH_API_NAME",
            self.credentials.image_search_api_name,
        ) or DEFAULT_1688_IMAGE_SEARCH_API_NAME

        request_payload = _image_search_params(
            image_url=image_url,
            keyword_profile=keyword_profile,
            limit=limit,
        )
        return self._call_openapi(
            namespace=_openapi_namespace(self.credentials),
            api_name=str(api_name),
            params=request_payload,
            error_label="1688 图搜",
            endpoint=endpoint,
        )

    def _call_product_info(self, offer_id: str) -> dict[str, Any] | None:
        namespace = os.getenv(
            "RA_1688_PRODUCT_INFO_NAMESPACE",
            DEFAULT_1688_PRODUCT_INFO_NAMESPACE,
        ).strip()
        api_name = os.getenv(
            "RA_1688_PRODUCT_INFO_API_NAME",
            DEFAULT_1688_PRODUCT_INFO_API_NAME,
        ).strip()
        try:
            return self._call_openapi(
                namespace=namespace,
                api_name=api_name,
                params={"productId": offer_id},
                error_label="1688 商品详情",
                allow_business_error=True,
            )
        except RASupplierApiError:
            return None

    def _call_freight_estimate(
        self,
        *,
        offer_id: str,
        sku_id: str,
        quantity: int,
    ) -> dict[str, Any] | None:
        namespace = os.getenv(
            "RA_1688_FREIGHT_NAMESPACE",
            DEFAULT_1688_FREIGHT_NAMESPACE,
        ).strip()
        api_name = os.getenv(
            "RA_1688_FREIGHT_API_NAME",
            DEFAULT_1688_FREIGHT_API_NAME,
        ).strip()
        params = {
            "productFreightQueryParamsNew": {
                "offerId": offer_id,
                "toProvinceCode": os.getenv("RA_1688_TO_PROVINCE_CODE", "330000").strip(),
                "toCityCode": os.getenv("RA_1688_TO_CITY_CODE", "330100").strip(),
                "toCountryCode": os.getenv("RA_1688_TO_COUNTRY_CODE", "330108").strip(),
                "totalNum": quantity,
                "logisticsSkuNumModels": [
                    {
                        "skuId": sku_id,
                        "number": quantity,
                    }
                ],
            }
        }
        try:
            return self._call_openapi(
                namespace=namespace,
                api_name=api_name,
                params=params,
                error_label="1688 国内运费预估",
                allow_business_error=True,
            )
        except RASupplierApiError:
            return None

    def _call_openapi(
        self,
        *,
        namespace: str,
        api_name: str,
        params: dict[str, Any],
        error_label: str,
        endpoint: str | None = None,
        allow_business_error: bool = False,
    ) -> dict[str, Any]:
        url = endpoint or self._openapi_url(api_name, namespace=namespace)
        request_payload = dict(params)
        request_payload["access_token"] = str(self.credentials.access_token or "")
        request_payload["_aop_timestamp"] = _aop_timestamp()
        signature_path = _signature_path_for_url(
            url,
            api_name=api_name,
            credentials=self.credentials,
            namespace=namespace,
        )
        if signature_path:
            request_payload["_aop_signature"] = _aop_signature(
                url_path=signature_path,
                params=request_payload,
                app_secret=str(self.credentials.app_secret or ""),
            )

        data = urlencode(_flatten_params(request_payload)).encode("utf-8")
        request = Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "barong-ra/1.0",
            },
        )
        timeout = self.credentials.timeout_seconds or _int_env("RA_1688_TIMEOUT_SECONDS") or 15
        try:
            with urlopen(request, timeout=max(3, timeout)) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RASupplierApiError(f"{error_label}请求失败：HTTP {exc.code} {detail}") from exc
        except URLError as exc:
            raise RASupplierApiError(f"{error_label}网络失败：{exc.reason}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RASupplierApiError(f"{error_label}返回内容不是有效 JSON。") from exc
        if not isinstance(parsed, dict):
            raise RASupplierApiError(f"{error_label}返回结构异常。")
        success = _openapi_success(parsed)
        if success is False:
            message = _openapi_message(parsed) or f"{error_label}返回失败。"
            if allow_business_error:
                return {
                    "success": False,
                    "message": str(message)[:500],
                    "raw": parsed,
                }
            raise RASupplierApiError(str(message)[:500])
        return parsed

    def _enrich_offer(self, offer: SupplierApiOffer) -> SupplierApiOffer:
        payload = dict(offer.payload or {})
        offer_id = _optional_string(payload.get("offer_id")) or _offer_id_from_url(
            offer.supplier_url
        )
        if not offer_id:
            return offer

        detail_payload = self._call_product_info(offer_id)
        if detail_payload:
            payload["product_info_api"] = _compact_api_payload(detail_payload)
            product_info = _product_info_payload(detail_payload)
            sku_id = _extract_sku_id(product_info)
            if sku_id:
                payload["sku_id"] = sku_id
            detail_price = _detail_unit_price(product_info)
            if detail_price is not None:
                payload["product_info_unit_price_cny"] = _decimal_number(detail_price)
            detail_moq = _detail_moq(product_info)
            if detail_moq is not None:
                payload["product_info_moq"] = detail_moq
        else:
            sku_id = None

        quantity = max(1, offer.moq or _optional_int(payload.get("product_info_moq")) or 1)
        shipping = offer.domestic_shipping_cny
        if sku_id:
            freight_payload = self._call_freight_estimate(
                offer_id=offer_id,
                sku_id=sku_id,
                quantity=quantity,
            )
            if freight_payload:
                payload["freight_estimate_api"] = _compact_api_payload(freight_payload)
                freight_total = _freight_total_cny(freight_payload)
                if freight_total is not None:
                    shipping = _money(freight_total / Decimal(str(quantity)))
                    payload["domestic_shipping_cny"] = _decimal_number(shipping)
                    payload["freight_total_cny"] = _decimal_number(freight_total)
                    payload["freight_quantity"] = quantity
                elif _freight_free_postage(freight_payload):
                    shipping = Decimal("0")
                    payload["domestic_shipping_cny"] = 0.0
                    payload["freight_total_cny"] = 0.0
                    payload["freight_quantity"] = quantity
        else:
            payload["freight_warning"] = "商品详情未返回 skuId，无法调用国内运费预估。"

        return replace(
            offer,
            domestic_shipping_cny=shipping,
            payload=payload,
        )

    def _openapi_url(self, api_name: str, *, namespace: str | None = None) -> str:
        return (
            f"{_openapi_base_url(self.credentials).rstrip('/')}/"
            f"{_openapi_version(self.credentials)}/"
            f"{namespace or _openapi_namespace(self.credentials)}/"
            f"{api_name.strip()}/"
            f"{self.credentials.app_key}"
        )


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


def _optional_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _product_image_url(product: dict[str, Any]) -> str | None:
    features = _dict_value(product.get("features"))
    primary = primary_product_image_url(
        asin=str(product.get("asin") or ""),
        image_url=str(product.get("image_url")) if product.get("image_url") else None,
        features=features,
    )
    if primary:
        return primary
    candidates = product_image_candidates(
        asin=str(product.get("asin") or ""),
        image_url=str(product.get("image_url")) if product.get("image_url") else None,
        features=features,
    )
    return candidates[0] if candidates else None


def _image_search_params(
    *,
    image_url: str,
    keyword_profile: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "picUrl": image_url,
        "page": 1,
        "priceMin": _env_or_credential("RA_1688_PRICE_MIN", None) or "0",
        "priceMax": _env_or_credential("RA_1688_PRICE_MAX", None) or "999999",
        "sortFields": os.getenv("RA_1688_SORT_FIELDS", "").strip(),
        "cpsFirst": _bool_env("RA_1688_CPS_FIRST"),
        "classify": os.getenv("RA_1688_CLASSIFY", "").strip(),
        "tags": os.getenv("RA_1688_TAGS", "HQ_DISTRIBUTION").strip(),
    }
    category_id = os.getenv("RA_1688_CATEGORY_ID", "").strip()
    if category_id:
        params["categoryID"] = category_id
    media_id = os.getenv("RA_1688_MEDIA_ID", "").strip()
    if media_id:
        params["mediaId"] = media_id
    media_zone_id = os.getenv("RA_1688_MEDIA_ZONE_ID", "").strip()
    if media_zone_id:
        params["mediaZoneId"] = media_zone_id
    product_type = _optional_string(keyword_profile.get("product_type_zh"))
    if product_type:
        params["keywords"] = product_type
    return {key: value for key, value in params.items() if value not in (None, "")}


def _normalize_image_search_offers(
    payload: dict[str, Any],
    *,
    limit: int,
) -> list[SupplierApiOffer]:
    raw_items = _extract_offer_items(payload)
    output: list[SupplierApiOffer] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_items):
        if len(output) >= max(1, min(int(limit or 5), 20)):
            break
        if not isinstance(item, dict):
            continue
        offer_id = _optional_string(
            item.get("offerId") or item.get("offer_id") or item.get("id")
        )
        detail_url = _optional_string(
            item.get("detailUrl") or item.get("detail_url") or item.get("url")
        )
        if not detail_url and offer_id:
            detail_url = f"https://detail.1688.com/offer/{offer_id}.html"
        if not detail_url:
            continue
        dedupe_key = offer_id or detail_url
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        title = _optional_string(item.get("subject") or item.get("title") or item.get("name"))
        price = _official_price(item)
        if price is None:
            continue
        min_unit_price = _min_official_unit_price_cny()
        if price < min_unit_price:
            continue
        moq = _official_moq(item)
        rating = _official_rating(item)
        stock = _official_stock(item)
        monthly_sales = _official_monthly_sales(item)
        output.append(
            SupplierApiOffer(
                supplier_name=_optional_string(
                    _dict_value(item.get("companyInfo")).get("companyName")
                    or item.get("loginId")
                    or item.get("supplierName")
                )
                or "1688供应商",
                supplier_url=detail_url,
                title=title or "1688 图搜同款商品",
                unit_price_cny=price,
                domestic_shipping_cny=_official_shipping(item),
                moq=moq,
                rating=rating,
                match_score=max(65, 96 - index * 3),
                stock=stock,
                monthly_sales=monthly_sales,
                one_piece_hint=moq <= 1,
                platform="1688",
                platform_label="1688",
                source="alibaba1688_official_image_search",
                payload={
                    "official_api": True,
                    "api_family": "1688_image_search",
                    "offer_id": offer_id,
                    "title": title,
                    "image_url": item.get("imageUrl")
                    or _dict_value(item.get("offerImage")).get("imageUrl"),
                    "province": item.get("province") or _dict_value(item.get("companyInfo")).get("province"),
                    "city": item.get("city") or _dict_value(item.get("companyInfo")).get("city"),
                    "category_id": item.get("categoryId") or item.get("categoryID"),
                    "supply_amount": item.get("supplyAmount"),
                    "raw_price": item.get("oldPrice")
                    or item.get("price")
                    or _dict_value(item.get("offerPrice")).get("price"),
                },
            )
        )
    return output


def _min_official_unit_price_cny() -> Decimal:
    value = os.getenv("RA_1688_MIN_UNIT_PRICE_CNY", "2").strip()
    parsed = decimal_value(value)
    if parsed is None or parsed < 0:
        return Decimal("2")
    return parsed


def _extract_offer_items(payload: dict[str, Any]) -> list[Any]:
    current: Any = payload
    for key in ("result", "data"):
        if isinstance(current, dict) and isinstance(current.get(key), dict):
            current = current[key]
            break
    if isinstance(current, dict):
        for key in ("result", "items", "list", "data", "modelList"):
            value = current.get(key)
            if isinstance(value, list):
                return value
        nested = current.get("result")
        if isinstance(nested, dict):
            for key in ("result", "items", "list", "data"):
                value = nested.get(key)
                if isinstance(value, list):
                    return value
    return []


def _official_price(item: dict[str, Any]) -> Decimal | None:
    candidates: list[tuple[str, Any]] = [
        ("oldPrice", item.get("oldPrice")),
        ("price", item.get("price")),
        ("priceCent", item.get("priceCent")),
        ("consignPrice", item.get("consignPrice")),
    ]
    offer_price = _dict_value(item.get("offerPrice"))
    candidates.extend(
        [
            ("offerPrice.consignPrice", offer_price.get("consignPrice")),
            ("offerPrice.multipleConsignPrice", offer_price.get("multipleConsignPrice")),
            ("offerPrice.price", offer_price.get("price")),
            ("offerPrice.priceUnderLine", offer_price.get("priceUnderLine")),
        ]
    )
    quantity_prices = offer_price.get("quantityPrice")
    if isinstance(quantity_prices, list):
        for entry in quantity_prices:
            if isinstance(entry, dict):
                candidates.append(("offerPrice.quantityPrice.value", entry.get("value")))
    for key, value in candidates:
        price = decimal_value(value)
        if price is None or price <= 0:
            continue
        if _official_price_is_cent_value(key, value, price):
            return _money(price / Decimal("100"))
        return _money(price)
    return None


def _official_price_is_cent_value(key: str, value: Any, price: Decimal) -> bool:
    raw = str(value or "").strip()
    if "." in raw:
        return False
    if key in {"oldPrice", "priceCent"}:
        return price >= Decimal("10")
    return price >= Decimal("1000")


def _official_shipping(item: dict[str, Any]) -> Decimal | None:
    offer_price = _dict_value(item.get("offerPrice"))
    for key in ("shippingFee", "freight", "postage", "domesticShipping"):
        value = decimal_value(item.get(key) or offer_price.get(key))
        if value is not None and value >= 0:
            return _money(value)
    if offer_price.get("distributionFreePostage") is True or item.get("isFreeShipping") is True:
        return Decimal("0")
    return None


def _official_moq(item: dict[str, Any]) -> int:
    for key in ("quantityBegin", "minOrderQuantity", "moq"):
        parsed = _optional_int(item.get(key))
        if parsed:
            return parsed
    return 1


def _official_rating(item: dict[str, Any]) -> Decimal | None:
    quality = _dict_value(item.get("qualityEvaluation"))
    return decimal_value(quality.get("compositeScore") or item.get("rating"))


def _official_stock(item: dict[str, Any]) -> int | None:
    stock = _optional_int(item.get("supplyAmount") or item.get("stock"))
    if stock is None or stock >= 2_147_483_000:
        return None
    return stock


def _official_monthly_sales(item: dict[str, Any]) -> int | None:
    histories = item.get("offerHistoryTradeInfo")
    if not isinstance(histories, list):
        return None
    best: int | None = None
    for entry in histories:
        if not isinstance(entry, dict):
            continue
        value = _optional_string(entry.get("historyTradeValue"))
        if not value:
            continue
        parsed = _optional_int(re.sub(r"[^0-9]", "", value))
        if parsed is None:
            continue
        best = max(best or 0, parsed)
    return best


def _product_info_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = _dict_value(payload.get("result"))
    product_info = _dict_value(payload.get("productInfo"))
    if product_info:
        return product_info
    product_info = _dict_value(result.get("productInfo"))
    if product_info:
        return product_info
    nested_result = _dict_value(result.get("result"))
    product_info = _dict_value(nested_result.get("productInfo"))
    return product_info or result or payload


def _extract_sku_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in {"skuid", "sku_id"}:
                sku_id = _optional_string(item)
                if sku_id:
                    return sku_id
        preferred_keys = (
            "skuInfos",
            "skuInfoList",
            "productSkuInfos",
            "productSKUInfos",
            "saleInfo",
            "sku",
        )
        for key in preferred_keys:
            found = _extract_sku_id(value.get(key))
            if found:
                return found
        for item in value.values():
            found = _extract_sku_id(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _extract_sku_id(item)
            if found:
                return found
    return None


def _detail_unit_price(product_info: dict[str, Any]) -> Decimal | None:
    sale_info = _dict_value(product_info.get("saleInfo"))
    price_candidates = [
        sale_info.get("price"),
        sale_info.get("consignPrice"),
        sale_info.get("retailPrice"),
        sale_info.get("amountOnSale"),
        product_info.get("price"),
    ]
    sku_infos = _list_value(
        sale_info.get("skuInfos")
        or product_info.get("skuInfos")
        or product_info.get("skuInfoList")
    )
    for sku in sku_infos:
        if isinstance(sku, dict):
            price_candidates.extend(
                [
                    sku.get("price"),
                    sku.get("consignPrice"),
                    _dict_value(sku.get("priceRange")).get("price"),
                ]
            )
    for value in price_candidates:
        price = decimal_value(value)
        if price is not None and price > 0:
            return _money(price)
    return None


def _detail_moq(product_info: dict[str, Any]) -> int | None:
    sale_info = _dict_value(product_info.get("saleInfo"))
    for key in ("minOrderQuantity", "amountOnSale", "batchNumber", "beginAmount"):
        parsed = _optional_int(sale_info.get(key) or product_info.get(key))
        if parsed:
            return parsed
    return None


def _freight_total_cny(payload: dict[str, Any]) -> Decimal | None:
    freight_model = _freight_model(payload)
    if _freight_free_postage(payload):
        return Decimal("0")
    for key in ("freight", "totalFreight", "fee", "postage"):
        value = decimal_value(freight_model.get(key))
        if value is not None and value >= 0:
            return _money(value)
    return None


def _freight_free_postage(payload: dict[str, Any]) -> bool:
    freight_model = _freight_model(payload)
    return freight_model.get("freePostage") is True or freight_model.get("free_postage") is True


def _freight_model(payload: dict[str, Any]) -> dict[str, Any]:
    result = _dict_value(payload.get("result"))
    nested = _dict_value(result.get("result"))
    if nested:
        return nested
    return result or payload


def _compact_api_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = _dict_value(payload.get("result"))
    return {
        "success": _openapi_success(payload),
        "message": _openapi_message(payload),
        "has_result": bool(result),
        "captured_at": datetime.now(UTC).isoformat(),
    }


def _openapi_success(payload: dict[str, Any]) -> bool | None:
    for value in (
        payload.get("success"),
        _dict_value(payload.get("result")).get("success"),
        _dict_value(_dict_value(payload.get("result")).get("result")).get("success"),
    ):
        if isinstance(value, bool):
            return value
    code = (
        payload.get("code")
        or _dict_value(payload.get("result")).get("code")
        or _dict_value(_dict_value(payload.get("result")).get("result")).get("code")
    )
    if code is not None:
        return str(code).upper() in {"S0000", "SUCCESS", "OK", "200"}
    return None


def _openapi_message(payload: dict[str, Any]) -> str | None:
    for value in (
        payload.get("message"),
        payload.get("error_message"),
        payload.get("errorMessage"),
        _dict_value(payload.get("result")).get("message"),
        _dict_value(payload.get("result")).get("error_message"),
        _dict_value(_dict_value(payload.get("result")).get("result")).get("message"),
    ):
        text = _optional_string(value)
        if text:
            return text
    return None


def _offer_id_from_url(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"/offer/([0-9]{6,})", value)
    if match:
        return match.group(1)
    return None


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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


def _flatten_params(params: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            output[key] = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            output[key] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            output[key] = str(value)
    return output


def _decimal_number(value: Any) -> float | None:
    decimal = decimal_value(value)
    return float(decimal) if decimal is not None else None


def _aop_timestamp() -> str:
    return str(int(datetime.now(UTC).timestamp() * 1000))


def _aop_signature(*, url_path: str, params: dict[str, Any], app_secret: str) -> str:
    flattened = _flatten_params(
        {key: value for key, value in params.items() if key != "_aop_signature"}
    )
    canonical = url_path + "".join(
        f"{key}{flattened[key]}" for key in sorted(flattened)
    )
    return hmac.new(
        app_secret.encode("utf-8"),
        canonical.encode("utf-8"),
        sha1,
    ).hexdigest().upper()


def _openapi_path(
    *,
    api_name: str,
    credentials: Alibaba1688Credentials,
    namespace: str | None = None,
) -> str:
    return (
        f"param2/{_openapi_version(credentials)}/"
        f"{namespace or _openapi_namespace(credentials)}/{api_name.strip()}/{credentials.app_key}"
    )


def _signature_path_for_url(
    url: str,
    *,
    api_name: str,
    credentials: Alibaba1688Credentials,
    namespace: str | None = None,
) -> str | None:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if path.startswith("openapi/"):
        path = path[len("openapi/") :]
    if path.startswith("param2/"):
        return path
    if not parsed.netloc or "1688.com" in parsed.netloc:
        return _openapi_path(
            api_name=api_name,
            credentials=credentials,
            namespace=namespace,
        )
    return None


def _openapi_base_url(credentials: Alibaba1688Credentials) -> str:
    return (
        os.getenv("RA_1688_OPEN_API_BASE_URL", "").strip()
        or credentials.api_base_url
        or DEFAULT_1688_OPEN_API_BASE_URL
    )


def _openapi_version(credentials: Alibaba1688Credentials) -> str:
    return (
        os.getenv("RA_1688_IMAGE_SEARCH_VERSION", "").strip()
        or credentials.image_search_version
        or "1"
    )


def _openapi_namespace(credentials: Alibaba1688Credentials) -> str:
    return (
        os.getenv("RA_1688_IMAGE_SEARCH_NAMESPACE", "").strip()
        or credentials.image_search_namespace
        or DEFAULT_1688_IMAGE_SEARCH_NAMESPACE
    )


def _env_or_credential(name: str, value: str | None) -> str | None:
    return os.getenv(name, "").strip() or value


def _bool_env(name: str) -> bool | None:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return None
    return value in {"1", "true", "yes", "y", "on"}


def _int_env(name: str) -> int | None:
    return _optional_int(os.getenv(name))
