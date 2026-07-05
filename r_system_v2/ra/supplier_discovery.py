"""Serper + 1688 supplier discovery for R-A profit analysis."""

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
from urllib.parse import urljoin, urlparse
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
from r_system_v2.ra.providers import RAnalysisProviderBinding


SERPER_SEARCH_URL = "https://google.serper.dev/search"
DEFAULT_DISCOVERY_LIMIT = 5
MIN_DISCOVERY_LIMIT = 3
MAX_DISCOVERY_LIMIT = 5
DEFAULT_CRAWLER_TIMEOUT_MS = 8_000


class RASupplierDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SerperResult:
    title: str
    link: str
    snippet: str | None
    position: int | None


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
    result_limit: int = DEFAULT_DISCOVERY_LIMIT,
    auto_calculate: bool = True,
    exchange_rate_usd_cny: Decimal | None = None,
    min_gross_margin: Decimal | None = None,
    serper_client: Serper1688Client | None = None,
    crawler: Playwright1688Crawler | None = None,
) -> dict[str, object]:
    normalized_asin = asin.strip().upper()
    limit = _bounded_limit(result_limit)
    product = _load_product(db, normalized_asin)
    candidate_id = _ensure_candidate(db, org_id=org_id, product=product)
    db.commit()
    client = serper_client or _serper_client(db, org_id=org_id)
    crawler = crawler or Playwright1688Crawler()
    queries = build_1688_queries(product)
    searches: list[dict[str, object]] = []
    offers: list[dict[str, object]] = []
    seen_links: set[str] = set()
    warnings: list[str] = []

    for query in queries:
        if len(offers) >= limit:
            break
        search_id = str(uuid4())
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
            query=query,
            status=status,
            result_count=len(results),
            payload={
                "results": [result.__dict__ for result in results],
                "searched_at": datetime.now(UTC).isoformat(),
            },
        )
        db.commit()
        searches.append(
            {
                "search_id": search_id,
                "query": query,
                "status": status,
                "result_count": len(results),
            }
        )
        if status == "failed":
            continue

        for result in results:
            if len(offers) >= limit:
                break
            normalized_link = _normalized_1688_link(result.link)
            if normalized_link is None or normalized_link in seen_links:
                continue
            seen_links.add(normalized_link)
            crawled = crawler.crawl(normalized_link)
            result_price = _result_price_cny(result)
            result_shipping = _result_shipping_cny(result)
            unit_price_cny = crawled.unit_price_cny or result_price
            domestic_shipping_cny = (
                crawled.domestic_shipping_cny
                if crawled.domestic_shipping_cny is not None
                else result_shipping
            )
            crawler_warning = (
                None
                if crawled.unit_price_cny is not None or result_price is not None
                else crawled.warning
            )
            offer_id = _insert_supplier_offer(
                db,
                org_id=org_id,
                search_id=search_id,
                candidate_id=candidate_id,
                asin=normalized_asin,
                supplier_name=crawled.title or result.title or "1688 供应商",
                supplier_url=crawled.final_url or normalized_link,
                unit_price_cny=unit_price_cny,
                domestic_shipping_cny=domestic_shipping_cny,
                moq=crawled.moq,
                source="serper_1688",
                match_score=_match_score(result, crawled),
                offer_status="priced" if unit_price_cny is not None else "price_pending",
                payload_extra={
                    "serper_title": result.title,
                    "serper_snippet": result.snippet,
                    "serper_position": result.position,
                    "crawler_status": crawled.crawler_status,
                    "crawler_warning": crawler_warning,
                    "price_source": (
                        "1688_page"
                        if crawled.unit_price_cny is not None
                        else "serper_snippet"
                        if result_price is not None
                        else None
                    ),
                    "raw_excerpt": crawled.raw_excerpt,
                    "one_piece_hint": _one_piece_hint(result, crawled),
                    "shipping_notice": (
                        "1688 页面显示包邮或抓取到运费"
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
                    "supplier_name": crawled.title or result.title or "1688 供应商",
                    "supplier_url": crawled.final_url or normalized_link,
                    "unit_price_cny": _decimal_number(unit_price_cny),
                    "domestic_shipping_cny": _decimal_number(domestic_shipping_cny),
                    "moq": crawled.moq,
                    "match_score": _match_score(result, crawled),
                    "one_piece_hint": _one_piece_hint(result, crawled),
                    "offer_status": (
                        "priced" if unit_price_cny is not None else "price_pending"
                    ),
                    "crawler_status": crawled.crawler_status,
                    "warning": crawler_warning,
                }
            )

    priced_count = sum(1 for offer in offers if offer["unit_price_cny"] is not None)
    profit_run: dict[str, object] | None = None
    if auto_calculate and priced_count > 0:
        profit_run = run_profit_for_existing_offers(
            db,
            org_id=org_id,
            asin=normalized_asin,
            limit=limit,
            exchange_rate_usd_cny=exchange_rate_usd_cny,
            min_gross_margin=min_gross_margin,
        )
    else:
        db.commit()

    return {
        "asin": normalized_asin,
        "candidate_id": candidate_id,
        "queries": queries,
        "searches": searches,
        "offers": offers,
        "profit_run": profit_run,
        "counts": {
            "searches": len(searches),
            "candidate_offers": len(offers),
            "priced_offers": priced_count,
        },
        "warnings": warnings,
    }


def build_1688_queries(product: dict[str, Any]) -> list[str]:
    title_zh = _clean_query_text(product.get("title_zh"))
    title = _clean_query_text(product.get("title"))
    category = _clean_query_text(product.get("category"))
    base = title_zh or title
    if not base:
        raise RAProfitError("该产品缺少标题，无法搜索 1688。")
    if len(base) > 120:
        base = base[:120]
    queries = [
        f"1688 {base} 一件代发 一件起批 同款",
        f"{base} 阿里巴巴 1688 一件代发 批发 厂家",
    ]
    if category:
        queries.append(f"1688 {category} {base[:80]} 一件起批 批发")
    return _dedupe_preserve_order(queries)


def _serper_client(db: Session, *, org_id: str) -> Serper1688Client:
    try:
        api_key = RAnalysisProviderBinding(
            org_id=org_id,
            secret_manager=SecretManager(db_session=db),
        ).serper_key()
    except SecretManagerError as exc:
        raise RASupplierDiscoveryError("R-A 没有绑定 Serper key。") from exc
    if not api_key.strip():
        raise RASupplierDiscoveryError("R-A 没有绑定 Serper key。")
    return Serper1688Client(api_key=api_key)


def _insert_supplier_search(
    db: Session,
    *,
    search_id: str,
    org_id: str,
    candidate_id: str,
    asin: str,
    query: str,
    status: str,
    result_count: int,
    payload: dict[str, Any],
) -> None:
    db.execute(
        text(
            f"""
            INSERT INTO ra_supplier_searches (
              id, org_id, candidate_id, asin, query, provider, status,
              result_count, payload
            )
            VALUES (
              :id, :org_id, :candidate_id, :asin, :query, 'serper',
              :status, :result_count, {_json_bind(db, "payload")}
            )
            """
        ),
        {
            "id": search_id,
            "org_id": org_id,
            "candidate_id": candidate_id,
            "asin": asin,
            "query": query,
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
    return urljoin(base_url, href)


def _extract_price_cny(text: str) -> Decimal | None:
    labeled_patterns = (
        r'"(?:price|offerPrice|skuPrice|discountPrice|salePrice)"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)',
        r'"priceRange"\s*:\s*"\s*([0-9]+(?:\.[0-9]{1,2})?)',
        r'(?:价格|批发价|拿货价|现货价)[^0-9￥¥]{0,20}(?:￥|¥)?\s*([0-9]+(?:\.[0-9]{1,2})?)',
    )
    generic_patterns = (
        r'(?<!运费\s)(?<!邮费\s)(?<!快递\s)(?<!物流\s)(?:￥|¥)\s*([0-9]+(?:\.[0-9]{1,2})?)',
    )
    values = _extract_decimal_matches(text, labeled_patterns)
    if values:
        return min(values)
    values = _extract_decimal_matches(text, generic_patterns)
    if values:
        return min(values)
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


def _is_1688_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == "1688.com" or host.endswith(".1688.com")


def _normalized_1688_link(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return None
    if not _is_1688_url(url):
        return None
    return parsed._replace(fragment="").geturl()


def _bounded_limit(value: int) -> int:
    return max(MIN_DISCOVERY_LIMIT, min(MAX_DISCOVERY_LIMIT, int(value)))


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


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
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
