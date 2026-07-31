"""渲染 /wholesale/ 主页和店型子页的 HTML。

**纯函数,不碰数据库、不发网络请求**——好测,也让"页面上到底会出现什么字"
这件事可以被测试钉死(红线:绝不出现任何价格)。

样式全部复用站点已有的 `.by-*` 品牌页组件(`tools/wp-house-style/
make_shop_css.py:62-124`),**一行新 CSS 都不写**:
  by-page / by-hero-lite / by-eyebrow2 / by-lead / by-block / by-cards /
  by-card / by-steps / by-list / by-btn / by-cta-block

⚠️ **子页不自己渲染 `<h1>`**,让主题出标题。因为隐藏主题标题那条 CSS 规则
用的是**硬编码页面 ID**(`make_shop_css.py:126`),新页不加进去就会出现两个
标题;而那份 CSS 是手工粘进插件的。不自出 h1 就完全绕开这个坑。
"""

from __future__ import annotations

import html
import re
from typing import Any

from .. import policies

CONTACT_SHORTCODE = '[barong_contact_form channel="wholesale"]'
# 主页 slug 固定;子页走 parent 关系,URL 自然是 /wholesale/<slug>/
WHOLESALE_SLUG = "wholesale"
WHOLESALE_TITLE = "Wholesale & B2B Partnerships"
# 卡片上放几张代表图。放太多就变成产品目录了,那是子页的活。
CARD_THUMBS = 3


