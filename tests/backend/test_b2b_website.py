"""/wholesale/ 主页与店型子页:红线、同源、防重复建页。

背景(2026-07-29):产品页浮窗只接住"已经点进某个产品"的人。店家找供应商的
真实路径是搜 `wholesale <类目> supplier` 落到站点找 Wholesale 入口——主阵地
才是大头。
"""

from __future__ import annotations

import html as html_lib
import re

import pytest

from backend.app.modules.b2b import policies
from backend.app.modules.b2b.website import pages

pytestmark = pytest.mark.unit


def _group() -> dict:
    product = {
        "sku": "ET-001",
        "name": "Baozi Squishy",
        "url": "https://barongyekhna.com/?p=4025",
        "image": "https://barongyekhna.com/x.webp",
    }
    return {
        "key": "gift_shop",
        "label": "Gift & novelty stores",
        "slug": "gift-shop",
        "url": "/wholesale/gift-shop/",
        "count": 32,
        "thumbs": [product],
        "categories": [{"name": "Stress & fidget toys", "products": [product]}],
    }


def _text(markup: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", " ", markup))


# --------------------------------------------------------------------------
# 红线:绝不出现价格
# --------------------------------------------------------------------------


def test_no_page_ever_renders_a_product_price() -> None:
    """**最重要的一条。** GMC 把"页面价与 feed 价不符"判成 Misrepresentation,
    这个账号被封过两次只剩一次申诉。小窗、图册、这三处同一条红线。

    唯一允许出现的金额是免运费门槛(USD 500),那是政策不是商品价。
    """
    for markup in (
        pages.render_wholesale_page([_group()]),
        pages.render_store_type_page(_group()),
    ):
        money = re.findall(r"(?:USD|\$)\s?\d[\d,.]*", _text(markup))
        assert money in ([], ["USD 500"]), money
        for banned in ("18.50", "35.99", "wholesale price", "MSRP"):
            assert banned not in markup, banned


def test_pages_never_say_oem_or_odm() -> None:
    """每封中国工厂群发的垃圾邮件都写 OEM/ODM,美国零售商看到就归类成
    阿里巴巴供应商。他们自己叫 private label。"""
    markup = pages.render_wholesale_page([_group()])
    assert "OEM" not in markup
    assert "ODM" not in markup
    assert "Private label" in markup


def test_free_shipping_line_keeps_the_sea_freight_lock() -> None:
    """漏了"仅限海运"这几个字,客户走 UPS 红单能把整单利润吃光。"""
    markup = _text(pages.render_wholesale_page([]))
    assert "sea freight only" in markup.lower()
    assert "paid by the buyer" in markup.lower()


def test_payment_terms_state_the_card_refusal() -> None:
    """页面和浮窗在这条上**刻意相反**:

    - 浮窗是钩子,负面表述劝退人,所以不写支付方式
    - 这个页面是给已经在评估的人看的,写清楚反而专业,而且是最明确的拒卡告示
    """
    markup = _text(pages.render_wholesale_page([]))
    assert "wire transfer (T/T) only" in markup
    assert "do not accept credit card" in markup

    widget = " ".join(e["text"] for e in policies.widget_policies()).lower()
    assert "credit card" not in widget
    assert "paypal" not in widget


# --------------------------------------------------------------------------
# 同源:页面 / 图册 / 浮窗共用 policies.py
# --------------------------------------------------------------------------


def test_page_terms_come_from_the_policy_source() -> None:
    markup = html_lib.unescape(pages.render_wholesale_page([]))
    for title, body in policies.wholesale_terms():
        assert title in markup, title
        assert body[:40] in markup, title


def test_free_shipping_threshold_is_identical_across_surfaces() -> None:
    """门槛从 $500 改成 $800 时,三处必须同时变——各存一份就是 GMC 的雷。"""
    threshold = f"{policies.DEFAULT_CURRENCY} {policies.FREE_SHIPPING_THRESHOLD:.0f}"
    assert threshold in " ".join(policies.line_sheet_notes())
    assert threshold in html_lib.unescape(pages.render_wholesale_page([]))
    assert threshold in " ".join(e["text"] for e in policies.widget_policies())


# --------------------------------------------------------------------------
# 结构
# --------------------------------------------------------------------------


def test_store_type_page_renders_no_h1() -> None:
    """隐藏主题标题那条 CSS 用的是**硬编码页面 ID**,新页不加进去会出现两个
    标题;而那份 CSS 是手工粘进插件的。不自出 h1 就完全绕开这个坑。"""
    assert "<h1" not in pages.render_store_type_page(_group())
    # 主页是既有页面,那条 CSS 已经包含它的 id
    assert "<h1" in pages.render_wholesale_page([])


def test_pages_reuse_the_existing_house_style_classes() -> None:
    """站点已有 .by-* 品牌页组件,一行新 CSS 都不该写。"""
    markup = pages.render_wholesale_page([_group()])
    for cls in ("by-page", "by-hero-lite", "by-block", "by-cards", "by-card",
                "by-steps", "by-list"):
        assert cls in markup, cls
    assert "<style" not in markup


def test_store_type_cards_hide_moq_numbers_but_encourage_small_orders() -> None:
    """用户拍板:不写 MOQ 数字(不同产品不一样,写区间显得乱),
    但要有一句降低心理门槛的话。"""
    markup = _text(pages.render_store_type_cards([_group()]))
    assert "MOQ" not in markup
    assert "one case" in markup


def test_product_tiles_link_to_the_retail_product_page() -> None:
    """刻意链到零售页:买手需要看 MSRP 算利润,而那页已经有实拍图、规格、
    GEO 内容和批发浮窗。另做一套 B2B 产品页等于把目录翻倍维护。"""
    markup = pages.render_store_type_page(_group())
    assert "https://barongyekhna.com/?p=4025" in markup


def test_empty_catalogue_renders_a_page_without_the_showcase() -> None:
    """一个产品都没填批发价时,页面照样能出——只是没有货架那一段。"""
    markup = pages.render_wholesale_page([])
    assert "by-page" in markup
    assert "What we make" not in markup
    assert "barong_contact_form" in markup


def test_store_type_slug_is_url_safe() -> None:
    assert pages.store_type_slug("gift_shop") == "gift-shop"
    assert pages.store_type_slug("Pet Boutique!") == "pet-boutique"


# --------------------------------------------------------------------------
# 防重复建页(照抄 guides_index 时必须修掉的缺陷)
# --------------------------------------------------------------------------


def test_publisher_never_creates_a_duplicate_on_a_transient_failure() -> None:
    """**回归**:`guides_index.py:363-387` 在**任何** unreachable 上都 fallback
    到"新建",WP 一超时就多一个重复页。这边是 1 主页 + N 子页,炸得更狠。

    只有确认 404(页面真没了)才允许走重建路径。
    """
    from pathlib import Path

    import backend.app.modules.b2b.website.publisher as pub

    source = Path(pub.__file__).read_text(encoding="utf-8")
    write = source[source.index("def _write_page(") : source.index("def publish(")]
    # 更新失败且不是 404 → 抛错，绝不往下走到创建
    assert 'if result.get("status") != 404:' in write
    assert "raise PublishError" in write
    # 重建前先按 slug 认领回来
    assert "_find_by_slug(credentials, slug)" in write


def test_publisher_commits_before_going_out_to_wordpress() -> None:
    """出网前必须结束事务:长事务会被 idle-in-transaction 掐断
    （这一轮已经栽过两次）。"""
    from pathlib import Path

    import backend.app.modules.b2b.website.publisher as pub

    source = Path(pub.__file__).read_text(encoding="utf-8")
    body = source[source.index("def publish(") : source.index("def publish_safely(")]
    assert body.index("db.commit()") < body.index("_resolve_credentials")


def test_buyer_facing_copy_uses_american_spelling() -> None:
    """**站是给美国买家看的,一律美式拼写。**

    2026-07-29 用户抓到浮窗上写了 `programme`(英联邦拼法)。和「美国市场
    一律用英制单位」是同一类错误:写给谁看,就用谁的写法。

    只查买家看得到的字串,代码注释和标识符不管。
    """
    from backend.app.modules.b2b.store_types import catalog

    surfaces = [
        pages.render_wholesale_page([_group()]),
        pages.render_store_type_page(_group()),
        " ".join(e["text"] for e in policies.widget_policies()),
        " ".join(policies.line_sheet_notes()),
        " ".join(t + d for t, d in policies.wholesale_terms()),
        " ".join(t + d for t, d in policies.who_we_work_with()),
        " ".join(s["public_label"] for s in catalog.STORE_TYPE_CATALOG),
    ]
    british = ("programme", "centres", "catalogue", "organisation",
               "customise", "colour", "licence", "favour", "optimise")
    for text in surfaces:
        low = text.lower()
        for word in british:
            assert word not in low, f"英式拼法 {word!r}: …{low[max(0,low.find(word)-30):low.find(word)+20]}…"


def test_store_type_public_labels_are_english() -> None:
    """DB 里的 label 是中文(给控制台看),网站必须用 public_label。
    2026-07-29 首次生成时页面上印出了"户外装备店"。"""
    import re as _re

    from backend.app.modules.b2b.store_types import catalog

    for spec in catalog.STORE_TYPE_CATALOG:
        label = spec["public_label"]
        assert label, spec["key"]
        assert not _re.search(r"[一-鿿]", label), f"{spec['key']}: {label}"


# --------------------------------------------------------------------------
# 指南内链:交叉污染是这一块唯一真正危险的 bug
# --------------------------------------------------------------------------


def test_guides_render_inside_their_own_category_section() -> None:
    """方案 B:指南挂在**各自类目段落下面**。

    用户的顾虑是"花洒连接到了捏捏的指南里面去"。方案 B 从结构上就排除了——
    一个段落里的指南只来自这个段落自己的产品。这条测试钉住那个结构。
    """
    shower = {
        "name": "Portable Showers",
        "products": [{"name": "Camping Shower", "url": "/p/4148", "image": ""}],
        "guides": [{"title": "How long does a 5 gallon shower last?",
                    "url": "/portable-camping-shower-faq/"}],
    }
    squishy = {
        "name": "Executive Toys",
        "products": [{"name": "Baozi Squishy", "url": "/p/4025", "image": ""}],
        "guides": [{"title": "Do squishies dry out?", "url": "/squishy-faq/"}],
    }
    markup = pages.render_store_type_page(
        {"label": "Gift stores", "count": 2, "categories": [shower, squishy]}
    )
    # 每篇指南必须出现在它自己那个类目的标题之后、下一个类目标题之前
    i_shower = markup.index("Portable Showers")
    i_squishy = markup.index("Executive Toys")
    i_shower_guide = markup.index("/portable-camping-shower-faq/")
    i_squishy_guide = markup.index("/squishy-faq/")
    assert i_shower < i_shower_guide < i_squishy, "花洒指南跑出了自己的段落"
    assert i_squishy < i_squishy_guide, "捏捏指南跑到了花洒段落里"


def test_a_category_with_no_guides_renders_nothing_extra() -> None:
    """没指南就什么都不加——绝不留一个空的「Buying guides」标题。"""
    markup = pages.render_store_type_page(
        {
            "label": "Gift stores",
            "count": 1,
            "categories": [
                {"name": "Executive Toys", "guides": [],
                 "products": [{"name": "X", "url": "/p/1", "image": ""}]}
            ],
        }
    )
    assert "Buying guides" not in markup


def test_guides_block_skips_rows_missing_a_url_or_title() -> None:
    """半截数据不许渲染成一个点不动的链接。"""
    markup = pages._guides_block(
        [
            {"title": "Good one", "url": "/good/"},
            {"title": "", "url": "/no-title/"},
            {"title": "No url", "url": ""},
        ]
    )
    assert "/good/" in markup
    assert "/no-title/" not in markup
    assert "No url" not in markup


def test_draft_guides_are_never_linked() -> None:
    """**published_url 非空 ≠ 线上可见。** n8n 首次建文落 draft 等人工发布,
    草稿期写下的 URL 还是 `?p=<id>` 形式。链到草稿 = 访客 404,而且不报错。"""
    from backend.app.modules.b2b.website import guides as g

    class FakeCreds:
        base_url = "http://x"

    def fake_request(url, **kwargs):
        return {
            "reachable": True,
            "data": [
                {"id": 4220, "status": "publish",
                 "link": "https://barongyekhna.com/live-guide/"},
                {"id": 4999, "status": "draft",
                 "link": "https://barongyekhna.com/?p=4999"},
            ],
        }

    g_wp = __import__(
        "backend.app.services.wp_bridge", fromlist=["wp_bridge"]
    )
    orig_req, orig_url = g_wp._request_json, g_wp._api_url
    g_wp._request_json = fake_request
    g_wp._api_url = lambda c, p: f"http://x/{p}"
    try:
        out = g.filter_live(
            FakeCreds(),
            [
                {"title": "Live", "url": "https://barongyekhna.com/live-guide/"},
                {"title": "Draft", "url": "https://barongyekhna.com/?p=4999"},
            ],
            post_ids=[4220, 4999],
        )
    finally:
        g_wp._request_json, g_wp._api_url = orig_req, orig_url

    assert [x["title"] for x in out] == ["Live"], out


def test_stale_query_string_urls_get_the_real_permalink() -> None:
    """草稿期存下的 `?p=4220`,发布后要换成真固定链接。"""
    from backend.app.modules.b2b.website import guides as g

    class FakeCreds:
        base_url = "http://x"

    g_wp = __import__(
        "backend.app.services.wp_bridge", fromlist=["wp_bridge"]
    )
    orig_req, orig_url = g_wp._request_json, g_wp._api_url
    g_wp._request_json = lambda url, **kw: {
        "reachable": True,
        "data": [{"id": 4220, "status": "publish",
                  "link": "https://barongyekhna.com/real-slug/"}],
    }
    g_wp._api_url = lambda c, p: f"http://x/{p}"
    try:
        out = g.filter_live(
            FakeCreds(),
            [{"title": "G", "url": "https://barongyekhna.com/?p=4220"}],
            post_ids=[4220],
        )
    finally:
        g_wp._request_json, g_wp._api_url = orig_req, orig_url
    assert out == [{"title": "G", "url": "https://barongyekhna.com/real-slug/"}]


def test_unverifiable_guides_are_dropped_not_guessed() -> None:
    """WP 核不了状态时宁可一篇不链,也不赌它已发布。"""
    from backend.app.modules.b2b.website import guides as g

    class FakeCreds:
        base_url = "http://x"

    g_wp = __import__(
        "backend.app.services.wp_bridge", fromlist=["wp_bridge"]
    )
    orig_req, orig_url = g_wp._request_json, g_wp._api_url
    g_wp._request_json = lambda url, **kw: {
        "reachable": False, "error": "wordpress_unreachable"
    }
    g_wp._api_url = lambda c, p: f"http://x/{p}"
    try:
        out = g.filter_live(
            FakeCreds(), [{"title": "G", "url": "/g/"}], post_ids=[1]
        )
    finally:
        g_wp._request_json, g_wp._api_url = orig_req, orig_url
    assert out == []
    # 没给 post id 同样不赌
    assert g.filter_live(FakeCreds(), [{"title": "G", "url": "/g/"}]) == []


def test_guides_per_category_are_capped() -> None:
    from backend.app.modules.b2b.website import guides as g

    assert g.MAX_GUIDES_PER_CATEGORY == 3


def test_status_reports_stored_guide_counts_without_going_out_to_wordpress() -> None:
    """面板上的指南篇数必须是**上次发布真的挂上去的数**,而且读它不许出网。

    为什么不在 `status()` 里重算:重算就得向 WP 核一遍每篇是不是已发布(出网),
    而面板是打开页面就调的。更要紧的是语义——面板该显示"页面上现在是什么",
    那本来就是上次发布的结果,不是此刻的推测。
    """
    from pathlib import Path

    import backend.app.modules.b2b.website.publisher as pub

    source = Path(pub.__file__).read_text(encoding="utf-8")
    status_body = source[source.index("def status(") :]
    # 从 KV 读，不重新连接指南
    assert "GUIDE_COUNT_PREFIX" in status_body
    assert "guide_categories_mapped" in status_body
    for forbidden in (
        "guides_for_products",
        "filter_live",
        "_resolve_credentials",
        "_request_json",
    ):
        assert forbidden not in status_body, f"status() 不该出网: {forbidden}"


def test_publish_persists_guide_counts_per_store_type() -> None:
    """发布时把篇数落库,否则面板没东西可显示。"""
    from pathlib import Path

    import backend.app.modules.b2b.website.publisher as pub

    source = Path(pub.__file__).read_text(encoding="utf-8")
    body = source[source.index("def publish(") : source.index("def _guide_count(")]
    assert "GUIDE_COUNT_PREFIX" in body
    assert "GUIDE_CATEGORIES_KEY" in body


def test_guide_count_sums_every_category_section() -> None:
    """一个店型页的篇数 = 它各类目段落之和(不是只数第一个段落)。"""
    from backend.app.modules.b2b.website import publisher

    group = {
        "categories": [
            {"guides": [{"title": "a", "url": "/a/"}, {"title": "b", "url": "/b/"}]},
            {"guides": [{"title": "c", "url": "/c/"}]},
            {"guides": []},
            {},
        ]
    }
    assert publisher._guide_count(group) == 3
    assert publisher._guide_count({}) == 0


def test_republish_skips_inside_the_minimum_interval() -> None:
    """定时被误配成每分钟一次时,护栏必须挡住——这条路会往 WP 写 N 个页面。"""
    from datetime import UTC, datetime, timedelta

    from backend.app.modules.b2b.website import publisher

    calls: list[int] = []

    class _FakeDb:
        pass

    recent = (datetime.now(UTC) - timedelta(minutes=3)).isoformat()
    original_get = publisher._get
    original_publish = publisher.publish_safely
    publisher._get = lambda db, key: recent  # type: ignore[assignment]
    publisher.publish_safely = lambda db: calls.append(1)  # type: ignore[assignment]
    try:
        result = publisher.republish_if_due(_FakeDb())  # type: ignore[arg-type]
    finally:
        publisher._get = original_get  # type: ignore[assignment]
        publisher.publish_safely = original_publish  # type: ignore[assignment]

    assert result["skipped"] is True
    assert result["ok"] is True
    assert not calls, "间隔内绝不能真的往 WP 写"


def test_republish_runs_once_the_interval_has_passed() -> None:
    from datetime import UTC, datetime, timedelta

    from backend.app.modules.b2b.website import publisher

    old = (datetime.now(UTC) - timedelta(hours=26)).isoformat()
    original_get = publisher._get
    original_publish = publisher.publish_safely
    publisher._get = lambda db, key: old  # type: ignore[assignment]
    publisher.publish_safely = lambda db: {  # type: ignore[assignment]
        "groups": 2,
        "guides_linked": 6,
        "guide_categories_mapped": 1,
    }
    try:
        result = publisher.republish_if_due(object())  # type: ignore[arg-type]
    finally:
        publisher._get = original_get  # type: ignore[assignment]
        publisher.publish_safely = original_publish  # type: ignore[assignment]

    assert result == {
        "ok": True,
        "skipped": False,
        "groups": 2,
        "guides_linked": 6,
        "guide_categories_mapped": 1,
    }


def test_republish_never_raises_at_the_caller() -> None:
    """发布失败要返回 ok=false,不能抛——抛了 n8n 会重试风暴,而重试解决不了
    WP 打不通这类问题。"""
    from backend.app.modules.b2b.website import publisher

    original_get = publisher._get
    original_publish = publisher.publish_safely
    publisher._get = lambda db, key: None  # type: ignore[assignment]
    publisher.publish_safely = lambda db: None  # type: ignore[assignment]
    try:
        result = publisher.republish_if_due(object())  # type: ignore[arg-type]
    finally:
        publisher._get = original_get  # type: ignore[assignment]
        publisher.publish_safely = original_publish  # type: ignore[assignment]

    assert result == {"ok": False, "skipped": False}


def test_republish_endpoint_is_fail_closed_without_a_token() -> None:
    """密钥没配 → 一律 403。绝不能因为忘了配环境变量就变成裸端点。"""
    from pathlib import Path

    import backend.app.modules.b2b.machine_router as machine

    source = Path(machine.__file__).read_text(encoding="utf-8")
    body = source[source.index("def website_republish(") :]
    assert "secrets.compare_digest" in body
    assert "not expected or not supplied" in body, "密钥为空必须直接拒"
    assert "status_code=403" in body
