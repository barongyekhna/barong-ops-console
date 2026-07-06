from __future__ import annotations

from decimal import Decimal

from r_system_v2.ra.supplier_discovery import (
    _normalized_1688_link,
    _parse_1688_html,
    _result_price_cny,
    SerperResult,
    build_1688_queries,
)


def test_ra_supplier_queries_prefer_chinese_product_title() -> None:
    queries = build_1688_queries(
        {
            "asin": "B0SUPPLY01",
            "title": "Milk Frother Handheld Foam Maker",
            "title_zh": "手持电动打奶器 奶泡器",
            "category": "厨房小工具",
        }
    )

    assert queries[0].startswith("site:detail.1688.com/offer 1688 手持电动打奶器 奶泡器")
    assert "一件代发" in queries[0]
    assert "一件起批" in queries[0]
    assert any("厨房小工具" in query for query in queries)
    assert all("B0SUPPLY01" not in query for query in queries)


def test_ra_1688_html_parser_extracts_cost_shipping_and_moq() -> None:
    offer = _parse_1688_html(
        """
        <html>
          <head><title>手持电动打奶器源头厂家 - 阿里巴巴</title></head>
          <body>
            <script>{"skuPrice":"18.80","offerPrice":"19.90"}</script>
            <span>起批量 3 件</span>
            <span>运费 ￥6.50</span>
          </body>
        </html>
        """,
        title=None,
        crawler_status="playwright",
    )

    assert offer.title == "手持电动打奶器源头厂家"
    assert offer.unit_price_cny == Decimal("18.80")
    assert offer.domestic_shipping_cny == Decimal("6.50")
    assert offer.moq == 3
    assert offer.warning is None


def test_ra_1688_link_normalization_keeps_only_1688_hosts() -> None:
    assert (
        _normalized_1688_link("https://detail.1688.com/offer/123456789.html?x=1#top")
        == "https://detail.1688.com/offer/123456789.html"
    )
    assert (
        _normalized_1688_link("https://m.1688.com/offer/987654321.html?spm=test")
        == "https://detail.1688.com/offer/987654321.html"
    )
    assert _normalized_1688_link("https://example.com/offer/123.html") is None


def test_ra_serper_result_can_supply_explicit_1688_price() -> None:
    price = _result_price_cny(
        SerperResult(
            title="手持电动打奶器 一件代发 ￥18.80",
            link="https://detail.1688.com/offer/123.html",
            snippet="现货批发，1件起批，运费 ￥6.50",
            position=1,
        )
    )

    assert price == Decimal("18.80")
