"""第②步补完(10-27):K 写完文案,她读稿改稿、出文案卡、按老板的意见改——这里是不连库、不出网的纯逻辑。

- copy_text():K 的文案 JSON → 买家会看到的那些字段(标题、钩子、短描述、卖点、段落、收尾、SEO、FAQ),
  给模型读、给卡片画、给前端画的都是这一份。
- 两段提示词(读稿 / 按意见改)和它们的输出解析:模型给的东西只认形状对的、在范围内的,其余丢掉。
- strip_edits():K 用 422 逐条退回的字段,从要改的东西里去掉再交一次。

规矩(都是 K 文案本来的规矩,她只是替老板先读一遍):事实只能来自档案和批过的卖点;不写价格/运费/库存/退货期限/保修/保证;
认证和保险没证书不写;别人的品牌不出现;美制单位、美式拼写、不夸张;卖点原文她不能改(走卖点审批)。
"""

from __future__ import annotations

import re
from typing import Any

from ...k_series.product_knowledge.buyer_display import contains_cjk

TEXT_FIELDS = ("headline", "subheadline", "short_description", "conversion_support_block")
SEO_FIELDS = ("title", "meta_description", "h1", "url_slug")
MAX_SECTIONS = 10
MAX_FAQ = 10
MAX_BULLETS = 20


def _text(value: Any) -> str:
    return " ".join(str(value).split()).strip() if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _strings(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(x) for x in value][:limit]


def copy_text(copy: Any) -> dict[str, Any]:
    """文案 JSON → 买家会看到的全文。缺什么就是空,不猜。"""
    copy = copy if isinstance(copy, dict) else {}
    page = copy.get("product_page_copy") if isinstance(copy.get("product_page_copy"), dict) else {}
    fold = page.get("above_the_fold") if isinstance(page.get("above_the_fold"), dict) else {}
    seo = copy.get("seo") if isinstance(copy.get("seo"), dict) else {}
    coverage = copy.get("coverage") if isinstance(copy.get("coverage"), dict) else {}
    rate = coverage.get("rate")
    return {
        "headline": _text(fold.get("headline")),
        "subheadline": _text(fold.get("subheadline")),
        "short_description": _text(fold.get("short_description")),
        "bullets": [b for b in _strings(page.get("key_bullets"), MAX_BULLETS) if b],
        "sections": [
            {"heading": _text(s.get("heading")), "body": _text(s.get("body"))}
            for s in (page.get("chunk_sections") if isinstance(page.get("chunk_sections"), list) else [])
            if isinstance(s, dict)
        ][:MAX_SECTIONS],
        "conversion_support_block": _text(page.get("conversion_support_block")),
        "seo": {key: _text(seo.get(key)) for key in SEO_FIELDS},
        "faq": [
            {"question": _text(f.get("question")), "answer": _text(f.get("answer"))}
            for f in (copy.get("page_faq") if isinstance(copy.get("page_faq"), list) else [])
            if isinstance(f, dict)
        ][:MAX_FAQ],
        "missing_inputs": [m for m in _strings(copy.get("missing_inputs"), 6) if m],
        "coverage_rate": float(rate) if isinstance(rate, (int, float)) and not isinstance(rate, bool) else None,
    }


def page_prompt(view: dict[str, Any], points: list[dict[str, Any]]) -> str:
    """全文按编号摆给模型:段落 i、FAQ i、卖点 bp1…,模型照编号回答。"""
    seo = view.get("seo") or {}
    lines = [
        f"seo.h1(页面标题): {seo.get('h1') or ''}",
        f"seo.title: {seo.get('title') or ''}",
        f"seo.meta_description: {seo.get('meta_description') or ''}",
        f"seo.url_slug: {seo.get('url_slug') or ''}",
        f"headline: {view.get('headline') or ''}",
        f"subheadline: {view.get('subheadline') or ''}",
        f"short_description: {view.get('short_description') or ''}",
        "卖点(批过的原文,不能在这里改):",
        *[f"  {b.get('id') or f'bp{i}'}: {b.get('text')}" for i, b in enumerate(points, start=1)],
        *[f"段落 {i}: [{s.get('heading')}] {s.get('body')}" for i, s in enumerate(view.get("sections") or [])],
        f"conversion_support_block: {view.get('conversion_support_block') or ''}",
        *[f"FAQ {i}: Q: {f.get('question')} / A: {f.get('answer')}" for i, f in enumerate(view.get("faq") or [])],
    ]
    return "\n".join(lines)