def _e(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def store_type_slug(key: str) -> str:
    """`gift_shop` → `gift-shop`。URL 里不要下划线。"""
    return re.sub(r"[^a-z0-9]+", "-", str(key or "").lower()).strip("-")


def _thumb(product: dict) -> str:
    """产品缩略图 + 名称,整块链到零售产品页。

    **刻意链到零售页而不是另做 B2B 产品页**:买手需要看 MSRP 算利润,而那页
    已经有实拍图、规格、GEO 内容和批发浮窗。另做一套等于把目录翻倍维护。
    """
    url = str(product.get("url") or "")
    name = _e(product.get("name"))
    image = str(product.get("image") or "")
    img_html = (
        f'<img src="{_e(image)}" alt="{name}" loading="lazy">' if image else ""
    )
    inner = f"{img_html}<span>{name}</span>"
    return (
        f'<a class="by-card" href="{_e(url)}">{inner}</a>'
        if url
        else f'<div class="by-card">{inner}</div>'
    )


def _guides_block(guides: list[dict]) -> str:
    """类目段落下面的「相关指南」。

    对买手的作用是**展示专业度**:一个愿意把"这东西能用多久""有什么毛病"
    写清楚的供应商,比只会发报价单的可信。用现成的 `.by-list-plain`
    (em dash 前缀),零新 CSS。
    """
    items = "".join(
        f'<li><a href="{_e(g.get("url"))}">{_e(g.get("title"))}</a></li>'
        for g in guides
        if g.get("url") and g.get("title")
    )
    if not items:
        return ""
    return (
        '<p class="by-meta"><strong>Buying guides for this line</strong></p>'
        f'<ul class="by-list-plain">{items}</ul>'
    )


def render_intro_block() -> str:
    """「我们为什么能做这么多品类」。

    品类跨度大如果不解释就是**减分**——采购的第一反应是"这是贸易公司吧"。
    这段把它从疑点变成能力说明。工厂照片是这段的支点,没照片这段就只是又
    一份自我介绍。
    """
    inhouse = " · ".join(_e(x) for x in policies.WHOLESALE_INHOUSE)
    partnered = " · ".join(_e(x) for x in policies.WHOLESALE_PARTNERED)
    photos = "".join(
        '<div class="by-card"><span>Factory photo coming soon</span></div>'
        for _ in range(3)
    )
    return (
        '<section class="by-block" id="capability">'
        f"<h2>{_e(policies.WHOLESALE_INTRO_TITLE)}</h2>"
        f'<p class="by-lead">{_e(policies.WHOLESALE_INTRO_LEAD)}</p>'
        '<ul class="by-list">'
        f"<li><strong>We do in-house:</strong> {inhouse}</li>"
        f"<li><strong>We partner for:</strong> {partnered}</li>"
        "</ul>"
        f"<p>{_e(policies.WHOLESALE_INTRO_CLOSE)}</p>"
        f"<p><strong>{_e(policies.WHOLESALE_INTRO_PROOF)}</strong></p>"
        f'<div class="by-cards">{photos}</div>'
        "</section>"
    )


def render_store_type_cards(groups: list[dict]) -> str:
    """店型卡片。**页面列的是店型不是产品**——产品从 6 个涨到 300 个,卡片
    还是这几张,只有数字变大。这就是"买家类型不跟产品数涨"。

    卡片上**不写 MOQ 数字**(用户拍板:不同产品不一样,写区间显得乱),
    只指向图册——起订量逐款不同,按款列最准确。曾经写过"most lines start at
    one case",2026-07-30 删掉:没有任何机制保证那句话是真的。
    """
    if not groups:
        return ""
    cards = []
    for group in groups:
        label = _e(group.get("label"))
        count = int(group.get("count") or 0)
        url = _e(group.get("url") or "")
        thumbs = "".join(_thumb(p) for p in (group.get("thumbs") or []))
        cards.append(
            '<div class="by-card">'
            f"<h3>{label}</h3>"
            f"<p>{count} product{'s' if count != 1 else ''} ready to ship."
            f" {_e(policies.MOQ_LINE)}</p>"
            + (f'<div class="by-cards">{thumbs}</div>' if thumbs else "")
            + (f'<p><a class="by-btn" href="{url}">See the range</a></p>' if url else "")
            + "</div>"
        )
    return (
        '<section class="by-block" id="what-we-make">'
        "<h2>What we make</h2>"
        '<div class="by-cards">' + "".join(cards) + "</div>"
        "</section>"
    )


def render_wholesale_page(groups: list[dict]) -> str:
    """/wholesale/ 主页全文。

    ⚠️ **绝不出现任何价格**。小窗、图册、这个页面三处同一条红线:GMC 会把
    "页面价与 feed 价不符"判成 Misrepresentation,只剩一次申诉机会。
    """
    who = "".join(
        f'<div class="by-card"><h3>{_e(t)}</h3><p>{_e(d)}</p></div>'
        for t, d in policies.who_we_work_with()
    )
    steps = "".join(
        f"<li><strong>{_e(t)}</strong> {_e(d)}</li>"
        for t, d in policies.how_it_works()
    )
    terms = "".join(
        f"<li><strong>{_e(t)}</strong> - {_e(d)}</li>"
        for t, d in policies.wholesale_terms()
    )
    return (
        '<div class="by-page">'
        '<section class="by-hero-lite">'
        '<p class="by-eyebrow2">WHOLESALE &amp; B2B</p>'
        "<h1>Partner with the source.</h1>"
        '<p class="by-lead">We manufacture and assemble in-house, so wholesale'
        " partners work factory-direct: honest pricing, consistent quality,"
        " and one accountable team from quote to delivery.</p>"
        "</section>"
        + render_intro_block()
        + '<section class="by-block"><h2>Who we work with</h2>'
        f'<div class="by-cards">{who}</div></section>'
        + render_store_type_cards(groups)
        + '<section class="by-block"><h2>How it works</h2>'
        f'<ol class="by-steps">{steps}</ol></section>'
        + '<section class="by-block" id="terms"><h2>Terms at a glance</h2>'
        f'<ul class="by-list">{terms}</ul></section>'
        + '<section class="by-block"><h2>Start the conversation</h2>'
        "<p>Send us your requirements - inquiries from this form go directly"
        " to our B2B team, separate from retail support.</p>"
        f"{CONTACT_SHORTCODE}</section>"
        "</div>"
    )


def render_store_type_page(group: dict) -> str:
    """一个店型的子页:该店型全部产品,**按谷歌类目分组**。

    分组用 `category_path`,自动——32 个产品混在一起看着杂乱,分了组每一段
    小标题本身还是一个类目关键词(SEO 白拿)。

    **不渲染 `<h1>`**:主题会出标题(见模块注释)。
    """
    label = _e(group.get("label"))
    count = int(group.get("count") or 0)
    sections = []
    for category in group.get("categories") or []:
        name = _e(category.get("name"))
        products = category.get("products") or []
        tiles = "".join(_thumb(p) for p in products)
        # 方案 B(用户拍板):指南挂在**各自类目段落下面**,紧贴它讲的那批货。
        # 从结构上就不可能张冠李戴——一个段落里的指南只来自这个段落的产品。
        sections.append(
            f"<h3>{name} ({len(products)})</h3>"
            f'<div class="by-cards">{tiles}</div>'
            + _guides_block(category.get("guides") or [])
        )
    body = "".join(sections) or "<p>Range coming soon.</p>"
    return (
        '<div class="by-page">'
        '<section class="by-hero-lite">'
        '<p class="by-eyebrow2">WHOLESALE</p>'
        f'<p class="by-lead">{count} product{"s" if count != 1 else ""} '
        f"available to {label.lower()}. "
        f"{_e(policies.MOQ_LINE)}</p>"
        "</section>"
        f'<section class="by-block"><h2>The range</h2>{body}</section>'
        '<section class="by-block"><h2>Request the line sheet</h2>'
        f"<p>Tell us which lines you're interested in and we'll send the"
        f" current {label.lower()} line sheet with pricing tiers and MOQs.</p>"
        f"{CONTACT_SHORTCODE}</section>"
        '<p class="by-cta-block">'
        f'<a class="by-btn" href="/{WHOLESALE_SLUG}/">'
        "Back to the wholesale program</a></p>"
        "</div>"
    )
