"""把 K 的 marketing_copy_json 按 product-page-layout skill 骨架拼成
WooCommerce 的 description_html，并生成 Schema.org 结构化数据（Product + FAQPage）。

内容 AI（gpt-5.5）早在文案阶段就生成好了（product_page_copy / page_faq / json_ld），
这里只做**确定性排版 + schema 组装**，不再调 AI。

排版铁律（见 SKILL.md）：正文绝不含价格/库存/配送（走结构化字段）。
Schema 铁律：FAQPage 的问答 = 页面可见 FAQ（同源，Google 硬规定，防惩罚）；
Product 的 price/availability 用上架时的真实值填（与 feed 同源）。

样式：HTML 只带稳定 class（kp-*），CSS 加在主题里一次、全站生效 —— 不往每个
产品里塞内联样式。CSS 见 P_PRODUCT_PAGE_CSS。
"""

from __future__ import annotations

import json as _json
from html import escape
from typing import Any

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


def _faq_items(marketing_copy_json: dict[str, Any] | None) -> list[tuple[str, str]]:
    mcj = marketing_copy_json or {}
    out: list[tuple[str, str]] = []
    for f in mcj.get("page_faq") or []:
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
    lead = _s(atf.get("short_description")) or _s(atf.get("subheadline"))
    if lead:
        parts.append(f'<p class="kp-lead">{escape(lead)}</p>')
        emitted.append("kp-lead")

    bullets = [_s(b) for b in (ppc.get("key_bullets") or []) if _s(b)]
    if bullets:
        items = "".join(f"<li>{escape(b)}</li>" for b in bullets)
        parts.append(
            '<section class="kp-benefits"><h3>Highlights</h3>'
            f"<ul>{items}</ul></section>"
        )
        emitted.append("kp-benefits")
    else:
        omitted.append("kp-benefits")

    image_queue = list(images)
    detail: list[str] = []
    for chunk in ppc.get("chunk_sections") or []:
        if not isinstance(chunk, dict):
            continue
        heading, body = _s(chunk.get("heading")), _s(chunk.get("body"))
        if heading:
            detail.append(f"<h3>{escape(heading)}</h3>")
        if body:
            detail.append(f"<p>{escape(body)}</p>")
        if (heading or body) and image_queue:
            image = image_queue.pop(0)
            detail.append(_figure_html(image))
            embedded.append(_s(image.get("embed_token")))
    # 图比 chunk 多：剩余的排在 detail 末尾
    for image in image_queue:
        detail.append(_figure_html(image))
        embedded.append(_s(image.get("embed_token")))
    image_queue = []
    if detail:
        parts.append('<section class="kp-detail">' + "".join(detail) + "</section>")
        emitted.append("kp-detail")

    spec_table = _s(ppc.get("specifications_html_table"))
    if spec_table:
        parts.append(
            '<section class="kp-specs"><h3>Specifications</h3>'
            f"{spec_table}</section>"
        )
        emitted.append("kp-specs")
    else:
        omitted.append("kp-specs")

    # kp-faq —— 可见 FAQ（和 FAQPage schema 同源）
    faqs = _faq_items(marketing_copy_json)
    if faqs:
        rows = "".join(
            f'<div class="kp-faq-item"><dt class="kp-faq-q">{escape(q)}</dt>'
            f'<dd class="kp-faq-a">{escape(a)}</dd></div>'
            for q, a in faqs
        )
        parts.append(
            '<section class="kp-faq"><h3>Frequently Asked Questions</h3>'
            f"<dl>{rows}</dl></section>"
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
    """生成 Product + FAQPage 的 <script type=ld+json>（客户不可见，给 Google 看）。
    Product 的 price/availability 用真实值填（同源）；FAQPage 用页面同一份 FAQ。"""
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
    if faqs:
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