COPY_CHECK_ASK = (
    "你是苏青禾,美国独立站 Barong Yekhna 的运营总管。K 系统刚给一件商品写好英文商品页文案,你先读一遍、能改的直接改,再给老板看。\n"
    "只准改措辞,不准加事实:事实只能来自商品资料和批过的卖点;文案里多出来的参数、材质、数字、功效,没依据的删掉或改成有依据的说法。\n"
    "硬规矩:\n"
    "- 不写价格、运费、库存、发货时效、退货期限、保修、保证;认证(UL/FCC/CE/UN38.3/FDA/EPA 这类)和保险没有证书不能写;别人的品牌和型号不能出现。\n"
    "- 面向美国买家:美制单位优先(in / ft / lb / oz / °F,公制可放括号里),美式拼写,读起来像美国人写的——不要中式英语,不要空话和夸张词(best、#1、perfect、guaranteed、revolutionary、premium quality 这类)。\n"
    "- seo.h1 不超过 70 字符、主关键词靠前;seo.title 55–60 字符并以「| Barong Yekhna」结尾;meta_description 不超过 160 字符、一句自然话;"
    "headline 是买家结果的钩子不是产品名;short_description 2–3 句。\n"
    "- 卖点是批过的原文,这里不能改;卖点本身有问题写进 unsure。\n"
    "- 改动要小而准,只改该改的,不要重写整篇;没问题的字段给 null,没问题的段落不要列。\n"
    "只输出 JSON:\n"
    '{"summary_zh": "3 到 5 行中文:这页在卖什么、主打什么、我整体觉得怎样",\n'
    ' "edits": {"headline": null, "subheadline": null, "short_description": null, "conversion_support_block": null,\n'
    '   "chunk_sections": [{"index": 0, "heading": null, "body": "改后的英文"}],\n'
    '   "seo": {"title": null, "meta_description": null, "h1": null, "url_slug": null},\n'
    '   "page_faq": [{"index": 0, "answer": "改后的英文答案"}]},\n'
    ' "notes": ["一句中文:改了哪里、为什么(一处一条)"],\n'
    ' "unsure": ["一句中文:拿不准、要老板定的(没有就空数组)"]}'
)

COPY_REWORK_ASK = (
    "老板驳回了这件商品的文案卡,下面是他的原话和文案全文(段落按序号、卖点按编号、FAQ 按序号)。把他的意见落成具体改动,只输出 JSON:\n"
    '{"edits": {"headline": null, "subheadline": null, "short_description": null, "conversion_support_block": null,\n'
    '   "chunk_sections": [{"index": 0, "heading": null, "body": null}], "seo": {"title": null, "meta_description": null, "h1": null, "url_slug": null},\n'
    '   "page_faq": [{"index": 0, "answer": null}]},\n'
    ' "bullet_edits": [{"id": "bp2", "text": "卖点改后的英文"}],\n'
    ' "drop_points": ["要去掉的卖点编号"],\n'
    ' "unclear": "他说的里面对不上文案、或者我改不了的那部分,原话照抄;没有就空字符串"}\n'
    "规矩:只按老板说的改,不顺手改别的;不能新增事实;卖点改措辞必须还是同一个事实(K 会逐条核证据);"
    "老板说某句不对而那句是卖点原文,就改那条卖点或去掉它;不写价格/运费/库存/退货期限/保修/保证,没证书的认证和保险不写,别人的品牌不出现,美制单位、美式拼写。"
)


