"""Serper + supplier discovery for R-A profit analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from html import unescape
import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.ra.profit_engine import decimal_value
from r_system_v2.ra.profit_service import (
    RAProfitError,
    _ensure_candidate,
    _insert_supplier_offer,
    _json_bind,
    _load_product,
    run_profit_for_existing_offers,
)
from r_system_v2.ra.supplier_api import (
    Mock1688OfficialApiProvider,
    SupplierApiProvider,
    supplier_source_mode,
)
from r_system_v2.ra.providers import RAnalysisProviderBinding
from r_system_v2.ra.supplier_keyword_skill import (
    build_supplier_keyword_profile,
    evaluate_supplier_alignment,
)


SERPER_SEARCH_URL = "https://google.serper.dev/search"
DEFAULT_DISCOVERY_LIMIT = 5
MIN_DISCOVERY_LIMIT = 3
MAX_DISCOVERY_LIMIT = 5
DEFAULT_CRAWLER_TIMEOUT_MS = 8_000
SUPPLIER_PLATFORM_LABELS = {
    "1688": "1688",
    "pdd": "拼多多",
    "taobao": "淘宝/天猫",
    "jd": "京东",
}


class RASupplierDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SerperResult:
    title: str
    link: str
    snippet: str | None
    position: int | None


@dataclass(frozen=True)
class SupplierSearchQuery:
    query: str
    platform: str
    platform_label: str
    search_url: str


@dataclass(frozen=True)
class CrawledOffer:
    final_url: str | None
    title: str | None
    unit_price_cny: Decimal | None
    domestic_shipping_cny: Decimal | None
    moq: int | None
    crawler_status: str
    warning: str | None
    raw_excerpt: str | None
    one_piece_hint: bool = False


class Serper1688Client:
    def __init__(self, *, api_key: str, timeout_seconds: float = 12.0) -> None:
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, num: int = 10) -> list[SerperResult]:
        payload = {
            "q": query,
            "gl": "us",
            "hl": "zh-cn",
            "num": max(1, min(num, 20)),
        }
        request = Request(
            os.getenv("RA_SERPER_SEARCH_URL", SERPER_SEARCH_URL),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-API-KEY": self.api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RASupplierDiscoveryError(
                f"Serper 请求失败：HTTP {exc.code} {detail}"
            ) from exc
        except URLError as exc:
            raise RASupplierDiscoveryError(f"Serper 网络请求失败：{exc.reason}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RASupplierDiscoveryError("Serper 返回内容不是有效 JSON。") from exc

        organic = data.get("organic")
        if not isinstance(organic, list):
            return []

        results: list[SerperResult] = []
        for item in organic:
            if not isinstance(item, dict):
                continue
            link = str(item.get("link") or "").strip()
            if not link:
                continue
            results.append(
                SerperResult(
                    title=str(item.get("title") or "").strip(),
                    link=link,
                    snippet=str(item.get("snippet") or "").strip() or None,
                    position=_int_value(item.get("position")),
                )
            )
        return results


class Playwright1688Crawler:
    def __init__(self, *, timeout_ms: int | None = None) -> None:
        self.timeout_ms = timeout_ms or _crawler_timeout_ms()

    def crawl(self, url: str) -> CrawledOffer:
        if not _is_1688_url(url):
            return CrawledOffer(
                final_url=None,
                title=None,
                unit_price_cny=None,
                domestic_shipping_cny=None,
                moq=None,
                crawler_status="skipped_non_1688",
                warning="不是 1688 链接。",
                raw_excerpt=None,
            )

        try:
            return self._crawl_with_playwright(url)
        except ModuleNotFoundError:
            return self._crawl_with_html_fallback(url, "playwright_unavailable")
        except Exception as exc:  # pragma: no cover - depends on runtime browser.
            fallback = self._crawl_with_html_fallback(url, "playwright_failed")
            if fallback.warning:
                return fallback
            return CrawledOffer(
                final_url=fallback.final_url,
                title=fallback.title,
                unit_price_cny=fallback.unit_price_cny,
                domestic_shipping_cny=fallback.domestic_shipping_cny,
                moq=fallback.moq,
                crawler_status="playwright_failed",
                warning=f"Playwright 抓取失败，已尝试普通 HTML：{exc}",
                raw_excerpt=fallback.raw_excerpt,
            )

    def _crawl_with_playwright(self, url: str) -> CrawledOffer:
        from playwright.sync_api import sync_playwright

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
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(800)
                detail_url = _first_detail_offer_url(page, base_url=page.url)
                if detail_url and detail_url != page.url:
                    page.goto(
                        detail_url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )
                    page.wait_for_timeout(800)
                html = page.content()
                title = page.title()
                final_url = page.url
            finally:
                browser.close()
        return _parse_1688_html(
            html,
            title=title,
            crawler_status="playwright",
            final_url=final_url,
        )

    def _crawl_with_html_fallback(self, url: str, status: str) -> CrawledOffer:
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
            with urlopen(request, timeout=max(3, self.timeout_ms / 1000)) as response:
                html = response.read(1_500_000).decode("utf-8", errors="replace")
        except Exception as exc:
            return CrawledOffer(
                final_url=None,
                title=None,
                unit_price_cny=None,
                domestic_shipping_cny=None,
                moq=None,
                crawler_status=status,
                warning=f"1688 页面抓取失败：{exc}",
                raw_excerpt=None,
            )
        return _parse_1688_html(
            html,
            title=None,
            crawler_status=status,
            final_url=url,
        )


def discover_1688_supplier_offers(
    db: Session,
    *,
    org_id: str,
    asin: str,
    run_id: str | None = None,
    result_limit: int = DEFAULT_DISCOVERY_LIMIT,
    auto_calculate: bool = True,
    exchange_rate_usd_cny: Decimal | None = None,
    min_gross_margin: Decimal | None = None,
    serper_client: Serper1688Client | None = None,
    crawler: Playwright1688Crawler | None = None,
    supplier_api_provider: SupplierApiProvider | None = None,
) -> dict[str, object]:
    normalized_asin = asin.strip().upper()
    limit = _bounded_limit(result_limit)
    product = _load_product(db, normalized_asin)
    candidate_id = _ensure_candidate(
        db,
        org_id=org_id,
        product=product,
        run_id=run_id,
    )
    db.commit()
    keyword_profile = build_supplier_keyword_profile(db, org_id=org_id, product=product)
    if supplier_source_mode() != "serper_legacy":
        return _discover_with_supplier_api_provider(
            db,
            org_id=org_id,
            asin=normalized_asin,
            run_id=run_id,
            product=product,
            candidate_id=candidate_id,
            keyword_profile=keyword_profile,
            result_limit=limit,
            auto_calculate=auto_calculate,
            exchange_rate_usd_cny=exchange_rate_usd_cny,
            min_gross_margin=min_gross_margin,
            provider=supplier_api_provider or Mock1688OfficialApiProvider(),
        )
    client = serper_client or _serper_client(db, org_id=org_id)
    crawler = crawler or Playwright1688Crawler()
    _discard_db_transaction(db)
    search_queries = build_supplier_queries(product, keyword_profile=keyword_profile)
    queries = [item.query for item in search_queries]
    searches: list[dict[str, object]] = []
    offers: list[dict[str, object]] = []
    seen_links: set[str] = set()
    warnings: list[str] = []

    for search_query in search_queries:
        if len(offers) >= limit:
            break
        query = search_query.query
        search_id = str(uuid4())
        _discard_db_transaction(db)
        try:
            results = client.search(query, num=max(10, limit * 4))
            status = "complete"
        except RASupplierDiscoveryError as exc:
            results = []
            status = "failed"
            warnings.append(str(exc))
        _insert_supplier_search(
            db,
            search_id=search_id,
            org_id=org_id,
            candidate_id=candidate_id,
            asin=normalized_asin,
            run_id=run_id,
            query=query,
            status=status,
            result_count=len(results),
            payload={
                "platform": search_query.platform,
                "platform_label": search_query.platform_label,
                "search_url": search_query.search_url,
                "keyword_profile": keyword_profile,
                "results": [result.__dict__ for result in results],
                "searched_at": datetime.now(UTC).isoformat(),
            },
        )
        db.commit()
        searches.append(
            {
                "search_id": search_id,
                "query": query,
                "platform": search_query.platform,
                "platform_label": search_query.platform_label,
                "search_url": search_query.search_url,
                "status": status,
                "result_count": len(results),
            }
        )
        if status == "failed":
            continue

        for result in _ranked_supplier_results(results, platform=search_query.platform):
            if len(offers) >= limit:
                break
            normalized_link = _normalized_supplier_link(
                result.link,
                platform=search_query.platform,
            )
            if normalized_link is None or normalized_link in seen_links:
                continue
            seen_links.add(normalized_link)
            _discard_db_transaction(db)
            crawled = (
                crawler.crawl(normalized_link)
                if search_query.platform == "1688"
                else _serper_only_offer(
                    result,
                    normalized_link,
                    platform=search_query.platform,
                )
            )
            result_price = _result_price_cny(result)
            result_shipping = _result_shipping_cny(result)
            unit_price_cny, price_source, price_warning = _select_supplier_price(
                crawled.unit_price_cny,
                result_price,
                product=product,
                exchange_rate_usd_cny=exchange_rate_usd_cny,
                platform=search_query.platform,
            )
            supplier_name = (
                crawled.title
                or result.title
                or f"{search_query.platform_label}供应商"
            )
            alignment = evaluate_supplier_alignment(
                db=db,
                org_id=org_id,
                product=product,
                keyword_profile=keyword_profile,
                supplier_title=supplier_name,
                supplier_snippet=result.snippet,
                raw_excerpt=crawled.raw_excerpt,
                unit_price_cny=unit_price_cny,
            )
            alignment_status = str(alignment.get("match_status") or "review")
            alignment_price = decimal_value(alignment.get("adjusted_unit_price_cny"))
            if alignment_status == "match" and alignment_price is not None:
                unit_price_cny = alignment_price
            elif alignment_status != "match":
                unit_price_cny = None
            domestic_shipping_cny = (
                crawled.domestic_shipping_cny
                if crawled.domestic_shipping_cny is not None
                else result_shipping
            )
            supplier_url = _supplier_detail_url(
                crawled.final_url,
                normalized_link,
                platform=search_query.platform,
            )
            if supplier_url is None:
                warnings.append(
                    f"{normalized_asin}: 未找到可打开的{search_query.platform_label}详情页链接。"
                )
                continue
            alignment_warning = (
                None
                if alignment_status == "match"
                else str(alignment.get("match_reason") or "供应商匹配待人工确认。")
            )
            crawler_warning = alignment_warning or price_warning or (
                None if unit_price_cny is not None else crawled.warning
            )
            offer_status = _offer_status(
                unit_price_cny=unit_price_cny,
                alignment_status=alignment_status,
            )
            match_score = min(
                _match_score(result, crawled),
                _int_value(alignment.get("match_score")) or 0,
            )
            offer_id = _insert_supplier_offer(
                db,
                org_id=org_id,
                search_id=search_id,
                candidate_id=candidate_id,
                asin=normalized_asin,
                supplier_name=supplier_name,
                supplier_url=supplier_url,
                unit_price_cny=unit_price_cny,
                domestic_shipping_cny=domestic_shipping_cny,
                moq=crawled.moq,
                source=f"serper_{search_query.platform}",
                match_score=match_score,
                offer_status=offer_status,
                payload_extra={
                    "platform": search_query.platform,
                    "platform_label": search_query.platform_label,
                    "supplier_url_type": "detail",
                    "supplier_detail_url": supplier_url,
                    "supplier_search_url": search_query.search_url,
                    "search_url": search_query.search_url,
                    "choice_page_url": search_query.search_url,
                    "result_url": result.link,
                    "serper_title": result.title,
                    "serper_snippet": result.snippet,
                    "serper_position": result.position,
                    "crawler_status": crawled.crawler_status,
                    "crawler_warning": crawler_warning,
                    "price_source": price_source,
                    "raw_crawled_price_cny": _decimal_number(crawled.unit_price_cny),
                    "raw_serper_price_cny": _decimal_number(result_price),
                    "raw_selected_price_cny": _decimal_number(
                        alignment.get("raw_unit_price_cny")
                    ),
                    "adjusted_unit_price_cny": _decimal_number(unit_price_cny),
                    "raw_excerpt": crawled.raw_excerpt,
                    "one_piece_hint": _one_piece_hint(result, crawled),
                    "retail_platform_hint": search_query.platform != "1688",
                    "keyword_profile": keyword_profile,
                    "supplier_alignment": alignment,
                    "shipping_notice": (
                        f"{search_query.platform_label}页面显示包邮或抓取到运费"
                        if domestic_shipping_cny is not None
                        else None
                    ),
                },
            )
            db.commit()
            offers.append(
                {
                    "offer_id": offer_id,
                    "search_id": search_id,
                    "supplier_name": supplier_name,
                    "supplier_url": supplier_url,
                    "supplier_platform": search_query.platform,
                    "supplier_platform_label": search_query.platform_label,
                    "supplier_url_type": "detail",
                    "supplier_detail_url": supplier_url,
                    "supplier_search_url": search_query.search_url,
                    "unit_price_cny": _decimal_number(unit_price_cny),
                    "domestic_shipping_cny": _decimal_number(domestic_shipping_cny),
                    "moq": crawled.moq,
                    "match_score": match_score,
                    "one_piece_hint": _one_piece_hint(result, crawled),
                    "offer_status": offer_status,
                    "crawler_status": crawled.crawler_status,
                    "warning": crawler_warning,
                    "keyword_profile": keyword_profile,
                    "supplier_alignment": alignment,
                }
            )

    priced_count = sum(1 for offer in offers if offer["unit_price_cny"] is not None)
    profit_run: dict[str, object] | None = None
    min_profit_suppliers = _min_profit_supplier_count()
    if auto_calculate and priced_count >= min_profit_suppliers:
        profit_run = run_profit_for_existing_offers(
            db,
            org_id=org_id,
            asin=normalized_asin,
            candidate_id=candidate_id,
            limit=limit,
            exchange_rate_usd_cny=exchange_rate_usd_cny,
            min_gross_margin=min_gross_margin,
        )
    else:
        if auto_calculate and priced_count > 0:
            warnings.append(
                f"{normalized_asin}: 可靠可定价供应商仅 {priced_count} 条，"
                f"不足 {min_profit_suppliers} 条，未生成正式利润结论。"
            )
        db.commit()

    return {
        "asin": normalized_asin,
        "candidate_id": candidate_id,
        "queries": queries,
        "searches": searches,
        "offers": offers,
        "profit_run": profit_run,
        "keyword_profile": keyword_profile,
        "counts": {
            "searches": len(searches),
            "candidate_offers": len(offers),
            "priced_offers": priced_count,
        },
        "warnings": warnings,
    }


def _discover_with_supplier_api_provider(
    db: Session,
    *,
    org_id: str,
    asin: str,
    run_id: str | None,
    product: dict[str, Any],
    candidate_id: str,
    keyword_profile: dict[str, Any],
    result_limit: int,
    auto_calculate: bool,
    exchange_rate_usd_cny: Decimal | None,
    min_gross_margin: Decimal | None,
    provider: SupplierApiProvider,
) -> dict[str, object]:
    search_id = str(uuid4())
    base_query = str(
        keyword_profile.get("product_type_zh")
        or product.get("title_zh")
        or product.get("title")
        or asin
    ).strip()
    query = f"1688官方API同类商品：{base_query[:80]}"
    offers_from_api = provider.search_offers(
        product=product,
        keyword_profile=keyword_profile,
        limit=result_limit,
    )
    _insert_supplier_search(
        db,
        search_id=search_id,
        org_id=org_id,
        candidate_id=candidate_id,
        asin=asin,
        run_id=run_id,
        query=query,
        provider=provider.provider_name,
        status="complete",
        result_count=len(offers_from_api),
        payload={
            "provider": provider.provider_name,
            "platform": "1688",
            "platform_label": "1688",
            "keyword_profile": keyword_profile,
            "searched_at": datetime.now(UTC).isoformat(),
            "mocked": provider.provider_name == "mock_1688_api",
            "results": [
                {
                    "supplier_name": offer.supplier_name,
                    "supplier_url": offer.supplier_url,
                    "title": offer.title,
                    "unit_price_cny": _decimal_number(offer.unit_price_cny),
                    "domestic_shipping_cny": _decimal_number(offer.domestic_shipping_cny),
                    "moq": offer.moq,
                    "match_score": offer.match_score,
                    "stock": offer.stock,
                    "monthly_sales": offer.monthly_sales,
                }
                for offer in offers_from_api
            ],
        },
    )
    db.commit()

    offers: list[dict[str, object]] = []
    for offer in offers_from_api:
        offer_id = _insert_supplier_offer(
            db,
            org_id=org_id,
            search_id=search_id,
            candidate_id=candidate_id,
            asin=asin,
            supplier_name=offer.supplier_name,
            supplier_url=offer.supplier_url,
            unit_price_cny=offer.unit_price_cny,
            domestic_shipping_cny=offer.domestic_shipping_cny,
            moq=offer.moq,
            rating=offer.rating,
            source=provider.provider_name,
            match_score=offer.match_score,
            offer_status="selected",
            payload_extra={
                "platform": offer.platform,
                "platform_label": offer.platform_label,
                "supplier_url_type": "detail",
                "supplier_detail_url": offer.supplier_url,
                "supplier_search_url": None,
                "search_url": None,
                "choice_page_url": None,
                "crawler_status": provider.provider_name,
                "crawler_warning": None,
                "price_source": provider.provider_name,
                "one_piece_hint": offer.one_piece_hint,
                "stock": offer.stock,
                "monthly_sales": offer.monthly_sales,
                "keyword_profile": keyword_profile,
                "supplier_alignment": {
                    "match_status": "match",
                    "match_score": offer.match_score,
                    "match_reason": "1688 官方 API mock 返回同类商品候选，等待真实 API 后替换为官方结果。",
                    "same_product_type": True,
                    "brand_risk": False,
                    "shape_conflict": False,
                    "warnings": [],
                },
                "shipping_notice": (
                    "1688 官方 API mock 返回供应商运费"
                    if offer.domestic_shipping_cny is not None
                    else None
                ),
                **(offer.payload or {}),
            },
        )
        db.commit()
        offers.append(
            {
                "offer_id": offer_id,
                "search_id": search_id,
                "supplier_name": offer.supplier_name,
                "supplier_url": offer.supplier_url,
                "supplier_platform": offer.platform,
                "supplier_platform_label": offer.platform_label,
                "supplier_url_type": "detail",
                "supplier_detail_url": offer.supplier_url,
                "supplier_search_url": None,
                "unit_price_cny": _decimal_number(offer.unit_price_cny),
                "domestic_shipping_cny": _decimal_number(offer.domestic_shipping_cny),
                "moq": offer.moq,
                "match_score": offer.match_score,
                "one_piece_hint": offer.one_piece_hint,
                "offer_status": "selected",
                "crawler_status": provider.provider_name,
                "warning": None,
                "keyword_profile": keyword_profile,
                "supplier_alignment": {
                    "match_status": "match",
                    "match_score": offer.match_score,
                    "match_reason": "1688 官方 API mock 返回同类商品候选。",
                },
            }
        )

    priced_count = sum(1 for offer in offers if offer["unit_price_cny"] is not None)
    profit_run: dict[str, object] | None = None
    min_profit_suppliers = _min_profit_supplier_count()
    warnings: list[str] = []
    if auto_calculate and priced_count >= min_profit_suppliers:
        profit_run = run_profit_for_existing_offers(
            db,
            org_id=org_id,
            asin=asin,
            candidate_id=candidate_id,
            limit=result_limit,
            exchange_rate_usd_cny=exchange_rate_usd_cny,
            min_gross_margin=min_gross_margin,
        )
    elif auto_calculate:
        warnings.append(
            f"{asin}: 可靠可定价供应商仅 {priced_count} 条，不足 {min_profit_suppliers} 条，未生成正式利润结论。"
        )
        db.commit()

    return {
        "asin": asin,
        "candidate_id": candidate_id,
        "queries": [query],
        "searches": [
            {
                "search_id": search_id,
                "query": query,
                "platform": "1688",
                "platform_label": "1688",
                "search_url": None,
                "status": "complete",
                "result_count": len(offers_from_api),
                "provider": provider.provider_name,
            }
        ],
        "offers": offers,
        "profit_run": profit_run,
        "keyword_profile": keyword_profile,
        "counts": {
            "searches": 1,
            "candidate_offers": len(offers),
            "priced_offers": priced_count,
        },
        "warnings": warnings,
    }


def build_1688_queries(product: dict[str, Any]) -> list[str]:
    return [item.query for item in build_supplier_queries(product) if item.platform == "1688"]


def build_supplier_queries(
    product: dict[str, Any],
    *,
    keyword_profile: dict[str, Any] | None = None,
) -> list[SupplierSearchQuery]:
    profile = keyword_profile or build_supplier_keyword_profile(None, org_id=None, product=product)
    base = _clean_query_text(profile.get("product_type_zh")) or _clean_query_text(
        product.get("title_zh") or product.get("title")
    )
    if not base:
        raise RAProfitError("该产品缺少标题，无法搜索 1688。")
    search_queries = profile.get("search_queries") if isinstance(profile, dict) else {}
    if not isinstance(search_queries, dict):
        search_queries = {}
    queries: list[SupplierSearchQuery] = []
    for platform in ("1688", "pdd", "taobao", "jd"):
        platform_queries = search_queries.get(platform)
        if not isinstance(platform_queries, list) or not platform_queries:
            platform_queries = _default_platform_queries(base, platform)
        for query in platform_queries:
            cleaned_query = _clean_query_text(query)
            if not cleaned_query:
                continue
            queries.append(
                _supplier_search_query(
                    platform,
                    cleaned_query,
                    base,
                )
            )
    return _dedupe_preserve_order(queries)


def _supplier_search_query(platform: str, query: str, base_keyword: str) -> SupplierSearchQuery:
    return SupplierSearchQuery(
        query=query,
        platform=platform,
        platform_label=SUPPLIER_PLATFORM_LABELS.get(platform, platform),
        search_url=_platform_search_url(platform, base_keyword),
    )


def _default_platform_queries(base: str, platform: str) -> list[str]:
    if platform == "1688":
        return [
            f"{base} 一件代发",
            f"{base} 一件起批",
            f"{base} 批发 厂家",
            f"{base} 现货",
        ]
    if platform == "pdd":
        return [f"拼多多 {base}", f"{base} 拼多多 现货"]
    if platform == "taobao":
        return [f"淘宝 {base}", f"{base} 淘宝 同款"]
    if platform == "jd":
        return [f"京东 {base}", f"{base} 京东 现货"]
    return [base]


def _platform_search_url(platform: str, keyword: str) -> str:
    encoded = quote_plus(keyword)
    if platform == "1688":
        return f"https://s.1688.com/selloffer/offer_search.htm?keywords={encoded}"
    if platform == "pdd":
        return f"https://mobile.yangkeduo.com/search_result.html?search_key={encoded}"
    if platform == "taobao":
        return f"https://s.taobao.com/search?q={encoded}"
    if platform == "jd":
        return f"https://search.jd.com/Search?keyword={encoded}&enc=utf-8"
    return f"https://www.google.com/search?q={encoded}"


def _serper_client(db: Session, *, org_id: str) -> Serper1688Client:
    last_error: Exception | None = None
    for _ in range(2):
        _discard_db_transaction(db)
        try:
            api_key = RAnalysisProviderBinding(
                org_id=org_id,
                secret_manager=SecretManager(db_session=db),
            ).serper_key()
            _discard_db_transaction(db)
            break
        except SecretManagerError as exc:
            _discard_db_transaction(db)
            raise RASupplierDiscoveryError("R-A 没有绑定 Serper key。") from exc
        except Exception as exc:
            last_error = exc
            _discard_db_transaction(db)
    else:
        raise RASupplierDiscoveryError(
            f"R-A Serper key 读取失败：{str(last_error)[:180]}"
        )
    if not api_key.strip():
        raise RASupplierDiscoveryError("R-A 没有绑定 Serper key。")
    return Serper1688Client(api_key=api_key)


def _discard_db_transaction(db: Session) -> None:
    try:
        if db.in_transaction() or db.in_nested_transaction():
            db.rollback()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _insert_supplier_search(
    db: Session,
    *,
    search_id: str,
    org_id: str,
    candidate_id: str,
    asin: str,
    run_id: str | None,
    query: str,
    status: str,
    result_count: int,
    payload: dict[str, Any],
    provider: str = "serper",
) -> None:
    db.execute(
        text(
            f"""
            INSERT INTO ra_supplier_searches (
              id, org_id, candidate_id, asin, query, provider, status,
              result_count, run_id, payload
            )
            VALUES (
              :id, :org_id, :candidate_id, :asin, :query, :provider,
              :status, :result_count, :run_id, {_json_bind(db, "payload")}
            )
            """
        ),
        {
            "id": search_id,
            "org_id": org_id,
            "candidate_id": candidate_id,
            "asin": asin,
            "run_id": run_id,
            "query": query,
            "provider": provider,
            "status": status,
            "result_count": result_count,
            "payload": json.dumps(payload, ensure_ascii=False),
        },
    )


def _parse_1688_html(
    html: str,
    *,
    title: str | None,
    crawler_status: str,
    final_url: str | None = None,
) -> CrawledOffer:
    text = unescape(html)
    page_title = title or _extract_title(text)
    unit_price = _extract_price_cny(text)
    shipping = _extract_shipping_cny(text)
    moq = _extract_moq(text)
    one_piece_hint = bool(re.search(r"(?:一件代发|一件起批|1\s*件\s*起批|一件可发)", text))
    warning = None
    if unit_price is None:
        warning = "未从 1688 页面抓到明确价格，可能需要登录态或页面反爬。"
    return CrawledOffer(
        final_url=final_url,
        title=_clean_page_title(page_title),
        unit_price_cny=unit_price,
        domestic_shipping_cny=shipping,
        moq=moq,
        crawler_status=crawler_status,
        warning=warning,
        raw_excerpt=_raw_excerpt(text),
        one_piece_hint=one_piece_hint,
    )


def _first_detail_offer_url(page: Any, *, base_url: str) -> str | None:
    if "detail.1688.com/offer/" in base_url:
        return None
    try:
        href = page.locator('a[href*="detail.1688.com/offer/"]').first.get_attribute(
            "href",
            timeout=2_000,
        )
    except Exception:
        return None
    if not href:
        return None
    return _canonical_1688_offer_url(urljoin(base_url, href)) or urljoin(base_url, href)


def _extract_price_cny(text: str) -> Decimal | None:
    strong_values = _extract_price_range_matches(text)
    strong_values.extend(
        _extract_decimal_matches(
            text,
            (
                r'"(?:skuPrice|offerPrice|discountPrice|salePrice|unitPrice|wholesalePrice|activityPrice)"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)',
                r'(?:价格|批发价|拿货价|现货价|到手价|活动价)[^0-9￥¥]{0,20}(?:￥|¥)?\s*([0-9]+(?:\.[0-9]{1,2})?)',
            ),
        )
    )
    strong_values = _credible_price_values(strong_values)
    if strong_values:
        return min(strong_values)

    money_values = _extract_contextual_money_values(text)
    if money_values:
        return min(money_values)

    weak_values = _extract_decimal_matches(
        text,
        (r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)',),
    )
    weak_values = _credible_price_values(weak_values, min_value=Decimal("2"))
    if weak_values:
        return min(weak_values)
    return None


def _result_price_cny(result: SerperResult) -> Decimal | None:
    text = " ".join(value for value in (result.title, result.snippet) if value)
    return _extract_price_cny(text)


def _result_shipping_cny(result: SerperResult) -> Decimal | None:
    text = " ".join(value for value in (result.title, result.snippet) if value)
    return _extract_shipping_cny(text)


def _extract_decimal_matches(text: str, patterns: tuple[str, ...]) -> list[Decimal]:
    values: list[Decimal] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = decimal_value(match.group(1))
            if value is not None and Decimal("0.1") <= value <= Decimal("50000"):
                values.append(value)
    return values


def _extract_price_range_matches(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    patterns = (
        r'"(?:priceRange|priceRangeOriginal|priceRangeStr)"\s*:\s*"?\s*([0-9]+(?:\.[0-9]{1,2})?)(?:\s*(?:-|~|—|至|到)\s*([0-9]+(?:\.[0-9]{1,2})?))?',
        r'(?:￥|¥)\s*([0-9]+(?:\.[0-9]{1,2})?)\s*(?:-|~|—|至|到)\s*(?:￥|¥)?\s*([0-9]+(?:\.[0-9]{1,2})?)',
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            for group in match.groups():
                value = decimal_value(group)
                if value is not None and Decimal("0.1") <= value <= Decimal("50000"):
                    values.append(value)
    return values


def _extract_contextual_money_values(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for match in re.finditer(r"(?:￥|¥)\s*([0-9]+(?:\.[0-9]{1,2})?)", text):
        start = max(0, match.start() - 12)
        end = min(len(text), match.end() + 8)
        context = text[start:end]
        if re.search(r"(?:运费|邮费|快递|物流|配送|起批|起订|优惠券|满减|立减|库存|销量|月销|评价|评分)", context):
            continue
        value = decimal_value(match.group(1))
        if value is not None and Decimal("0.1") <= value <= Decimal("50000"):
            values.append(value)
    return _credible_price_values(values)


def _credible_price_values(
    values: list[Decimal],
    *,
    min_value: Decimal = Decimal("0.1"),
) -> list[Decimal]:
    if not values:
        return []
    values = [value for value in values if min_value <= value <= Decimal("50000")]
    if not values:
        return []
    high_values = [value for value in values if value >= Decimal("5")]
    if high_values:
        return high_values
    return values


def _select_supplier_price(
    crawled_price: Decimal | None,
    result_price: Decimal | None,
    *,
    product: dict[str, Any],
    exchange_rate_usd_cny: Decimal | None,
    platform: str,
) -> tuple[Decimal | None, str | None, str | None]:
    candidates = [
        (
            crawled_price,
            "1688_page" if platform == "1688" else "supplier_page",
        ),
        (result_price, "serper_snippet"),
    ]
    warnings: list[str] = []
    for price, source in candidates:
        if price is None:
            continue
        warning = _supplier_price_warning(
            price,
            product=product,
            exchange_rate_usd_cny=exchange_rate_usd_cny,
        )
        if warning is None:
            return price, source, None
        warnings.append(warning)
    return None, None, warnings[0] if warnings else None


def _supplier_price_warning(
    price: Decimal,
    *,
    product: dict[str, Any],
    exchange_rate_usd_cny: Decimal | None,
) -> str | None:
    if price <= 0:
        return "供应商价格小于等于 0，疑似页面解析错误，已暂停利润计算。"
    if price < Decimal("2"):
        return f"供应商价格 {price} 元过低，疑似页面数量/噪声字段，已暂停利润计算。"

    sell_price_usd = decimal_value(product.get("price"))
    if sell_price_usd is None or exchange_rate_usd_cny is None:
        return None
    if sell_price_usd < Decimal("15"):
        return None
    minimum_reasonable = max(
        Decimal("3"),
        sell_price_usd * exchange_rate_usd_cny * Decimal("0.02"),
    )
    if price < minimum_reasonable:
        return (
            f"供应商价格 {price} 元明显低于亚马逊售价，"
            "疑似页面数量/噪声字段，已暂停利润计算。"
        )
    return None


def _extract_shipping_cny(text: str) -> Decimal | None:
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
    return value


def _extract_moq(text: str) -> int | None:
    patterns = (
        r"(?:起批量|起订量|起批)[^0-9]{0,20}([1-9][0-9]{0,5})",
        r"([1-9][0-9]{0,5})\s*(?:件|个|套|只|箱|把)\s*起批",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _int_value(match.group(1))
    return None


def _extract_title(text: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.S)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _clean_page_title(title: str | None) -> str | None:
    if not title:
        return None
    cleaned = re.sub(r"\s+", " ", title).strip()
    cleaned = re.sub(r"[-_ ]*阿里巴巴.*$", "", cleaned).strip()
    return cleaned[:240] or None


def _raw_excerpt(text: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    return cleaned[:500] or None


def _match_score(result: SerperResult, crawled: CrawledOffer) -> int:
    score = 80
    if result.position:
        score -= min(20, max(0, result.position - 1) * 2)
    if crawled.unit_price_cny is not None:
        score += 10
    if _one_piece_hint(result, crawled):
        score += 8
    if crawled.moq is not None:
        if crawled.moq <= 1:
            score += 12
        elif crawled.moq <= 5:
            score += 6
        elif crawled.moq > 20:
            score -= 10
    return max(0, min(100, score))


def _one_piece_hint(result: SerperResult, crawled: CrawledOffer) -> bool:
    if crawled.one_piece_hint:
        return True
    combined = " ".join(
        value
        for value in (result.title, result.snippet, crawled.title, crawled.raw_excerpt)
        if value
    )
    return bool(re.search(r"(?:一件代发|一件起批|1\s*件\s*起批|一件可发)", combined))


def _ranked_1688_results(results: list[SerperResult]) -> list[SerperResult]:
    return _ranked_supplier_results(results, platform="1688")


def _ranked_supplier_results(
    results: list[SerperResult],
    *,
    platform: str,
) -> list[SerperResult]:
    return sorted(
        results,
        key=lambda result: (
            0 if _supplier_detail_url(result.link, result.link, platform=platform) else 1,
            0 if _is_platform_url(result.link, platform=platform) else 1,
            result.position or 999,
        ),
    )


def _serper_only_offer(
    result: SerperResult,
    normalized_link: str,
    *,
    platform: str,
) -> CrawledOffer:
    price = _result_price_cny(result)
    return CrawledOffer(
        final_url=normalized_link,
        title=result.title or None,
        unit_price_cny=price,
        domestic_shipping_cny=_result_shipping_cny(result),
        moq=1,
        crawler_status="serper_result",
        warning=None
        if price is not None
        else f"{SUPPLIER_PLATFORM_LABELS.get(platform, platform)}详情页暂未抓取价格，仅保留候选链接。",
        raw_excerpt=result.snippet,
        one_piece_hint=True,
    )


def _supplier_detail_url(
    final_url: str | None,
    normalized_link: str,
    *,
    platform: str = "1688",
) -> str | None:
    if platform == "pdd":
        return _canonical_pdd_product_url(final_url) or _canonical_pdd_product_url(
            normalized_link
        )
    if platform == "taobao":
        return _canonical_taobao_product_url(final_url) or _canonical_taobao_product_url(
            normalized_link
        )
    if platform == "jd":
        return _canonical_jd_product_url(final_url) or _canonical_jd_product_url(
            normalized_link
        )
    canonical = _canonical_1688_offer_url(final_url) or _canonical_1688_offer_url(
        normalized_link
    )
    if canonical:
        return canonical
    if _is_1688_url(normalized_link) and not _is_login_url(normalized_link):
        parsed = urlparse(normalized_link)
        if "/offer/" in parsed.path:
            return normalized_link
    return None


def _normalized_supplier_link(url: str, *, platform: str) -> str | None:
    if platform == "1688":
        return _normalized_1688_link(url)
    if platform == "pdd":
        return _canonical_pdd_product_url(url)
    if platform == "taobao":
        return _canonical_taobao_product_url(url)
    if platform == "jd":
        return _canonical_jd_product_url(url)
    return None


def _is_login_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == "login.taobao.com" or host.endswith(".login.taobao.com") or "login.1688.com" in host


def _is_platform_url(url: str, *, platform: str) -> bool:
    if platform == "1688":
        return _is_1688_url(url)
    if platform == "pdd":
        return _is_pdd_url(url)
    if platform == "taobao":
        return _is_taobao_url(url)
    if platform == "jd":
        return _is_jd_url(url)
    return False


def _is_1688_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == "1688.com" or host.endswith(".1688.com")


def _is_pdd_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return (
        host == "pinduoduo.com"
        or host.endswith(".pinduoduo.com")
        or host == "yangkeduo.com"
        or host.endswith(".yangkeduo.com")
    )


def _is_taobao_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return (
        host == "taobao.com"
        or host.endswith(".taobao.com")
        or host == "tmall.com"
        or host.endswith(".tmall.com")
    )


def _is_jd_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == "jd.com" or host.endswith(".jd.com")


def _normalized_1688_link(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return None
    if not _is_1688_url(url):
        return None
    normalized = parsed._replace(fragment="").geturl()
    return _canonical_1688_offer_url(normalized) or normalized


def _canonical_1688_offer_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme or not _is_1688_url(parsed.geturl()):
        return None
    match = re.search(r"/offer/([0-9]{6,})", parsed.path)
    if not match:
        match = re.search(r"(?:offerId|offer_id|id)=([0-9]{6,})", parsed.query)
    if not match:
        return None
    return f"https://detail.1688.com/offer/{match.group(1)}.html"


def _canonical_pdd_product_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme or not _is_pdd_url(parsed.geturl()):
        return None
    match = re.search(r"(?:goods_id|goodsId)=([0-9]{6,})", parsed.query)
    if not match:
        match = re.search(r"/goods(?:/|_)([0-9]{6,})", parsed.path)
    if not match and parsed.path.endswith("/goods.html"):
        return parsed._replace(fragment="").geturl()
    if not match:
        return None
    return f"https://mobile.yangkeduo.com/goods.html?goods_id={match.group(1)}"


def _canonical_taobao_product_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme or not _is_taobao_url(parsed.geturl()) or _is_login_url(parsed.geturl()):
        return None
    match = re.search(r"(?:^|&)id=([0-9]{6,})(?:&|$)", parsed.query)
    if not match:
        return None
    return f"https://item.taobao.com/item.htm?id={match.group(1)}"


def _canonical_jd_product_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme or not _is_jd_url(parsed.geturl()):
        return None
    match = re.search(r"/([0-9]{6,})\.html", parsed.path)
    if not match:
        match = re.search(r"/product/([0-9]{6,})", parsed.path)
    if not match:
        return None
    return f"https://item.jd.com/{match.group(1)}.html"


def _bounded_limit(value: int) -> int:
    return max(MIN_DISCOVERY_LIMIT, min(MAX_DISCOVERY_LIMIT, int(value)))


def _offer_status(
    *,
    unit_price_cny: Decimal | None,
    alignment_status: str,
) -> str:
    if alignment_status == "mismatch":
        return "match_rejected"
    if alignment_status == "review":
        return "variant_pending"
    return "priced" if unit_price_cny is not None else "price_pending"


def _min_profit_supplier_count() -> int:
    raw_value = os.getenv("RA_MIN_VALID_SUPPLIERS_FOR_PROFIT")
    if not raw_value:
        return MIN_DISCOVERY_LIMIT
    try:
        parsed = int(raw_value)
    except ValueError:
        return MIN_DISCOVERY_LIMIT
    return max(1, min(parsed, MAX_DISCOVERY_LIMIT))


def _crawler_timeout_ms() -> int:
    raw_value = os.getenv("RA_1688_CRAWLER_TIMEOUT_MS")
    if not raw_value:
        return DEFAULT_CRAWLER_TIMEOUT_MS
    try:
        parsed = int(raw_value)
    except ValueError:
        return DEFAULT_CRAWLER_TIMEOUT_MS
    return max(3_000, min(parsed, 15_000))


def _clean_query_text(value: Any) -> str:
    if value is None:
        return ""
    text_value = str(value)
    text_value = re.sub(r"\bB0[A-Z0-9]{8}\b", " ", text_value, flags=re.IGNORECASE)
    text_value = re.sub(r"[^\w\u4e00-\u9fff\s-]", " ", text_value)
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return text_value


def _dedupe_preserve_order(
    values: list[str] | list[SupplierSearchQuery],
) -> list[str] | list[SupplierSearchQuery]:
    seen: set[str] = set()
    deduped = []
    for value in values:
        key = value.query if isinstance(value, SupplierSearchQuery) else value
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decimal_number(value: Any) -> float | None:
    decimal = decimal_value(value)
    return float(decimal) if decimal is not None else None
