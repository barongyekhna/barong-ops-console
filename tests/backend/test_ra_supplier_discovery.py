from __future__ import annotations

from decimal import Decimal

from r_system_v2.ra.supplier_discovery import (
    _extract_price_cny,
    _normalized_supplier_link,
    _normalized_1688_link,
    _parse_1688_html,
    _result_price_cny,
    _select_supplier_price,
    SerperResult,
    build_1688_queries,
    build_supplier_queries,
)
from r_system_v2.ra.supplier_api import Mock1688OfficialApiProvider


def test_ra_supplier_queries_prefer_chinese_product_title() -> None:
    queries = build_1688_queries(
        {
            "asin": "B0SUPPLY01",
            "brand": "FrothPro",
            "title": "Milk Frother Handheld Foam Maker",
            "title_zh": "手持电动打奶器 奶泡器",
            "category": "厨房小工具",
        }
    )

    assert queries[0].startswith("打奶器")
    assert "一件代发" in queries[0]
    assert any("一件起批" in query for query in queries)
    assert all("B0SUPPLY01" not in query for query in queries)
    assert all("FrothPro" not in query for query in queries)


def test_ra_supplier_queries_include_multi_platform_choice_pages() -> None:
    queries = build_supplier_queries(
        {
            "asin": "B0SUPPLY01",
            "title": "Cat Tree Tower",
            "title_zh": "猫爬架",
            "category": "宠物用品",
        }
    )

    platforms = {query.platform for query in queries}
    assert {"1688", "pdd", "taobao", "jd"}.issubset(platforms)
    assert all(query.search_url.startswith("https://") for query in queries)
    assert any("猫爬架" in query.query for query in queries)


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


def test_ra_1688_price_parser_ignores_generic_one_yuan_noise() -> None:
    price = _extract_price_cny(
        """
        <script>
          {"price":"1","skuPrice":"49.90","offerPrice":"69.00"}
        </script>
        """
    )

    assert price == Decimal("49.90")


def test_ra_1688_price_parser_prefers_real_price_range() -> None:
    price = _extract_price_cny(
        """
        <script>{"price":"1","priceRange":"49.90-69.00"}</script>
        """
    )

    assert price == Decimal("49.90")


def test_ra_supplier_price_selector_rejects_implausible_low_cost() -> None:
    price, source, warning = _select_supplier_price(
        Decimal("1.00"),
        None,
        product={"price": Decimal("26.97")},
        exchange_rate_usd_cny=Decimal("7.2"),
        platform="1688",
    )

    assert price is None
    assert source is None
    assert warning is not None
    assert "明显低于亚马逊售价" in warning or "过低" in warning


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


def test_ra_multi_platform_link_normalization_keeps_detail_pages() -> None:
    assert (
        _normalized_supplier_link(
            "https://mobile.yangkeduo.com/goods.html?goods_id=123456789&refer=search",
            platform="pdd",
        )
        == "https://mobile.yangkeduo.com/goods.html?goods_id=123456789"
    )
    assert (
        _normalized_supplier_link(
            "https://item.taobao.com/item.htm?id=987654321&spm=a21n57",
            platform="taobao",
        )
        == "https://item.taobao.com/item.htm?id=987654321"
    )
    assert (
        _normalized_supplier_link("https://item.jd.com/100012345678.html?cu=true", platform="jd")
        == "https://item.jd.com/100012345678.html"
    )
    assert _normalized_supplier_link("https://search.jd.com/Search?keyword=猫爬架", platform="jd") is None


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


def test_ra_mock_1688_official_api_returns_priced_detail_offers() -> None:
    provider = Mock1688OfficialApiProvider()

    offers = provider.search_offers(
        product={
            "asin": "B0MOCK1688",
            "title": "Camping Folding Chair",
            "title_zh": "户外折叠椅",
            "price": Decimal("39.99"),
        },
        keyword_profile={"product_type_zh": "户外折叠椅"},
        limit=5,
    )

    assert len(offers) == 5
    assert all(offer.supplier_url.startswith("https://detail.1688.com/offer/") for offer in offers)
    assert all(offer.unit_price_cny > 0 for offer in offers)
    assert all(offer.moq >= 1 for offer in offers)
    assert all(offer.one_piece_hint is True for offer in offers)
    assert all((offer.payload or {}).get("official_api_mock") is True for offer in offers)
