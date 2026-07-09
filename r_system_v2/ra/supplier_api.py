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
from html import unescape
import hmac
import json
from math import ceil
import os
import re
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from r_system_v2.ra.profit_engine import decimal_value
from r_system_v2.ra.supplier_keyword_skill import extract_pack_count
from r_system_v2.rw.product_images import primary_product_image_url, product_image_candidates


DEFAULT_SUPPLIER_SOURCE_MODE = "auto_1688_api"
DEFAULT_1688_OPEN_API_BASE_URL = "https://gw.open.1688.com/openapi/param2"
DEFAULT_1688_IMAGE_SEARCH_NAMESPACE = "com.alibaba.linkplus"
DEFAULT_1688_IMAGE_SEARCH_API_NAME = "alibaba.cross.similar.offer.search"
DEFAULT_1688_KEYWORD_SEARCH_NAMESPACE = "com.alibaba.product"
DEFAULT_1688_KEYWORD_SEARCH_API_NAME = "product.search.keywordQuery"
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


@dataclass(frozen=True)
class DetailPageProbe:
    final_url: str | None
    title: str | None
    unit_price_cny: Decimal | None
    domestic_shipping_cny: Decimal | None
    moq: int | None
    sku_id: str | None
    spec_id: str | None
    sku_name: str | None
    pack_count: int | None
    actual_weight_kg: Decimal | None
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    one_piece_hint: bool
    status: str
    warning: str | None
    raw_excerpt: str | None


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
        if _keyword_search_enabled():
            try:
                keyword_payload = self._call_keyword_search(
                    product=product,
                    keyword_profile=keyword_profile,
                    limit=limit,
                )
                offers.extend(
                    _normalize_image_search_offers(
                        keyword_payload,
                        limit=limit,
                        source="alibaba1688_official_keyword_search",
                        api_family="1688_keyword_search",
                    )
                )
            except RASupplierApiError:
                pass
        offers = _dedupe_offers(offers, limit=max(limit, limit * 2))
        if not offers:
            return []
        return [
            self._enrich_offer(
                offer,
                product=product,
                keyword_profile=keyword_profile,
            )
            for offer in offers
        ]

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

    def _call_keyword_search(
        self,
        *,
        product: dict[str, Any],
        keyword_profile: dict[str, Any],
        limit: int,
    ) -> dict[str, Any]:
        api_name = os.getenv(
            "RA_1688_KEYWORD_SEARCH_API_NAME",
            DEFAULT_1688_KEYWORD_SEARCH_API_NAME,
        ).strip()
        namespace = os.getenv(
            "RA_1688_KEYWORD_SEARCH_NAMESPACE",
            DEFAULT_1688_KEYWORD_SEARCH_NAMESPACE,
        ).strip()
        keyword = _keyword_search_term(product=product, keyword_profile=keyword_profile)
        if not api_name or not keyword:
            raise RASupplierApiError("1688 关键词搜索 API 未配置或关键词为空。")
        params = {
            "param": {
                "keywords": keyword,
                "pageNum": 1,
                "pageSize": max(10, min(limit * 4, 20)),
                "priceStart": os.getenv("RA_1688_KEYWORD_PRICE_START", "0").strip(),
                "priceEnd": os.getenv("RA_1688_KEYWORD_PRICE_END", "999999").strip(),
                "quantityBegin": os.getenv("RA_1688_KEYWORD_QUANTITY_BEGIN", "1").strip(),
            }
        }
        category_ids = os.getenv("RA_1688_KEYWORD_CATEGORY_IDS", "").strip()
        if category_ids:
            params["param"]["categoryIds"] = category_ids
        return self._call_openapi(
            namespace=namespace,
            api_name=api_name,
            params=params,
            error_label="1688 关键词搜货",
            allow_business_error=True,
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

    def _enrich_offer(
        self,
        offer: SupplierApiOffer,
        *,
        product: dict[str, Any],
        keyword_profile: dict[str, Any],
    ) -> SupplierApiOffer:
        payload = dict(offer.payload or {})
        offer_id = _optional_string(payload.get("offer_id")) or _offer_id_from_url(
            offer.supplier_url
        )

        detail_probe = _crawl_1688_detail_page(
            offer.supplier_url,
            product=product,
            keyword_profile=keyword_profile,
        )
        detail_price = None
        detail_moq = None
        detail_sku_id = None
        if detail_probe:
            payload["detail_page_crawler"] = _detail_probe_payload(detail_probe)
            detail_price = detail_probe.unit_price_cny
            detail_moq = detail_probe.moq
            detail_sku_id = detail_probe.sku_id
            if detail_probe.spec_id:
                payload["spec_id"] = detail_probe.spec_id
            if detail_probe.sku_name:
                payload["sku_name"] = detail_probe.sku_name
            if detail_probe.pack_count:
                payload["supplier_pack_count"] = detail_probe.pack_count
            if detail_probe.actual_weight_kg is not None:
                payload["supplier_actual_weight_kg"] = _decimal_number(
                    detail_probe.actual_weight_kg
                )
            if detail_probe.length_cm is not None:
                payload["supplier_length_cm"] = _decimal_number(detail_probe.length_cm)
            if detail_probe.width_cm is not None:
                payload["supplier_width_cm"] = _decimal_number(detail_probe.width_cm)
            if detail_probe.height_cm is not None:
                payload["supplier_height_cm"] = _decimal_number(detail_probe.height_cm)

        if not offer_id and detail_probe and detail_probe.final_url:
            offer_id = _offer_id_from_url(detail_probe.final_url)
            if offer_id:
                payload["offer_id"] = offer_id
        if not offer_id:
            return replace(offer, payload=payload)

        detail_payload = self._call_product_info(offer_id)
        if detail_payload:
            payload["product_info_api"] = _compact_api_payload(detail_payload)
            product_info = _product_info_payload(detail_payload)
            sku_id = _extract_sku_id(product_info)
            if sku_id:
                payload["sku_id"] = sku_id
            product_info_price = _detail_unit_price(product_info)
            if product_info_price is not None:
                payload["product_info_unit_price_cny"] = _decimal_number(product_info_price)
            product_info_moq = _detail_moq(product_info)
            if product_info_moq is not None:
                payload["product_info_moq"] = product_info_moq
        else:
            sku_id = None

        sku_id = sku_id or detail_sku_id
        if sku_id:
            payload["sku_id"] = sku_id
        selected_moq = (
            _optional_int(payload.get("product_info_moq"))
            or detail_moq
            or offer.moq
            or 1
        )
        quantity = max(1, selected_moq)
        shipping = offer.domestic_shipping_cny
        if (
            detail_probe
            and detail_probe.domestic_shipping_cny is not None
            and not detail_probe.warning
        ):
            shipping = detail_probe.domestic_shipping_cny
            payload["domestic_shipping_cny"] = _decimal_number(shipping)
            payload["shipping_source"] = "1688_detail_page"

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

        if shipping is None:
            estimate = _estimate_domestic_shipping_cny(
                product=product,
                detail_probe=detail_probe,
                quantity=quantity,
            )
            if estimate is not None:
                shipping = estimate
                payload["domestic_shipping_cny"] = _decimal_number(estimate)
                payload["shipping_source"] = "estimated_default_freight_table"
                payload["freight_warning"] = (
                    "未获取官方 sku 运费，已按默认国内快递价格表估算。"
                )

        unit_price = offer.unit_price_cny
        if (
            detail_price is not None
            and detail_probe is not None
            and detail_probe.warning is None
            and _detail_price_can_override_official(detail_price, offer.unit_price_cny)
        ):
            unit_price = detail_price
            payload["unit_price_source"] = "1688_detail_page"
            payload["detail_page_unit_price_cny"] = _decimal_number(detail_price)
        elif detail_price is not None:
            payload["detail_page_unit_price_cny"] = _decimal_number(detail_price)
            payload["detail_page_price_ignored_reason"] = (
                detail_probe.warning
                if detail_probe is not None and detail_probe.warning
                else "详情页价格与官方图搜价格差距过大，疑似页面噪声，未覆盖官方价格。"
            )

        return replace(
            offer,
            unit_price_cny=unit_price,
            domestic_shipping_cny=shipping,
            moq=selected_moq,
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
    source: str = "alibaba1688_official_image_search",
    api_family: str = "1688_image_search",
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
                source=source,
                payload={
                    "official_api": True,
                    "api_family": api_family,
                    "offer_id": offer_id,
                    "title": title,
                    "unit": item.get("unit"),
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


def _dedupe_offers(offers: list[SupplierApiOffer], *, limit: int) -> list[SupplierApiOffer]:
    output: list[SupplierApiOffer] = []
    seen: set[str] = set()
    for offer in offers:
        payload = _dict_value(offer.payload)
        key = (
            _optional_string(payload.get("offer_id"))
            or _offer_id_from_url(offer.supplier_url)
            or offer.supplier_url
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(offer)
        if len(output) >= max(1, limit):
            break
    return output


def _keyword_search_enabled() -> bool:
    return os.getenv("RA_1688_KEYWORD_SEARCH_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _keyword_search_term(*, product: dict[str, Any], keyword_profile: dict[str, Any]) -> str | None:
    for value in (
        keyword_profile.get("product_type_zh"),
        *(_list_value(keyword_profile.get("core_keywords_zh"))[:3]),
        product.get("title_zh"),
    ):
        text = _optional_string(value)
        if text:
            return text[:80]
    title = _optional_string(product.get("title"))
    if title:
        return re.sub(r"[^A-Za-z0-9\u4e00-\u9fff ]+", " ", title).strip()[:80]
    return None


def _min_official_unit_price_cny() -> Decimal:
    value = os.getenv("RA_1688_MIN_UNIT_PRICE_CNY", "2").strip()
    parsed = decimal_value(value)
    if parsed is None or parsed < 0:
        return Decimal("2")
    return parsed


def _crawl_1688_detail_page(
    url: str,
    *,
    product: dict[str, Any],
    keyword_profile: dict[str, Any],
) -> DetailPageProbe | None:
    if not _detail_crawler_enabled() or not _is_1688_url(url):
        return None
    try:
        return _crawl_1688_detail_with_playwright(
            url,
            product=product,
            keyword_profile=keyword_profile,
        )
    except ModuleNotFoundError:
        return _crawl_1688_detail_with_html(
            url,
            status="html_fallback_playwright_unavailable",
            product=product,
            keyword_profile=keyword_profile,
        )
    except Exception as exc:
        fallback = _crawl_1688_detail_with_html(
            url,
            status="html_fallback_playwright_failed",
            product=product,
            keyword_profile=keyword_profile,
        )
        if fallback is None:
            return DetailPageProbe(
                final_url=url,
                title=None,
                unit_price_cny=None,
                domestic_shipping_cny=None,
                moq=None,
                sku_id=None,
                spec_id=None,
                sku_name=None,
                pack_count=None,
                actual_weight_kg=None,
                length_cm=None,
                width_cm=None,
                height_cm=None,
                one_piece_hint=False,
                status="failed",
                warning=f"1688 详情页补抓失败：{str(exc)[:180]}",
                raw_excerpt=None,
            )
        return replace(
            fallback,
            warning=f"Playwright 补抓失败，已使用普通 HTML 兜底：{str(exc)[:180]}",
        )


def _crawl_1688_detail_with_playwright(
    url: str,
    *,
    product: dict[str, Any],
    keyword_profile: dict[str, Any],
) -> DetailPageProbe:
    from playwright.sync_api import sync_playwright

    timeout_ms = _detail_crawler_timeout_ms()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            page = browser.new_page(
                locale="zh-CN",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(_detail_crawler_settle_ms())
            final_url = page.url
            title = page.title()
            html = page.content()
        finally:
            browser.close()
    return _parse_1688_detail_html(
        html,
        title=title,
        final_url=final_url,
        status="playwright",
        product=product,
        keyword_profile=keyword_profile,
    )


def _crawl_1688_detail_with_html(
    url: str,
    *,
    status: str,
    product: dict[str, Any],
    keyword_profile: dict[str, Any],
) -> DetailPageProbe | None:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=max(3, _detail_crawler_timeout_ms() / 1000)) as response:
            final_url = response.geturl()
            html = response.read(1_800_000).decode("utf-8", errors="replace")
    except Exception:
        return None
    return _parse_1688_detail_html(
        html,
        title=None,
        final_url=final_url,
        status=status,
        product=product,
        keyword_profile=keyword_profile,
    )


def _parse_1688_detail_html(
    html: str,
    *,
    title: str | None,
    final_url: str | None,
    status: str,
    product: dict[str, Any],
    keyword_profile: dict[str, Any],
) -> DetailPageProbe:
    text = unescape(html)
    page_title = _clean_detail_title(title or _extract_html_title(text))
    searchable_text = " ".join(
        value
        for value in (
            page_title,
            _raw_detail_excerpt(text, limit=3_000),
        )
        if value
    )
    unit_price = _extract_detail_price_cny(text)
    shipping = _extract_detail_shipping_cny(text)
    moq = _extract_detail_moq(text)
    length_cm, width_cm, height_cm = _extract_detail_dimensions_cm(searchable_text)
    actual_weight_kg = _extract_detail_weight_kg(searchable_text)
    sku_id = _extract_detail_identifier(
        text,
        keys=("skuId", "sku_id", "skuID", "skuMapId"),
    )
    spec_id = _extract_detail_identifier(
        text,
        keys=("specId", "spec_id", "specID"),
    )
    sku_name = _extract_detail_sku_name(text)
    pack_count = _extract_pack_count(searchable_text)
    one_piece_hint = bool(
        re.search(r"(?:一件代发|一件起批|1\s*件\s*起批|一件可发)", searchable_text)
    )
    warning = None
    if unit_price is None:
        warning = "1688 详情页未抓到可信 SKU 价格。"
    elif _detail_page_likely_mismatch(
        searchable_text,
        product=product,
        keyword_profile=keyword_profile,
    ):
        warning = "1688 详情页标题与 R-W 产品关键词弱匹配，利润结果需人工复核。"
    return DetailPageProbe(
        final_url=final_url,
        title=page_title,
        unit_price_cny=unit_price,
        domestic_shipping_cny=shipping,
        moq=moq,
        sku_id=sku_id,
        spec_id=spec_id,
        sku_name=sku_name,
        pack_count=pack_count,
        actual_weight_kg=actual_weight_kg,
        length_cm=length_cm,
        width_cm=width_cm,
        height_cm=height_cm,
        one_piece_hint=one_piece_hint,
        status=status,
        warning=warning,
        raw_excerpt=_raw_detail_excerpt(text),
    )


def _detail_probe_payload(probe: DetailPageProbe) -> dict[str, Any]:
    return {
        "status": probe.status,
        "final_url": probe.final_url,
        "title": probe.title,
        "unit_price_cny": _decimal_number(probe.unit_price_cny),
        "domestic_shipping_cny": _decimal_number(probe.domestic_shipping_cny),
        "moq": probe.moq,
        "sku_id": probe.sku_id,
        "spec_id": probe.spec_id,
        "sku_name": probe.sku_name,
        "pack_count": probe.pack_count,
        "actual_weight_kg": _decimal_number(probe.actual_weight_kg),
        "length_cm": _decimal_number(probe.length_cm),
        "width_cm": _decimal_number(probe.width_cm),
        "height_cm": _decimal_number(probe.height_cm),
        "one_piece_hint": probe.one_piece_hint,
        "warning": probe.warning,
        "raw_excerpt": probe.raw_excerpt,
        "captured_at": datetime.now(UTC).isoformat(),
    }


def _extract_detail_price_cny(text: str) -> Decimal | None:
    values: list[Decimal] = []
    patterns = (
        r'"(?:skuPrice|offerPrice|discountPrice|salePrice|unitPrice|wholesalePrice|activityPrice)"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)',
        r'"(?:priceRange|priceRangeOriginal|priceRangeStr)"\s*:\s*"?\s*([0-9]+(?:\.[0-9]{1,2})?)(?:\s*(?:-|~|—|至|到)\s*([0-9]+(?:\.[0-9]{1,2})?))?',
        r'(?:价格|批发价|拿货价|现货价|活动价)[^0-9￥¥]{0,24}(?:￥|¥)?\s*([0-9]+(?:\.[0-9]{1,2})?)',
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            for group in match.groups():
                value = decimal_value(group)
                if value is not None and Decimal("0.1") <= value <= Decimal("50000"):
                    values.append(value)
    minimum = _min_official_unit_price_cny()
    credible = [value for value in values if minimum <= value <= Decimal("50000")]
    if not credible:
        return None
    return _money(min(credible))


def _detail_price_can_override_official(
    detail_price: Decimal,
    official_price: Decimal,
) -> bool:
    if detail_price < _min_official_unit_price_cny():
        return False
    lower_bound = max(_min_official_unit_price_cny(), official_price * Decimal("0.5"))
    upper_bound = max(official_price * Decimal("3"), official_price + Decimal("20"))
    return lower_bound <= detail_price <= upper_bound


def _extract_detail_shipping_cny(text: str) -> Decimal | None:
    if re.search(r"(?:包邮|免运费|免邮)", text):
        return Decimal("0")
    match = re.search(
        r"(?:运费|邮费|快递|物流|配送)[^0-9￥¥]{0,30}(?:￥|¥)?\s*([0-9]+(?:\.[0-9]{1,2})?)",
        text,
    )
    if not match:
        return None
    value = decimal_value(match.group(1))
    if value is None or value < 0 or value > Decimal("5000"):
        return None
    return _money(value)


def _extract_detail_moq(text: str) -> int | None:
    patterns = (
        r'"(?:minOrderQuantity|beginAmount|batchNumber|quantityBegin)"\s*:\s*"?([1-9][0-9]{0,5})',
        r"(?:起批量|起订量|起批)[^0-9]{0,20}([1-9][0-9]{0,5})",
        r"([1-9][0-9]{0,5})\s*(?:件|个|套|只|箱|把)\s*起批",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _optional_int(match.group(1))
    return None


def _extract_detail_identifier(text: str, *, keys: tuple[str, ...]) -> str | None:
    key_pattern = "|".join(re.escape(key) for key in keys)
    patterns = (
        rf'"(?:{key_pattern})"\s*:\s*"?([A-Za-z0-9_-]{{3,80}})"?',
        rf"(?:{key_pattern})=([A-Za-z0-9_-]{{3,80}})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_detail_sku_name(text: str) -> str | None:
    for key in ("skuName", "specName", "specValue", "name"):
        match = re.search(
            rf'"{key}"\s*:\s*"([^"]{{1,120}})"',
            text,
            flags=re.IGNORECASE,
        )
        if match:
            cleaned = re.sub(r"\s+", " ", match.group(1)).strip()
            if cleaned and not re.search(r"^\d+$", cleaned):
                return cleaned[:120]
    return None


def _extract_detail_dimensions_cm(text: str) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:x|X|×|\*)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:x|X|×|\*)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(cm|厘米|mm|毫米|in|inch|英寸)?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return (None, None, None)
    values = [decimal_value(match.group(index)) for index in (1, 2, 3)]
    if any(value is None or value <= 0 for value in values):
        return (None, None, None)
    unit = (match.group(4) or "cm").lower()
    converted = [_dimension_to_cm(value, unit) for value in values if value is not None]
    if len(converted) != 3 or any(value is None for value in converted):
        return (None, None, None)
    return (_q2(converted[0]), _q2(converted[1]), _q2(converted[2]))


def _dimension_to_cm(value: Decimal, unit: str) -> Decimal | None:
    if unit in {"mm", "毫米"}:
        return value / Decimal("10")
    if unit in {"in", "inch", "英寸"}:
        return value * Decimal("2.54")
    return value


def _extract_detail_weight_kg(text: str) -> Decimal | None:
    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*(kg|千克|公斤|g|克|lb|lbs|pound|oz|盎司)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = decimal_value(match.group(1))
    if value is None or value <= 0:
        return None
    unit = match.group(2).lower()
    if unit in {"g", "克"}:
        value = value / Decimal("1000")
    elif unit in {"lb", "lbs", "pound"}:
        value = value * Decimal("0.45359237")
    elif unit in {"oz", "盎司"}:
        value = value * Decimal("0.0283495231")
    if value <= 0 or value > Decimal("200"):
        return None
    return _q4(value)


def _extract_pack_count(text: str) -> int | None:
    return extract_pack_count(text)


def _estimate_domestic_shipping_cny(
    *,
    product: dict[str, Any],
    detail_probe: DetailPageProbe | None,
    quantity: int,
) -> Decimal | None:
    actual_weight = (
        detail_probe.actual_weight_kg
        if detail_probe and detail_probe.actual_weight_kg is not None
        else _product_weight_kg(product)
    )
    length = (
        detail_probe.length_cm
        if detail_probe and detail_probe.length_cm is not None
        else _product_dimension_cm(product, "length")
    )
    width = (
        detail_probe.width_cm
        if detail_probe and detail_probe.width_cm is not None
        else _product_dimension_cm(product, "width")
    )
    height = (
        detail_probe.height_cm
        if detail_probe and detail_probe.height_cm is not None
        else _product_dimension_cm(product, "height")
    )
    volume_weight = _volume_weight_kg(length, width, height)
    chargeable = _max_decimal(actual_weight, volume_weight)
    if chargeable is None:
        fallback = decimal_value(os.getenv("RA_1688_EST_FREIGHT_FALLBACK_CNY", "10"))
        return _money(fallback) if fallback is not None and fallback >= 0 else None
    total_weight = chargeable * Decimal(str(max(1, quantity)))
    first_fee = decimal_value(os.getenv("RA_1688_EST_FREIGHT_FIRST_FEE_CNY", "8")) or Decimal("8")
    first_unit = decimal_value(os.getenv("RA_1688_EST_FREIGHT_FIRST_UNIT_KG", "1")) or Decimal("1")
    next_fee = decimal_value(os.getenv("RA_1688_EST_FREIGHT_NEXT_FEE_CNY", "4")) or Decimal("4")
    next_unit = decimal_value(os.getenv("RA_1688_EST_FREIGHT_NEXT_UNIT_KG", "1")) or Decimal("1")
    if first_unit <= 0 or next_unit <= 0:
        return None
    extra_weight = max(Decimal("0"), total_weight - first_unit)
    steps = Decimal(ceil(extra_weight / next_unit)) if extra_weight > 0 else Decimal("0")
    total = first_fee + steps * next_fee
    return _money(total / Decimal(str(max(1, quantity))))


def _detail_page_likely_mismatch(
    text: str,
    *,
    product: dict[str, Any],
    keyword_profile: dict[str, Any],
) -> bool:
    lowered = text.lower()
    product_title = str(product.get("title") or "")
    terms = [
        keyword_profile.get("product_type_zh"),
        *(_list_value(keyword_profile.get("core_keywords_zh"))[:4]),
        product.get("title_zh"),
        product.get("brand"),
        *_english_match_tokens(product_title),
    ]
    normalized_terms = [
        str(term).strip().lower()
        for term in terms
        if isinstance(term, str) and len(str(term).strip()) >= 2
    ]
    if not normalized_terms:
        return False
    return not any(term in lowered for term in normalized_terms)


def _english_match_tokens(text: str) -> list[str]:
    generic = {
        "for",
        "with",
        "and",
        "the",
        "outdoor",
        "indoor",
        "replacement",
        "compatible",
        "adjustable",
        "display",
        "size",
    }
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text or "")
        if token.lower() not in generic
    ]
    return tokens[:8]


def _product_weight_kg(product: dict[str, Any]) -> Decimal | None:
    features = _dict_value(product.get("features"))
    for key in ("package_weight_kg", "item_weight_kg"):
        value = decimal_value(features.get(key))
        if value is not None and value > 0:
            return value
    for key in ("package_weight_g", "item_weight_g"):
        value = decimal_value(features.get(key))
        if value is not None and value > 0:
            return value / Decimal("1000")
    return None


def _product_dimension_cm(product: dict[str, Any], name: str) -> Decimal | None:
    features = _dict_value(product.get("features"))
    for key in (f"package_{name}_cm", f"item_{name}_cm"):
        value = decimal_value(features.get(key))
        if value is not None and value > 0:
            return value
    for key in (f"package_{name}_mm", f"item_{name}_mm"):
        value = decimal_value(features.get(key))
        if value is not None and value > 0:
            return value / Decimal("10")
    return None


def _volume_weight_kg(
    length_cm: Decimal | None,
    width_cm: Decimal | None,
    height_cm: Decimal | None,
) -> Decimal | None:
    if (
        length_cm is None
        or width_cm is None
        or height_cm is None
        or length_cm <= 0
        or width_cm <= 0
        or height_cm <= 0
    ):
        return None
    return _q4((length_cm * width_cm * height_cm) / Decimal("6000"))


def _max_decimal(*values: Decimal | None) -> Decimal | None:
    present = [value for value in values if value is not None and value > 0]
    return max(present) if present else None


def _extract_html_title(text: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.S)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _clean_detail_title(title: str | None) -> str | None:
    if not title:
        return None
    cleaned = re.sub(r"\s+", " ", title).strip()
    cleaned = re.sub(r"[-_ ]*阿里巴巴.*$", "", cleaned).strip()
    return cleaned[:240] or None


def _raw_detail_excerpt(text: str, *, limit: int = 500) -> str | None:
    cleaned = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    return cleaned[:limit] or None


def _is_1688_url(url: str) -> bool:
    host = urlparse(str(url or "")).netloc.lower()
    return host == "1688.com" or host.endswith(".1688.com")


def _detail_crawler_enabled() -> bool:
    value = os.getenv("RA_1688_DETAIL_CRAWLER_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _detail_crawler_timeout_ms() -> int:
    value = _optional_int(os.getenv("RA_1688_DETAIL_CRAWLER_TIMEOUT_MS"))
    return max(3_000, min(value or 8_000, 20_000))


def _detail_crawler_settle_ms() -> int:
    value = _optional_int(os.getenv("RA_1688_DETAIL_CRAWLER_SETTLE_MS"))
    return max(300, min(value or 900, 5_000))


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


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