def check_prompt_extra(
    view: dict[str, Any],
    points: list[dict[str, Any]],
    *,
    main_keyword: str | None,
    held: list[str],
    hype: list[str],
    flagged: list[str],
    boss_note: str | None = None,
    priorities: list[str] | None = None,
) -> str:
    parts = [
        f"主关键词:{main_keyword or '(没定)'}",
        *([f"买家最在乎的(从同类商品页上拆出来的,只核对文案有没有讲到、顺序对不对;不能据此加事实):{';'.join(priorities)[:400]}"] if priorities else []),
        *([f"老板上一版文案的意见(这版是照它改了卖点后重写的,读的时候对着看):{boss_note[:400]}"] if boss_note else []),
        *([f"没证书、不能写进文案的认证说法:{';'.join(held)[:400]}"] if held else []),
        *([f"卖家的宣传语(别用):{'、'.join(hype)[:300]}"] if hype else []),
        *([f"档案里还没定的:{'、'.join(flagged)[:300]}"] if flagged else []),
        *([f"K 自己标的没依据所以没写的:{';'.join(view.get('missing_inputs') or [])[:400]}"] if view.get("missing_inputs") else []),
        "英文商品页全文:",
        page_prompt(view, points),
    ]
    return "\n".join(parts)


def rework_prompt_extra(view: dict[str, Any], points: list[dict[str, Any]], reason: str) -> str:
    return f"老板原话:{reason}\n\n英文商品页全文:\n{page_prompt(view, points)}"


def _usable(value: Any) -> str | None:
    """模型给的一段英文:空、非字符串、带中文的都不用。"""
    text = _text(value)
    if not text or contains_cjk(text):
        return None
    return text


def parse_edits(data: Any, *, sections: int, faqs: int) -> dict[str, Any]:
    """模型给的 edits → K 接口要的形状。只收形状对、编号在范围内、真有内容的。"""
    data = data if isinstance(data, dict) else {}
    out: dict[str, Any] = {}
    for key in TEXT_FIELDS:
        text = _usable(data.get(key))
        if text:
            out[key] = text
    seo_in = data.get("seo") if isinstance(data.get("seo"), dict) else {}
    seo = {key: text for key in SEO_FIELDS if (text := _usable(seo_in.get(key)))}
    if seo:
        out["seo"] = seo
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in data.get("chunk_sections") if isinstance(data.get("chunk_sections"), list) else []:
        if not isinstance(item, dict) or isinstance(item.get("index"), bool) or not isinstance(item.get("index"), int):
            continue
        index = item["index"]
        if index < 0 or index >= sections or index in seen:
            continue
        entry = {"index": index}
        for key in ("heading", "body"):
            text = _usable(item.get(key))
            if text:
                entry[key] = text
        if len(entry) > 1:
            rows.append(entry)
            seen.add(index)
    if rows:
        out["chunk_sections"] = rows
    answers: list[dict[str, Any]] = []
    seen = set()
    for item in data.get("page_faq") if isinstance(data.get("page_faq"), list) else []:
        if not isinstance(item, dict) or isinstance(item.get("index"), bool) or not isinstance(item.get("index"), int):
            continue
        index = item["index"]
        text = _usable(item.get("answer"))
        if index < 0 or index >= faqs or index in seen or not text:
            continue
        answers.append({"index": index, "answer": text})
        seen.add(index)
    if answers:
        out["page_faq"] = answers
    return out


def _zh_lines(value: Any, limit: int) -> list[str]:
    return [t[:300] for t in (_text(x) for x in (value if isinstance(value, list) else [])) if t][:limit]


def parse_check(result: Any, *, sections: int, faqs: int) -> dict[str, Any]:
    data = result if isinstance(result, dict) else {}
    return {
        "summary_zh": _text(data.get("summary_zh"))[:800],
        "edits": parse_edits(data.get("edits"), sections=sections, faqs=faqs),
        "notes": _zh_lines(data.get("notes"), 12),
        "unsure": _zh_lines(data.get("unsure"), 8),
    }


