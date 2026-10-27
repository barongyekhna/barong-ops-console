"""K 文案的「按意见改」入口(2026-10-27,苏青禾第②步补完)。

以前 K 的英文商品页文案只有「生成」和「重新生成」,没有「改一句」:老板说标题太长、第二段换个说法,
只能整篇重写,写出来的又不是他看过的那版。这里补上逐字段的改稿入口,给苏青禾(和将来的 K 页面)用。

规矩(都是 K 原有的,不另立):
- 改的只是措辞,事实不能新增:改完照生成时同一套顺序再过一遍 K 的确定性校验——
  卖点栏永远是批过卖点的原文(project_approved_selling_points)、包装数量/件数核证据、FAQ 校验、
  标题/H1 里没证据的片段删掉、SEO 收口、多包装盒内文案、关键词覆盖率。校验把改的内容又改回去或删掉,
  调用方会收到 ``adjusted``,知道哪条没按它的来。
- 买家可见的字段不许中文、不许第三方品牌(品牌黑名单)、不许价格/运费/库存/退货期限/保修/认证/保险这些
  K 的文案规矩本来就不让写进去的东西(红线词表)。
- 卖点原文(key_bullets)和规格表(specifications_html_table)不在这里改:卖点去走卖点审批(K 逐条核证据),
  规格表是程序按规格生成的。
- 证据契约(evidence_contract / evidence_digest)原样保留——事实没变,P 的上架门禁照常认。
- 每次改都记进 ``revisions``(谁、为什么、改了哪些字段、哪些被校验改回去了),文案的中文对照
  (marketing_copy_zh)是改前那版的翻译,改完清掉,免得运营拿旧中文对新英文。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .brand_guard import SITE_BRAND, blacklist_violations, normalized_brand_terms
from .buyer_display import contains_cjk
from .evidence_guard import (
    TitleEvidenceConsistencyError,
    canonical_package_includes,
    enforce_package_evidence_consistency,
    enforce_title_evidence_consistency,
    project_approved_selling_points,
)
from .faq_research import _contains_third_party_brand, is_faq_text_brand_safe, validate_generated_faq
from .models import KProductKnowledgeProduct, KProductKnowledgeWorkflowExecution

EDIT_SOURCE_DEFAULT = "manual_review"
MAX_REVISIONS = 20

# 字段 → 最长字符数。超了不是截断,是退回:写文案的人该自己收。
LIMITS = {
    "headline": 120,
    "subheadline": 220,
    "short_description": 700,
    "conversion_support_block": 900,
    "section_heading": 140,
    "section_body": 1500,
    "seo.title": 70,
    "seo.meta_description": 160,
    "seo.h1": 90,
    "seo.url_slug": 80,
    "faq_answer": 700,
}
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# K 文案指令里本来就禁止写进文案的东西(价格/运费/库存是店铺结构化字段,退货/保修/认证/保险没证书不能说)。
_RED_LINES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\$\s?\d"), "文案里不写价格"),
    (re.compile(r"\bfree shipping\b", re.IGNORECASE), "文案里不写运费"),
    (re.compile(r"\b(in stock|out of stock|ships? (within|in) \d)", re.IGNORECASE), "文案里不写库存和发货时效"),
    (re.compile(r"\b\d+[\s-]?day (return|refund|money[\s-]?back)", re.IGNORECASE), "退货期限不写进文案"),
    (re.compile(r"\b(lifetime|limited) (warranty|guarantee)\b|\bwarranty\b|\bguaranteed?\b", re.IGNORECASE), "保修/保证不写进文案"),
    (re.compile(r"\b(UL|ETL|FCC|CE|RoHS|REACH|UN38\.3|FDA|EPA|CPSC|CPSIA)[\s-]?(certified|listed|approved|compliant|registered|certification)?\b"), "认证说法没证书不能写"),
    (re.compile(r"\binsur(ed|ance)\b", re.IGNORECASE), "保险说法不写进文案"),
)


class CopyEditError(Exception):
    """改稿没成。``items`` 逐条说哪个字段为什么不行,给调用方原样转给人看。"""

    def __init__(self, code: str, message: str, *, status_code: int = 422, items: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.items = items or []


def _clean(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split()).strip()


def _text_problems(field: str, value: str, *, limit: int, brand_terms: list[str], faq: bool = False) -> list[str]:
    problems: list[str] = []
    if not value:
        problems.append("不能为空")
        return problems
    if len(value) > limit:
        problems.append(f"太长({len(value)} 字符,最多 {limit})")
    if contains_cjk(value):
        problems.append("买家可见内容不允许中文")
    for violation in blacklist_violations([(field, value)], brand_terms):
        problems.append(f"含第三方品牌词「{violation['term']}」")
    # 明确的第三方品牌表所有字段都查;FAQ 那套「像不像专有名词」的启发式只用在 FAQ 答案上——
    # 它把 "2.11 GPM" 这种数字加单位也当专有名词,正文里到处都是这种写法(K 手改 FAQ 的接口也只在 FAQ 上用它)
    if _contains_third_party_brand(value) or (faq and not is_faq_text_brand_safe(value)):
        problems.append("含第三方品牌或型号")
    for pattern, why in _RED_LINES:
        if pattern.search(value):
            problems.append(why)
    return problems


def _latest_execution(db: Session, product_id: Any) -> KProductKnowledgeWorkflowExecution | None:
    # 晚导入:data_isolation 和 db.session 互相引用,这个模块单独被 import 时(发版冒烟逐模块 import)先引它会撞循环导入
    from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION

    return db.scalar(
        select(KProductKnowledgeWorkflowExecution)
        .where(KProductKnowledgeWorkflowExecution.product_id == product_id)
        .order_by(KProductKnowledgeWorkflowExecution.created_at.desc())
        .limit(1),
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )


def _get(copy: dict[str, Any], *path: str) -> Any:
    node: Any = copy
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def apply_copy_edits(
    db: Session,
    product: KProductKnowledgeProduct,
    edits: dict[str, Any],
    *,
    actor_user_id: str | None,
    reason: str | None = None,
    source: str = EDIT_SOURCE_DEFAULT,
) -> dict[str, Any]:
    """逐字段改 ``marketing_copy_json``,改完再过一遍 K 的校验链。返回 {changed, adjusted, marketing_copy}。

    ``edits`` 的形状(都可省):
      headline / subheadline / short_description / conversion_support_block: str
      chunk_sections: [{index, heading?, body?}]
      seo: {title?, meta_description?, h1?, url_slug?}
      page_faq: [{index, answer}]
    """
    copy = product.marketing_copy_json
    if not isinstance(copy, dict) or not isinstance(copy.get("product_page_copy"), dict):
        raise CopyEditError("MARKETING_COPY_MISSING", "这个品还没有文案,先生成再改。", status_code=409)
    if str(copy.get("channel") or "dtc").strip().lower() != "dtc":
        raise CopyEditError("MARKETING_COPY_CHANNEL_UNSUPPORTED", "只支持独立站(dtc)文案的改稿。", status_code=409)
    from ...p_series.upload.assemble import _evidence_gate_blockers  # P 门禁同一判据;晚导入避免 K↔P 互相导入

    blockers = _evidence_gate_blockers(product)
    if blockers:
        raise CopyEditError("MARKETING_COPY_STALE", "文案的证据快照已经过期,先重新生成再改:" + ";".join(blockers), status_code=409)

    staged = {**copy, "product_page_copy": dict(copy["product_page_copy"])}
    page = staged["product_page_copy"]
    fold = dict(page.get("above_the_fold") or {}) if isinstance(page.get("above_the_fold"), dict) else {}
    sections = [dict(s) if isinstance(s, dict) else {} for s in (page.get("chunk_sections") or [])]
    seo = dict(staged.get("seo") or {}) if isinstance(staged.get("seo"), dict) else {}
    faq = [dict(f) if isinstance(f, dict) else {} for f in (staged.get("page_faq") or [])]
    brand_terms = normalized_brand_terms(product)
    items: list[dict[str, Any]] = []
    wanted: dict[str, str] = {}  # 字段路径 → 想改成什么(校验后比对,看有没有被改回去)

    def take(field: str, value: Any, *, limit_key: str, faq: bool = False) -> str | None:
        if value is None:
            return None
        text = _clean(value)
        problems = _text_problems(field, text, limit=LIMITS[limit_key], brand_terms=brand_terms, faq=faq)
        if problems:
            items.append({"field": field, "error": ";".join(problems)})
            return None
        wanted[field] = text
        return text

    for key in ("headline", "subheadline", "short_description"):
        text = take(f"above_the_fold.{key}", edits.get(key), limit_key=key)
        if text is not None:
            fold[key] = text
    text = take("conversion_support_block", edits.get("conversion_support_block"), limit_key="conversion_support_block")
    if text is not None:
        page["conversion_support_block"] = text
    for entry in edits.get("chunk_sections") or []:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(sections):
            items.append({"field": f"chunk_sections[{index}]", "error": f"没有这一段(现在共 {len(sections)} 段)"})
            continue
        for key, limit_key in (("heading", "section_heading"), ("body", "section_body")):
            text = take(f"chunk_sections[{index}].{key}", entry.get(key), limit_key=limit_key)
            if text is not None:
                sections[index][key] = text
    seo_edits = edits.get("seo") if isinstance(edits.get("seo"), dict) else {}
    for key in ("title", "meta_description", "h1", "url_slug"):
        text = take(f"seo.{key}", seo_edits.get(key), limit_key=f"seo.{key}")
        if text is None:
            continue
        if key == "url_slug":
            text = text.lower()
            if not _SLUG.match(text):
                items.append({"field": "seo.url_slug", "error": "只能是小写字母、数字和连字符"})
                wanted.pop("seo.url_slug", None)
                continue
            wanted["seo.url_slug"] = text
        seo[key] = text
    for entry in edits.get("page_faq") or []:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(faq):
            items.append({"field": f"page_faq[{index}]", "error": f"没有这一问(现在共 {len(faq)} 问)"})
            continue
        text = take(f"page_faq[{index}].answer", entry.get("answer"), limit_key="faq_answer", faq=True)
        if text is not None:
            faq[index]["answer"] = text
    for key in ("key_bullets", "specifications_html_table"):
        if key in edits:
            items.append({"field": key, "error": "卖点原文走卖点审批改,规格表是程序按规格生成的,这里都不能改"})
    if items:
        raise CopyEditError("MARKETING_COPY_EDIT_INVALID", "有几处改不了:" + ";".join(f"{i['field']}:{i['error']}" for i in items), items=items)
    if not wanted:
        raise CopyEditError("MARKETING_COPY_EDIT_EMPTY", "没有要改的字段。")

    page["above_the_fold"] = fold
    page["chunk_sections"] = sections
    staged["seo"] = seo
    staged["page_faq"] = faq
    staged = _reenforce(db, product, staged)

    changed = sorted(wanted)
    adjusted = [
        {"field": field, "wanted": value, "got": _clean(_lookup(staged, field))}
        for field, value in wanted.items()
        if _clean(_lookup(staged, field)) != value
    ]
    revision = {
        "at": datetime.now(UTC).isoformat(),
        "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
        "source": (source or EDIT_SOURCE_DEFAULT)[:100],
        "reason": _clean(reason)[:500],
        "fields": changed,
        "adjusted": adjusted,
    }
    staged["revisions"] = [*[r for r in (copy.get("revisions") or []) if isinstance(r, dict)][-(MAX_REVISIONS - 1) :], revision]
    product.marketing_copy_json = staged
    product.marketing_copy_zh = None  # 改前那版的中文对照,留着会误导
    db.add(product)
    return {"changed": changed, "adjusted": adjusted, "marketing_copy": staged}


def _lookup(copy: dict[str, Any], field: str) -> Any:
    """按本文件的字段路径取值(above_the_fold.x / chunk_sections[i].x / seo.x / page_faq[i].answer / conversion_support_block)。"""
    page = copy.get("product_page_copy") if isinstance(copy.get("product_page_copy"), dict) else {}
    m = re.match(r"^(chunk_sections|page_faq)\[(\d+)\]\.(\w+)$", field)
    if m:
        rows = page.get("chunk_sections") if m.group(1) == "chunk_sections" else copy.get("page_faq")
        rows = rows if isinstance(rows, list) else []
        i = int(m.group(2))
        return rows[i].get(m.group(3)) if i < len(rows) and isinstance(rows[i], dict) else None
    if field.startswith("above_the_fold."):
        return _get(page, "above_the_fold", field.split(".", 1)[1])
    if field.startswith("seo."):
        return _get(copy, "seo", field.split(".", 1)[1])
    return page.get(field)


def _reenforce(db: Session, product: KProductKnowledgeProduct, staged: dict[str, Any]) -> dict[str, Any]:
    """改完照生成时同一套顺序再过一遍 K 的确定性校验(generate_marketing_copy._postprocess_copy,去掉要出网的 FAQ 重写)。"""
    from .workflow_engine import (
        _approved_selling_points_snapshot,
        _final_keywords_for_copy,
        _finalize_dtc_seo,
        _pack_aware_box_section,
        _stamp_keyword_coverage,
        _variant_pack_quantities,
    )

    approved_points = _approved_selling_points_snapshot(product)
    package_includes = canonical_package_includes(getattr(product, "package_includes_json", None), product.structured_specs_json)
    final_keywords = _final_keywords_for_copy(_latest_execution(db, product.id))
    out = project_approved_selling_points(staged, approved_points)
    try:
        out = enforce_package_evidence_consistency(out, package_includes=package_includes, structured_specs=product.structured_specs_json)
        if isinstance(product.faq_research_json, dict):
            # 没留研究资料的老品跳过:这一步靠研究资料核 FAQ 的出处,没资料会把整组 FAQ 当编的删光
            out = validate_generated_faq(
                out,
                product.faq_research_json,
                approved_selling_points=approved_points,
                structured_specs=product.structured_specs_json,
                package_includes=package_includes,
            )
        out = enforce_title_evidence_consistency(
            out,
            product_name=product.product_name_en,
            product_type=product.product_type,
            category_name=(product.category_path or product.merchant_product_type or product.category_hint),
            site_brand=SITE_BRAND,
            approved_selling_points={"bullets": approved_points},
            structured_specs=product.structured_specs_json,
            package_includes=package_includes,
        )
        out = _finalize_dtc_seo(out, final_keywords=final_keywords, site_brand=SITE_BRAND, structured_specs=product.structured_specs_json, package_includes=package_includes)
    except TitleEvidenceConsistencyError as exc:
        raise CopyEditError("MARKETING_COPY_TITLE_DEGENERATE", f"标题改成这样 K 不认(没有实质内容或数字对不上证据):{exc}") from exc
    out = _pack_aware_box_section(out, pack_quantities=_variant_pack_quantities(db, product), package_includes=package_includes)
    return _stamp_keyword_coverage(out, final_keywords)


__all__ = ["CopyEditError", "LIMITS", "apply_copy_edits"]
