"""把 K 的 marketing_copy_json 按 product-page-layout skill 骨架拼成
WooCommerce 的 description_html，并生成 Schema.org 结构化数据（Product + FAQPage）。

内容 AI（gpt-5.6-luna）早在文案阶段就生成好了（product_page_copy / page_faq / json_ld），
这里只做**确定性排版 + schema 组装**，不再调 AI。

排版铁律（见 SKILL.md）：正文绝不含价格/库存/配送（走结构化字段）。
Schema 铁律：FAQPage 的问答 = 页面可见且 K 质量门通过的 FAQ（同源，防惩罚）；
Product 的 price/availability 用上架时的真实值填（与 feed 同源）。

样式：HTML 只带稳定 class（kp-*），CSS 加在主题里一次、全站生效 —— 不往每个
产品里塞内联样式。CSS 见 P_PRODUCT_PAGE_CSS。
"""

from __future__ import annotations

import json as _json
from html import escape
from typing import Any

from ...k_series.product_knowledge.faq_research import faq_schema_is_eligible

_AVAIL_SCHEMA = {
    "in_stock": "https://schema.org/InStock",
    "out_of_stock": "https://schema.org/OutOfStock",
    "preorder": "https://schema.org/PreOrder",
}


def _s(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _ppc(marketing_copy_json: dict[str, Any] | None) -> dict[str, Any]:
    mcj = marketing_copy_json or {}
    ppc = mcj.get("product_page_copy") if isinstance(mcj, dict) else None
    return ppc if isinstance(ppc, dict) else {}


def _faq_items(marketing_copy_json: Any) -> list[tuple[str, str]]:
    mcj = marketing_copy_json if isinstance(marketing_copy_json, dict) else {}
    raw_items = mcj.get("page_faq")
    if not isinstance(raw_items, list):
        return []
    out: list[tuple[str, str]] = []
    for f in raw_items:
        if not isinstance(f, dict):
            continue
        q, a = _s(f.get("question")), _s(f.get("answer"))
        if q and a:
            out.append((q, a))
    return out


def _figure_html(image: dict[str, Any]) -> str:
    """描述内嵌图：src 是占位符（如 {{KP_IMG_8}}），上传方传完 WP media 后
    把它替换成站内媒体 URL —— 控制台拼 HTML 时还不知道最终图片地址。"""
    alt = escape(_s(image.get("alt")))
    title = escape(_s(image.get("title")))
    caption = _s(image.get("caption"))
    token = _s(image.get("embed_token"))
    img = f'<img src="{token}" alt="{alt}"'
    if title:
        img += f' title="{title}"'
    img += ' loading="lazy">'
    caption_html = (
        f"<figcaption>{escape(caption)}</figcaption>" if caption else ""
    )
    return f'<figure class="kp-figure">{img}{caption_html}</figure>'


def build_description_html(
    marketing_copy_json: dict[str, Any] | None,
    description_images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """description_images（可选）= placement=description 的图，按 position 升序。
    穿插规则：kp-detail 每个 chunk（h3+p）后放一张，图多出来的排在 kp-detail
    末尾；没有 kp-detail 段就放在 kp-benefits 之后 —— 图文并茂但位置确定性。"""
    ppc = _ppc(marketing_copy_json)
    images = sorted(
        description_images or [],
        key=lambda item: int(item.get("position") or 0),
    )
    parts: list[str] = ['<div class="kp-desc">']
    emitted: list[str] = []
    omitted: list[str] = []
    embedded: list[str] = []

    atf = ppc.get("above_the_fold")
    atf = atf if isinstance(atf, dict) else {}
    headline = _s(atf.get("headline"))
    subheadline = _s(atf.get("subheadline"))
    lead = _s(atf.get("short_description"))
    if headline or subheadline or lead:
        hero_parts = ['<header class="kp-hero">']
        if headline:
            hero_parts.append(f'<h2 class="kp-headline">{escape(headline)}</h2>')
        if subheadline:
            hero_parts.append(f'<p class="kp-subheadline">{escape(subheadline)}</p>')
        if lead:
            hero_parts.append(f'<p class="kp-lead">{escape(lead)}</p>')
        hero_parts.append("</header>")
        parts.append("".join(hero_parts))
        emitted.append("kp-lead")

    bullets = [_s(b) for b in (ppc.get("key_bullets") or []) if _s(b)]
    if bullets:
        items = "".join(f"<li>{escape(b)}</li>" for b in bullets)
        parts.append(
            f'<section class="kp-benefits"><ul>{items}</ul></section>'
        )
        emitted.append("kp-benefits")
    else:
        omitted.append("kp-benefits")

    image_queue = list(images)
    detail: list[str] = []
    module_idx = 0
    for chunk in ppc.get("chunk_sections") or []:
        if not isinstance(chunk, dict):
            continue
        heading, body = _s(chunk.get("heading")), _s(chunk.get("body"))
        text_html: list[str] = []
        if heading:
            text_html.append(f"<h3>{escape(heading)}</h3>")
        if body:
            text_html.append(f"<p>{escape(body)}</p>")
        fig_html = ""
        if (heading or body) and image_queue:
            image = image_queue.pop(0)
            fig_html = _figure_html(image)
            embedded.append(_s(image.get("embed_token")))
        if fig_html:
            # 图文左右并排模块（隔行左右互换），CSS 端 .kp-module(.rev) 排版
            rev = " rev" if module_idx % 2 == 1 else ""
            detail.append(
                f'<div class="kp-module{rev}">'
                f'<div class="kp-module-text">{"".join(text_html)}</div>'
                f"{fig_html}</div>"
            )
            module_idx += 1
        else:
            detail.extend(text_html)
    # 图比 chunk 多：剩余的排在 detail 末尾
    for image in image_queue:
        detail.append(_figure_html(image))
        embedded.append(_s(image.get("embed_token")))
    image_queue = []
    if detail:
        parts.append('<section class="kp-detail">' + "".join(detail) + "</section>")
        emitted.append("kp-detail")

    # kp-trust —— 信任/决策支持块（转化文案的收口）
    trust = _s(ppc.get("conversion_support_block"))
    if trust:
        parts.append(f'<aside class="kp-trust"><p>{escape(trust)}</p></aside>')
        emitted.append("kp-trust")

    spec_table = _s(ppc.get("specifications_html_table"))
    if spec_table:
        parts.append(
            '<section class="kp-specs"><h3>Specifications</h3>'
            f"{spec_table}</section>"
        )
        emitted.append("kp-specs")
    else:
        omitted.append("kp-specs")

    # kp-faq —— 可见 FAQ，原生 <details> 折叠（零 JS，wp_kses 白名单实测放行）
    # A visible FAQ may contain the evidence-backed questions retained by K's
    # validator even when there are too few of them for an FAQPage rich result.
    # Missing/legacy quality metadata therefore affects schema only, never the
    # rest of the PDP or publication flow.
    faqs = _faq_items(marketing_copy_json)
    if faqs:
        rows = "".join(
            f'<details class="kp-faq-item"><summary>{escape(q)}</summary>'
            f'<div class="kp-faq-a"><p>{escape(a)}</p></div></details>'
            for q, a in faqs
        )
        parts.append(
            '<section class="kp-faq"><h3>Frequently Asked Questions</h3>'
            f"{rows}</section>"
        )
        emitted.append("kp-faq")

    parts.append("</div>")
    return {
        "html": "".join(parts),
        "sections_emitted": emitted,
        "omitted_for_missing_data": omitted,
        "images_embedded": [token for token in embedded if token],
    }


def build_schema_jsonld(
    marketing_copy_json: dict[str, Any] | None,
    *,
    price: Any = None,
    currency: str = "USD",
    availability: str = "in_stock",
    url: str | None = None,
) -> str:
    """生成 Product + 合格 FAQPage 的 JSON-LD（客户不可见，给 Google 看）。
    Product 的 price/availability 用真实值填；FAQPage 还必须有 K 的质量判定。"""
    mcj = marketing_copy_json or {}
    scripts: list[dict[str, Any]] = []

    jl = mcj.get("json_ld") if isinstance(mcj, dict) else None
    data = jl.get("data") if isinstance(jl, dict) else None
    if isinstance(data, dict):
        prod = dict(data)
        prod.setdefault("@context", "https://schema.org")
        # 死命令：独立站结构化数据的品牌永远只有 SITE_BRAND，无条件覆盖
        # AI 写的任何 brand（第三方品牌进 Product schema = 商标+GMC 双重雷）。
        from ...k_series.product_knowledge.brand_guard import SITE_BRAND

        prod["brand"] = {"@type": "Brand", "name": SITE_BRAND}
        offers = dict(prod.get("offers") or {})
        offers["@type"] = "Offer"
        offers["priceCurrency"] = currency
        if price is not None:
            offers["price"] = str(price)
        offers["availability"] = _AVAIL_SCHEMA.get(
            availability, "https://schema.org/InStock"
        )
        if url:
            offers["url"] = url
        prod["offers"] = offers
        scripts.append(prod)

    faqs = _faq_items(marketing_copy_json)
    if faqs and faq_schema_is_eligible(marketing_copy_json):
        scripts.append(
            {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": a},
                    }
                    for q, a in faqs
                ],
            }
        )

    return "".join(
        f'<script type="application/ld+json">'
        f"{_json.dumps(s, ensure_ascii=False)}</script>"
        for s in scripts
    )


def plain_text_from_copy(marketing_copy_json: dict[str, Any] | None) -> str:
    ppc = _ppc(marketing_copy_json)
    atf = ppc.get("above_the_fold")
    atf = atf if isinstance(atf, dict) else {}
    lead = _s(atf.get("short_description")) or _s(atf.get("subheadline"))
    bullets = [_s(b) for b in (ppc.get("key_bullets") or []) if _s(b)]
    pieces = ([lead] if lead else []) + bullets
    return " · ".join(pieces)[:5000] or lead
