"""把 K 的 marketing_copy_json 按 product-page-layout skill 的统一骨架拼成
WooCommerce 的 description_html。

内容 AI 早在文案阶段就生成好了（product_page_copy: above_the_fold / key_bullets
/ chunk_sections / specifications_html_table），这里只做**确定性排版**，不再调 AI。
铁律（见 SKILL.md）：正文绝不含价格 / 库存 / 配送 —— 那些走结构化字段，写进
正文 = feed↔落地页不一致 = GMC 虚假陈述头号原因。
"""

from __future__ import annotations

from html import escape
from typing import Any


def _s(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def build_description_html(marketing_copy_json: dict[str, Any] | None) -> dict[str, Any]:
    mcj = marketing_copy_json or {}
    ppc = mcj.get("product_page_copy") if isinstance(mcj, dict) else None
    ppc = ppc if isinstance(ppc, dict) else {}

    parts: list[str] = ['<div class="kp-desc">']
    emitted: list[str] = []
    omitted: list[str] = []

    # kp-lead —— 首屏主打段
    atf = ppc.get("above_the_fold")
    atf = atf if isinstance(atf, dict) else {}
    lead = _s(atf.get("short_description")) or _s(atf.get("subheadline"))
    if lead:
        parts.append(f'<p class="kp-lead">{escape(lead)}</p>')
        emitted.append("kp-lead")

    # kp-benefits —— 卖点列表
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

    # kp-detail —— 分块描述段落（heading + body）
    detail: list[str] = []
    for chunk in ppc.get("chunk_sections") or []:
        if not isinstance(chunk, dict):
            continue
        heading = _s(chunk.get("heading"))
        body = _s(chunk.get("body"))
        if heading:
            detail.append(f"<h3>{escape(heading)}</h3>")
        if body:
            detail.append(f"<p>{escape(body)}</p>")
    if detail:
        parts.append('<section class="kp-detail">' + "".join(detail) + "</section>")
        emitted.append("kp-detail")

    # kp-specs —— 规格表（AI 已生成的 HTML 表，直接嵌）
    spec_table = _s(ppc.get("specifications_html_table"))
    if spec_table:
        parts.append(
            '<section class="kp-specs"><h3>Specifications</h3>'
            f"{spec_table}</section>"
        )
        emitted.append("kp-specs")
    else:
        omitted.append("kp-specs")

    parts.append("</div>")

    return {
        "html": "".join(parts),
        "sections_emitted": emitted,
        "omitted_for_missing_data": omitted,
    }


def plain_text_from_copy(marketing_copy_json: dict[str, Any] | None) -> str:
    """GMC feed 用的纯文本描述（同源，避免 feed↔页不一致）。"""
    mcj = marketing_copy_json or {}
    ppc = mcj.get("product_page_copy") if isinstance(mcj, dict) else None
    ppc = ppc if isinstance(ppc, dict) else {}
    atf = ppc.get("above_the_fold")
    atf = atf if isinstance(atf, dict) else {}
    lead = _s(atf.get("short_description")) or _s(atf.get("subheadline"))
    bullets = [_s(b) for b in (ppc.get("key_bullets") or []) if _s(b)]
    pieces = [lead] if lead else []
    pieces.extend(bullets)
    return " · ".join(pieces)[:5000] or lead
