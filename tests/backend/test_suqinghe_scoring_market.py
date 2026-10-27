"""选品评分卡 + 竞品拆解(10-27)的纯逻辑:评分各维度边界、一票否决、把握;拆解的搜索结果筛选、模型输出解析、种子词、卖点排序;
通用抓页的 JSON-LD 解析、去标签、拦截识别、静态抓取兜底(本地 http 服务,不出网)。unit,不连库。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from backend.app.modules.agent_series.common import webpage
from backend.app.modules.agent_series.suqinghe import market, pricing, scoring
from backend.app.modules.agent_series.suqinghe.constants import weight_class_kg

pytestmark = pytest.mark.unit

A = pricing.assumptions()
KG = weight_class_kg()


def _card(**over):
    base = dict(
        title="户外露营折叠水桶",
        category_path="Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Water Containers",
        profile_en="Collapsible Water Bucket",
        price_cny=18.0,
        weight_class="light",
        flags=(),
        factory_pts=12,
        factory_why="能换颜色、配提手做套装",
        shopping={"query": "collapsible camping bucket", "n": 16, "p25": 14.0, "median": 19.99, "p75": 26.0},
        amazon={"valid": True, "review_wall_max": 280, "single_brand_share": 0.2, "new_entrant_ratio_est": 0.35},
        keepa=[{"asin": "A", "monthly_sales": 600}, {"asin": "B", "monthly_sales": 300}, {"asin": "C", "monthly_sales": None}],
        keepa_error=None,
        a=A,
        kg_by_class=KG,
    )
    base.update(over)
    return scoring.scorecard(**base)


def test_scorecard_dimensions_add_up_and_cite_their_sources() -> None:
    card = _card()
    assert card["vetoed"] == [] and card["missing"] == []
    assert [d["key"] for d in card["dims"]] == ["economics", "demand", "competition", "factory", "logistics"]
    assert sum(d["max"] for d in card["dims"]) == 100 and card["total"] == sum(d["pts"] for d in card["dims"])
    by = {d["key"]: d for d in card["dims"]}
    assert by["economics"]["pts"] == 30 and "0.3 公斤估运费" in by["economics"]["why"] and "p25 $14.00" in by["economics"]["why"]
    assert by["demand"]["pts"] == 20 and "月销合计约 900" in by["demand"]["why"] and "16 个卖家" in by["demand"]["why"]
    assert by["competition"]["pts"] == 16 and "280 条" in by["competition"]["why"]
    assert by["factory"]["pts"] == 12 and by["logistics"]["pts"] == 15
    assert all(d["source"] for d in card["dims"])
    assert scoring.confidence(card) == "high"
    assert scoring.lines(card)[-1].startswith("合计 93/100")


def test_economics_scales_with_floor_price_against_p25() -> None:
    cheap = _card(price_cny=5.0)["dims"][0]
    assert cheap["pts"] == 30
    dear = _card(price_cny=90.0)["dims"][0]  # 进价 ¥90 的东西保底价远高于 p25 $14
    assert dear["pts"] == 0 and "保底价是它的" in dear["why"]
    half = _card(shopping={"n": 0})["dims"][0]
    assert half["pts"] == 15 and half["missing"] and "没拿到" in half["why"]
    no_price = _card(price_cny=None)["dims"][0]
    assert no_price["pts"] == 0 and no_price["missing"]
    heavy = _card(weight_class="medium")["dims"][0]
    assert "中等 1 公斤" in heavy["why"]


def test_demand_and_competition_mark_missing_data_instead_of_faking_zero() -> None:
    blind = _card(keepa=[], keepa_error="Keepa 钥匙没绑", amazon={"error": "Rainforest key 未绑定"})
    by = {d["key"]: d for d in blind["dims"]}
    assert by["demand"]["missing"] and "Keepa 钥匙没绑" in by["demand"]["why"] and by["demand"]["pts"] == 6  # 只剩卖家数的 6 分
    assert by["competition"]["missing"] and by["competition"]["pts"] == 10 and "Rainforest key 未绑定" in by["competition"]["why"]
    assert sorted(blind["missing"]) == ["有人买", "竞争"] and scoring.confidence(blind) == "low"
    wall = _card(amazon={"valid": True, "review_wall_max": 5000, "single_brand_share": 0.7, "dominant_brand": "YETI", "new_entrant_ratio_est": 0.05})["dims"][2]
    assert wall["pts"] == 0 and "YETI" in wall["why"] and "减半" in wall["why"]
    invalid = _card(amazon={"valid": False})["dims"][2]
    assert invalid["pts"] == 10 and invalid["missing"]


def test_red_lines_veto_by_terms_flags_and_weight() -> None:
    assert _card(title="户外折叠刀具套装")["vetoed"] == ["刀具(命中「刀具」)"]
    assert _card(profile_en="Coleman Style Lantern")["vetoed"] == ["带别人的品牌「coleman」"]
    assert _card(flags=("liquid", "battery"))["vetoed"] == ["她判:液体"]
    assert _card(weight_class="heavy")["vetoed"] == ["她判:大件重件,运费吃掉毛利"]
    assert _card(title="驱蚊片 户外电热蚊香")["vetoed"][0].startswith("驱蚊片(EPA)")
    # 花洒的 spray、风扇的 blade、医药箱的 药 不是红线:交给她标 flag
    assert _card(title="便携淋浴花洒 spray shower head", profile_en="Portable Shower Spray Head")["vetoed"] == []
    assert _card(title="户外医药箱空包")["vetoed"] == []
    # 锂电只扣分
    battery = _card(flags=("battery", "fragile"))
    assert battery["vetoed"] == [] and battery["dims"][4]["pts"] == 7 and "带电/锂电池 -4" in battery["dims"][4]["why"]


def test_factory_fit_clamps_and_keeps_reason() -> None:
    assert scoring.factory_fit(pts=99, why="x").pts == 15
    assert scoring.factory_fit(pts="bad", why="").pts == 5 and scoring.factory_fit(pts="bad", why="").why == "她没说理由"
    assert scoring.factory_fit(pts=-3, why="y").pts == 0


# ---------------------------------------------------------------- 竞品拆解


def test_shop_pages_drop_platforms_and_keep_one_per_domain() -> None:
    raw = {
        "organic": [
            {"link": "https://www.amazon.com/dp/B0", "title": "amz"},
            {"link": "https://outdoorshop.com/products/bucket", "title": "A"},
            {"link": "https://outdoorshop.com/products/bucket-2", "title": "A2"},
            {"link": "https://www.reddit.com/r/camping/x", "title": "r"},
            {"link": "https://gearjunkie.com/best-buckets", "title": "review"},
            {"link": "https://store.another.co/p/1", "title": "B", "snippet": "s"},
            {"link": "ftp://nope", "title": "bad"},
            {"link": "https://www.walmart.com/ip/1", "title": "w"},
            {"link": "https://third.shop/item", "title": "C"},
        ]
    }
    pages = market.shop_pages(raw, limit=2)
    assert [p["domain"] for p in pages] == ["outdoorshop.com", "store.another.co"]
    assert market.is_platform("amazon.com") and market.is_platform("www.amazon.co.uk") and not market.is_platform("myshop.com")


def test_parse_summary_strips_brands_dedupes_and_caps() -> None:
    out = market.parse_summary(
        {
            "priorities": [{"what": "装水量", "why": "三家都写 10L"}, {"what": "", "why": "x"}, "junk"],
            "ours": {"has": ["10L"], "missing": ["折叠后的尺寸"]},
            "bullet_order_hint": ["Capacity 10L", "YETI style handle", "packs flat"],
            "keywords": {"category": ["Collapsible Camping Bucket", "collapsible camping bucket", "Coleman bucket", "带中文"], "attribute": ["10 liter"], "scene": [], "question": ["how to store a collapsible bucket?"], "bogus": ["x"]},
            "competitors": {"brands": ["YETI", "Y"], "domains": ["outdoorshop.com", "OUTDOORSHOP.COM"]},
            "gaps": ["折叠后尺寸要问工厂"],
            "note": "机会在轻量",
        },
        domains=["store.another.co"],
    )
    assert out["priorities"] == [{"what": "装水量", "why": "三家都写 10L"}]
    assert out["keywords"]["category"] == ["collapsible camping bucket"]  # 去重、去品牌、去中文
    assert out["keywords"]["question"] == ["how to store a collapsible bucket?"] and "bogus" not in out["keywords"]
    assert out["bullet_order_hint"] == ["capacity 10l", "packs flat"]  # 带品牌的主题扔掉
    assert out["competitors"] == {"brands": ["YETI"], "domains": ["outdoorshop.com", "store.another.co"]}
    assert out["gaps"] == ["折叠后尺寸要问工厂"] and out["note"] == "机会在轻量"
    assert market.seed_keywords(out) == ["collapsible camping bucket", "10 liter"]
    assert market.competitor_names(out) == ["YETI", "outdoorshop.com", "store.another.co"]
    assert market.parse_summary("garbage", domains=[])["priorities"] == []


def test_reorder_bullets_follows_buyer_priorities_and_stays_stable() -> None:
    review = [
        {"id": "bp1", "text": "Food-grade silicone, safe for drinking water"},
        {"id": "bp2", "text": "Holds 10 liters (2.6 gallons) of water"},
        {"id": "bp3", "text": "Packs flat to 1 inch thick"},
        {"id": "bp4", "text": "Comes in three colors"},
    ]
    ordered = market.reorder_bullets(review, ["capacity 10 liters", "packs flat", "safe material"])
    assert [b["id"] for b in ordered] == ["bp2", "bp3", "bp4", "bp1"] or [b["id"] for b in ordered] == ["bp2", "bp3", "bp1", "bp4"]
    assert market.reorder_bullets(review, []) == review


def test_card_text_tells_the_boss_it_is_informational() -> None:
    done = {
        "status": "done",
        "query": "collapsible camping bucket",
        "pages": [{"domain": "a.com", "ok": True, "price": 19.0, "bullets": 3, "faq": 1}, {"domain": "b.com", "ok": True, "price": 25.0, "bullets": 2, "faq": 0}, {"domain": "c.com", "ok": False, "error": "被拦"}],
        "priorities": [{"what": "装水量", "why": "都写"}],
        "ours": {"has": ["10L"], "missing": ["折叠尺寸"]},
        "keywords": {"category": ["collapsible camping bucket"], "attribute": [], "scene": [], "question": []},
        "competitors": {"brands": ["YETI"], "domains": ["a.com"]},
        "gaps": ["折叠尺寸"],
        "note": "n",
    }
    text = market.card_text(done, sku="CWB-001", product_name="Collapsible Bucket")
    assert text["title"] == "CWB-001 竞品拆解:2 家同类页"
    assert "不用批" in text["conclusion"] and "$19–$25" in text["conclusion"] and "1 个关键词" in text["conclusion"]
    assert "要问你或工厂的:折叠尺寸" in text["why"] and "竞品:YETI、a.com" in text["why"]
    assert text["evidence"]["keywords"]["category"] == ["collapsible camping bucket"] and text["confidence"] == "medium"


def test_extract_page_prefers_jsonld_and_tolerates_a_broken_model_answer() -> None:
    html = """<html><head><title>Bucket | Shop</title>
    <script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"Shop"},
    {"@type":"Product","name":"Collapsible Bucket 10L","description":"Folds flat.","brand":{"@type":"Brand","name":"ShopBrand"},
    "image":["a.jpg","b.jpg","c.jpg"],"offers":{"@type":"Offer","price":"19.99","priceCurrency":"USD"},"aggregateRating":{"ratingValue":"4.6","reviewCount":"120"}}]}</script>
    </head><body><h1>Bucket</h1><p>Holds 10 liters.</p></body></html>"""
    page = webpage.Page(url="https://shop.example/p", final_url="https://shop.example/p", title="Bucket | Shop", html=html, text="Bucket\nHolds 10 liters.", ok=True, via="render")
    summary = market.extract_page(page, lambda db, ask, extra: {"content": "not json"}, db=None)
    assert summary["title"] == "Collapsible Bucket 10L" and summary["price"] == 19.99 and summary["brand"] == "ShopBrand" and summary["image_count"] == 3
    assert summary["review_count"] == 120 and summary["bullets"] == [] and summary["ok"] is True
    summary = market.extract_page(page, lambda db, ask, extra: {"bullets": ["Folds flat", "Folds flat", 3], "faq": [{"q": "Is it leakproof?", "a": "Yes."}], "image_count": 9}, db=None)
    assert summary["bullets"] == ["Folds flat"] and summary["faq"] == [{"q": "Is it leakproof?", "a": "Yes."}] and summary["image_count"] == 3  # JSON-LD 的图数优先


# ---------------------------------------------------------------- 通用抓页


def test_html_to_text_jsonld_and_blocked_detection() -> None:
    html = "<html><head><title>T</title><style>.x{}</style></head><body><script>var a=1</script><h1>Hello</h1><p>World &amp; co</p><ul><li>one</li><li>two</li></ul></body></html>"
    assert webpage.html_to_text(html) == "Hello\nWorld & co\none\ntwo"
    assert webpage.jsonld_products("<html></html>") == []
    assert webpage.jsonld_products('<script type="application/ld+json">{bad json</script>') == []
    assert webpage.looks_blocked(final_url="https://x.com/captcha?x", title="", text="")
    assert webpage.looks_blocked(final_url="https://x.com/", title="Just a moment...", text="")
    assert webpage.looks_blocked(final_url="https://x.com/", title="Shop", text="Please verify you are human to continue")
    assert not webpage.looks_blocked(final_url="https://x.com/p", title="Bucket", text="Holds 10 liters")
    assert webpage.image_count('<img src="a.jpg"><img src="logo.png"><img src="b.jpg" alt="x">') == 2
    assert webpage.registrable_domain("https://www.Shop.Example/p?x=1") == "shop.example"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/blocked"):
            body = b"<html><head><title>Access Denied</title></head><body>no</body></html>"
        else:
            body = b"<html><head><title>Local Bucket</title></head><body><h1>Bucket</h1><p>Holds 10 liters.</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: D102
        return


@pytest.fixture
def local_site():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def test_static_fetch_and_render_fallback_against_a_local_page(local_site, monkeypatch: pytest.MonkeyPatch) -> None:
    page = webpage.fetch_static(f"{local_site}/p")
    assert page.ok and page.title == "Local Bucket" and "Holds 10 liters." in page.text and page.via == "static"
    blocked = webpage.fetch_static(f"{local_site}/blocked")
    assert blocked.blocked and not blocked.ok

    def no_browser(*args, **kwargs):
        raise RuntimeError("playwright not installed")

    monkeypatch.setattr(webpage, "render_raw", no_browser)
    fallback = webpage.read(f"{local_site}/p", timeout_s=5)
    assert fallback.ok and fallback.via == "static" and "playwright not installed" in fallback.meta["render_error"]
    assert not webpage.read(f"{local_site}/p", timeout_s=5, allow_static=False).ok


def test_research_skips_when_too_few_pages_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(market, "search_pages", lambda db, **kw: {"query": kw["query"], "pages": [{"url": "https://a.com/p", "domain": "a.com", "title": "A", "snippet": ""}], "serp_keywords": ["k"]})
    monkeypatch.setattr("r_system_v2.ra.quota_ledger.try_consume", lambda db, provider, amount=1: 1)

    class _Db:
        def commit(self):
            return None

    out = market.research(_Db(), org_id="org", query="bucket", brief="b", fetch=lambda url: webpage.Page(url=url, ok=False, error="timeout"), gap_seconds=0)
    assert out["status"] == "skipped" and "只读到 0 页" in out["reason"] and out["pages"][0]["error"] == "timeout"
    monkeypatch.setattr(market, "search_pages", lambda db, **kw: {"error": "Serper 钥匙没绑"})
    assert market.research(_Db(), org_id="org", query="bucket", brief="b", gap_seconds=0)["reason"] == "搜不了:Serper 钥匙没绑"