def parse_rework(result: Any, *, sections: int, faqs: int, point_ids: set[str]) -> dict[str, Any]:
    data = result if isinstance(result, dict) else {}
    bullet_edits: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data.get("bullet_edits") if isinstance(data.get("bullet_edits"), list) else []:
        if not isinstance(item, dict):
            continue
        pid, text = _text(item.get("id")), _usable(item.get("text"))
        if pid in point_ids and pid not in seen and text:
            bullet_edits.append({"id": pid, "text": text})
            seen.add(pid)
    drop = [pid for pid in dict.fromkeys(_text(x) for x in (data.get("drop_points") if isinstance(data.get("drop_points"), list) else [])) if pid in point_ids and pid not in seen]
    return {
        "edits": parse_edits(data.get("edits"), sections=sections, faqs=faqs),
        "bullet_edits": bullet_edits,
        "drop_points": drop,
        "unclear": _text(data.get("unclear"))[:400],
    }


def card_evidence(
    *,
    dossier_id: int,
    product_id: str,
    sku: str,
    main_keyword: str | None,
    view: dict[str, Any],
    points: list[dict[str, Any]],
    check: dict[str, Any],
    history_unclear: str,
    held: list[str],
    hype: list[str],
    flagged: list[str],
    brief_paused: bool,
    copy_digest: str,
    card_kind: str,
) -> dict[str, Any]:
    """文案卡的 evidence(前端 card-view 照这个形状画;测试夹具也从这里出)。"""
    return {
        "dossier_id": dossier_id,
        "k_product_id": product_id,
        "sku": sku,
        "main_keyword": main_keyword,
        "copy": view,
        "points": [{"id": str(p.get("id") or ""), "text": _text(p.get("text"))} for p in points],
        "check": {
            "summary_zh": _text(check.get("summary_zh"))[:800],
            "notes": _zh_lines(check.get("notes"), 14),
            "unsure": _zh_lines(check.get("unsure"), 8),
            "changed": [_text(c) for c in (check.get("changed") if isinstance(check.get("changed"), list) else []) if _text(c)],
            "adjusted": [a for a in (check.get("adjusted") if isinstance(check.get("adjusted"), list) else []) if isinstance(a, dict)],
        },
        "history_unclear": _text(history_unclear)[:400],
        "held_certifications": held,
        "hype": hype,
        "flagged": flagged,
        "brief_paused": brief_paused,
        "copy_digest": copy_digest,
        "recheck": {"type": card_kind, "product_id": product_id},
    }


_FIELD = re.compile(r"^(chunk_sections|page_faq)\[(\d+)\]\.(\w+)$")


def strip_edits(edits: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """K 退回的字段路径(above_the_fold.headline / chunk_sections[2].body / seo.title / page_faq[1].answer / conversion_support_block)从 edits 里去掉。"""
    out: dict[str, Any] = {k: (dict(v) if isinstance(v, dict) else [dict(x) for x in v] if isinstance(v, list) else v) for k, v in edits.items()}
    for field in fields:
        m = _FIELD.match(field)
        if m:
            key, index, sub = m.group(1), int(m.group(2)), m.group(3)
            rows = out.get(key) or []
            for row in rows:
                if row.get("index") == index:
                    row.pop(sub, None)
            out[key] = [row for row in rows if len(row) > 1]
            if not out[key]:
                out.pop(key, None)
        elif field.startswith("above_the_fold."):
            out.pop(field.split(".", 1)[1], None)
        elif field.startswith("seo."):
            seo = out.get("seo") or {}
            seo.pop(field.split(".", 1)[1], None)
            if seo:
                out["seo"] = seo
            else:
                out.pop("seo", None)
        else:
            out.pop(field, None)
    return out


__all__ = [
    "COPY_CHECK_ASK",
    "COPY_REWORK_ASK",
    "check_prompt_extra",
    "copy_text",
    "page_prompt",
    "parse_check",
    "parse_edits",
    "parse_rework",
    "rework_prompt_extra",
    "strip_edits",
]
