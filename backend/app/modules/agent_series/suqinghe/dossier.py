"""1688 抓取结果 → K 档案草稿(10-23 苏青禾的第一项真本事)。

规矩(潜水泵教训):
- 每个字段都带来源(页面 JSON / 页面文本 / 第几张详情图第几段),谁说的一眼能查。
- 两个来源说法不一样 → conflict,双方原话都留着,不替老板选。
- 哪都没有,或者卖家只写了「如图」「其他」这种占位 → missing,**空着,不猜**。
- 1688 只有进价,没有售价 → retail_price 永远是 needs_owner。
- 英文品名只能从事实里来:让 writer 档改写,不许编参数、不许带品牌。

AI 调用(英文名 / 包装清单翻译 / 类目)都可以注入,测试不出网。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DRAFT_VERSION = 1
ALLOWED_IMAGE_HOSTS = ("alicdn.com",)

# 卖家常用的占位写法:看着有值,其实什么都没说。
PLACEHOLDERS = {
    "", "如图", "见图", "详见图片", "详见详情", "详情见图", "其他", "其它", "无", "暂无", "不详",
    "/", "-", "—", "--", "n/a", "na", "none", "other", "可定制", "定制", "以实物为准",
}

# 中文属性名 → 档案规格键。没列进来的属性留在 other_attributes 里给老板看,不进规格。
SPEC_ALIASES: dict[str, tuple[str, ...]] = {
    "material": ("材质", "玩具材质", "产品材质", "材料", "面料", "主要材质", "外壳材质", "material"),
    "dimensions": ("尺寸", "产品尺寸", "规格尺寸", "外形尺寸", "大小", "产品规格尺寸", "dimensions", "size"),
    "weight": ("重量", "产品重量", "净重", "单品重量", "weight", "net weight"),
    "age_range": ("适用年龄", "年龄范围", "适用年龄段", "适合年龄", "age", "age range", "ages"),
    "color": ("颜色", "产品颜色", "颜色分类", "color", "colour"),
    "packaging": ("包装", "包装方式", "包装形式", "packaging", "package type"),
    "power": ("功率", "额定功率", "power"),
    "voltage": ("电压", "额定电压", "voltage"),
    "battery": ("电池类型", "电池", "电池容量", "battery"),
    # 「产地:浙江省」和「原产国/地区:大陆」是两个粒度,不是矛盾,分开放。
    "origin_region": ("产地", "发货地"),
    "origin_country": ("原产国/地区", "原产国", "country of origin"),
    "applicable_people": ("适用人群", "target users"),
}
SPEC_LABELS_ZH = {
    "material": "材质", "dimensions": "尺寸", "weight": "重量", "age_range": "适用年龄",
    "color": "颜色", "packaging": "包装", "power": "功率", "voltage": "电压",
    "battery": "电池", "origin_region": "产地", "origin_country": "原产国", "applicable_people": "适用人群",
}
PACKAGE_FIELDS = ("package_includes", "package includes", "包装清单", "包装内含", "配件", "in the box", "包装含")
# 和产品本身无关、或者品牌身份(K 不收品牌当规格)的属性,直接丢。
IGNORED_ATTRIBUTES = ("品牌", "货号", "专利", "主要下游平台", "主要销售地区", "是否", "有可授权", "上市时间", "加工方式", "动漫角色")

WriterFn = Callable[[dict[str, Any]], dict[str, Any] | None]
ClassifierFn = Callable[[Session, str], Any]


def _field(value: Any = None, *, unit: str | None = None, sources: list[dict[str, Any]] | None = None,
           status: str = "ok", note: str = "") -> dict[str, Any]:
    return {"value": value, "unit": unit, "sources": sources or [], "status": status, "note": note}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_placeholder(value: Any) -> bool:
    text = _clean(value).strip("。.;；,， ").casefold()
    return text in PLACEHOLDERS


def _norm_for_compare(value: Any) -> str:
    text = _clean(value).casefold()
    text = text.replace("（", "(").replace("）", ")").replace("岁", "").replace("ages", "").replace("age", "")
    return re.sub(r"[\s,，、;；:：+()（）]+", "", text)


_CJK_ALIAS = re.compile(r"[\u3400-\u9fff]")


def _spec_key(name: Any) -> str | None:
    """属性名 → 规格键。完全相等优先;中文别名允许包含匹配,英文别名只认整词
    (否则 package_includes 里的 "age" 会被当成年龄 —— 10-23 首测踩到)。"""
    label = _clean(name).casefold()
    if not label or label in PACKAGE_FIELDS:
        return None
    for key, aliases in SPEC_ALIASES.items():
        if any(label == alias.casefold() for alias in aliases):
            return key
    words = set(re.split(r"[^a-z0-9]+", label))
    for key, aliases in SPEC_ALIASES.items():
        for alias in aliases:
            folded = alias.casefold()
            if _CJK_ALIAS.search(folded):
                if len(folded) >= 2 and folded in label:
                    return key
            elif " " in folded:
                if folded in label:
                    return key
            elif folded in words:
                return key
    return None


def _ignored(name: Any) -> bool:
    label = _clean(name)
    return any(term in label for term in IGNORED_ATTRIBUTES)


def _host_ok(url: Any) -> bool:
    text = str(url or "")
    return text.startswith(("http://", "https://")) and any(host in text for host in ALLOWED_IMAGE_HOSTS)


def _image_source(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "image",
        "ref": f"详情图 {int(fact.get('image_index') or 0) + 1} · 第 {int(fact.get('segment_index') or 0) + 1} 段",
        "raw": _clean(fact.get("raw_text") or fact.get("value"))[:300],
    }


# ---------------------------------------------------------------- 规格合并


# 只有重量和尺寸按层级分开记:单品 / 单个销售包装 / 批发外箱。其它字段(材质、年龄……)不分层。
_SCOPED_SPEC_KEYS = {"weight", "dimensions"}
_SCOPE_SUFFIX = {"inner_pack": "_pack", "carton": "_carton"}


def _scoped_key(key: str, scope: Any) -> str:
    if key in _SCOPED_SPEC_KEYS:
        return key + _SCOPE_SUFFIX.get(str(scope or ""), "")
    return key


def merge_specs(capture: dict[str, Any], facts: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """属性表 + 详情图事实 → {规格键: 字段}。返回 (specs, other_attributes)。"""
    observations: dict[str, list[tuple[str, str | None, dict[str, Any]]]] = {}
    other: list[dict[str, str]] = []
    for attr in capture.get("attributes") or []:
        name, value = _clean(attr.get("name")), _clean(attr.get("value"))
        if not name or _ignored(name):
            continue
        key = _spec_key(name)
        kind = "page_json" if attr.get("source") == "page_json" else "page_text"
        source = {"kind": kind, "ref": f"属性「{name}」", "raw": value[:300]}
        if key is None:
            if value and not is_placeholder(value):
                other.append({"name": name, "value": value[:300]})
            continue
        observations.setdefault(key, []).append((value, None, source))
    for fact in facts or []:
        key = _spec_key(fact.get("field"))
        if key is None:
            continue
        key = _scoped_key(key, fact.get("scope"))
        value = _clean(fact.get("value"))
        observations.setdefault(key, []).append((value, _clean(fact.get("unit")) or None, _image_source(fact)))

    specs: dict[str, dict[str, Any]] = {}
    for key, items in observations.items():
        real = [(v, u, s) for v, u, s in items if not is_placeholder(v)]
        sources = [s for _, _, s in items]
        if not real:
            specs[key] = _field(None, sources=sources, status="missing", note="卖家只写了占位(如图/其他),要去图里或问老板")
            continue
        distinct: dict[str, tuple[str, str | None]] = {}
        for value, unit, _ in real:
            distinct.setdefault(_norm_for_compare(f"{value}{unit or ''}"), (value, unit))
        if len(distinct) > 1:
            shown = ";".join(f"{v}{(' ' + u) if u else ''}" for v, u in distinct.values())
            specs[key] = _field(None, sources=sources, status="conflict", note=f"来源说法不一:{shown}")
            continue
        value, unit = next(iter(distinct.values()))
        specs[key] = _field(value, unit=unit, sources=sources)
    return specs, other


# ---------------------------------------------------------------- 变体 / 价格


def build_variants(capture: dict[str, Any]) -> list[dict[str, Any]]:
    images: dict[str, str] = {}
    for prop in capture.get("sku_props") or []:
        for item in prop.get("values") or []:
            if item.get("name") and _host_ok(item.get("image_url")):
                images[_clean(item["name"])] = item["image_url"]
    variants = []
    for sku in capture.get("skus") or []:
        name = _clean(sku.get("name"))
        dims = [sku.get("length_cm"), sku.get("width_cm"), sku.get("height_cm")]
        variants.append(
            {
                "sku_id": sku.get("sku_id"),
                "name_zh": name,
                "name_en": None,
                "cost_price_cny": sku.get("price_cny"),
                "weight_g": sku.get("weight_g") or None,
                "dims_cm": dims if all(isinstance(d, (int, float)) and d > 0 for d in dims) else None,
                "image_url": sku.get("image_url") if _host_ok(sku.get("image_url")) else images.get(name),
            }
        )
    return variants


def _price_summary(capture: dict[str, Any], variants: list[dict[str, Any]]) -> str:
    tiers = [t for t in capture.get("price_tiers") or [] if t.get("price_cny") not in (None, "")]
    if tiers:
        return "、".join(f"≥{t.get('min_qty')}件 ¥{t.get('price_cny')}" for t in tiers)
    prices = sorted({float(v["cost_price_cny"]) for v in variants if isinstance(v.get("cost_price_cny"), (int, float))})
    if prices:
        return f"¥{prices[0]}" if len(prices) == 1 else f"¥{prices[0]}–¥{prices[-1]}"
    return "页面上没拿到进价"


# ---------------------------------------------------------------- AI:英文名 / 包装清单


_WRITER_INSTRUCTION = (
    "You prepare an English product name for a US online store from verified 1688 supplier facts. "
    "Use ONLY the facts given. Never invent specifications, materials, quantities or certifications. "
    "No brand names, no marketing claims (best, premium, #1), no Chinese characters. "
    "product name: at most 75 characters, plain and descriptive, must end on a complete word or phrase. "
    "variant_names: same order and count as the given variant names, short English (max 60 chars each). "
    "package_includes: translate the given package-content facts into short English item lines; empty list if none given. "
    'Reply with JSON: {"name_en": str, "variant_names": [str], "package_includes": [str]}'
)


def _default_writer(payload: dict[str, Any]) -> dict[str, Any] | None:
    from ....db.session import SessionLocal
    from ....services.ai_provider_router import AIExecutionRouter
    from ...k_series.product_knowledge.constants import TARGET_ORGANIZATION_NAME
    from .constants import USAGE_LABEL

    db = SessionLocal()
    try:
        return AIExecutionRouter(db, timeout_seconds=120.0, total_budget_seconds=180.0).execute(
            provider="writer",
            task_type="generate",
            payload={
                "messages": [
                    {"role": "system", "content": _WRITER_INSTRUCTION},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "response_format": {"type": "json_object"},
            },
            org=TARGET_ORGANIZATION_NAME,
            module_id="k.product_knowledge",
            usage_label=USAGE_LABEL,
        )
    finally:
        db.close()


_CJK = re.compile(r"[㐀-鿿]")


def _english_ok(text: Any, limit: int) -> str | None:
    value = _clean(text)
    if not value or _CJK.search(value):
        return None
    if len(value) > limit:
        cut = value[:limit].rsplit(" ", 1)[0].strip(" ,-")
        value = cut or value[:limit]
    return value


# ---------------------------------------------------------------- 类目


def _default_classifier(db: Session, text: str) -> Any:
    from ..yinchengyue.classifier import classify

    return classify(db, text)


# 店里同类产品已经定过的类目是最好的证据(用户亲手批过)。英文名里的这些泛词不拿来找先例。
_PRECEDENT_STOP = {
    "with", "for", "and", "the", "toy", "toys", "kids", "adults", "relief", "stress", "set", "pack", "piece",
    "pieces", "gift", "cute", "mini", "new", "box", "blind", "colorful", "style", "random",
}


def _precedent_category(db: Session, name_en: Any) -> dict[str, Any] | None:
    """店里英文名相近、已经绑了谷歌类目的产品 ≥2 个且类目一致 → 沿用。读不到就返回 None 交给分类器。"""
    text = str(name_en or "")
    tokens = sorted({t.lower() for t in re.findall(r"[A-Za-z]{5,}", text)} - _PRECEDENT_STOP)
    if not tokens or db is None:
        return None
    try:
        from sqlalchemy import func, or_, select

        from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
        from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

        rows = db.execute(
            select(P.google_product_category, func.count(), func.min(P.sku))
            .where(
                P.google_product_category.is_not(None),
                or_(*[P.product_name_en.ilike(f"%{t}%") for t in tokens[:6]]),
            )
            .group_by(P.google_product_category)
            .order_by(func.count().desc()),
            execution_options=SKIP_ORG_DATA_ISOLATION,
        ).all()
    except Exception as exc:  # noqa: BLE001 —— 先例查不到不影响整份档案,退回分类器
        db.rollback()
        logger.warning("dossier precedent lookup failed: %s", exc)
        return None
    if not rows or int(rows[0][1]) < 2 or (len(rows) > 1 and int(rows[1][1]) >= int(rows[0][1])):
        return None
    category_id, count, example_sku = str(rows[0][0]), int(rows[0][1]), rows[0][2]
    name = path = ""
    try:
        from sqlalchemy import text as sql_text

        found = db.execute(
            sql_text("SELECT name, full_path FROM k_category_google WHERE id = :id"), {"id": category_id}
        ).first()
        if found is not None:
            name, path = str(found[0] or ""), str(found[1] or "")
    except Exception:  # noqa: BLE001
        db.rollback()
    value = {"google_category_id": category_id, "name": name, "path": path, "name_zh": "", "confidence": "medium"}
    source = {
        "kind": "precedent",
        "ref": f"店里同类先例 {count} 个(如 {example_sku})",
        "raw": f"英文名相近({', '.join(tokens[:4])})的产品都绑在这个类目",
    }
    return _field(value, sources=[source], note="沿用店里同类产品的类目")


def _category_field(db: Session, text: str, classifier: ClassifierFn) -> dict[str, Any]:
    try:
        verdict = classifier(db, text)
    except Exception as exc:  # noqa: BLE001 —— 类目判不出来不拖垮整份档案,标出来给老板
        logger.warning("dossier category classify failed: %s", exc)
        return _field(None, status="missing", note="类目判定没接通,等老板选")
    chosen = getattr(verdict, "chosen", None)
    status = getattr(verdict, "status", None)
    if status != "ok" or chosen is None:
        # 「没接通」和「真没有合适的」要分开说——之前一律写成后者,把分类器的 bug 藏了起来。
        if status == "offline":
            note = "类目判定这一步没接通(AI 没回话),等老板选"
        else:
            keywords = ", ".join(getattr(getattr(verdict, "hint", None), "keywords_en", None) or [])
            shortlist = getattr(verdict, "shortlist_size", None)
            note = f"没找到合适的谷歌类目(关键词:{keywords or '无'};候选 {shortlist if shortlist is not None else '?'} 个),等老板选"
        return _field(None, status="missing", note=note)
    confidence = str(getattr(verdict, "confidence", "low") or "low")
    value = {
        "google_category_id": str(chosen.id),
        "name": chosen.name,
        "path": " > ".join(getattr(verdict, "path", None) or [chosen.full_path]),
        "name_zh": getattr(chosen, "name_zh", ""),
        "confidence": confidence,
    }
    source = {"kind": "classifier", "ref": "殷承岳的类目判定", "raw": _clean(getattr(verdict, "reason_zh", ""))[:300]}
    if confidence == "low":
        return _field(value, sources=[source], status="needs_owner", note="把握不大,老板确认一下类目")
    return _field(value, sources=[source])


# ---------------------------------------------------------------- 主入口


def build_draft(
    db: Session,
    capture: dict[str, Any],
    image_read: dict[str, Any] | None,
    *,
    writer: WriterFn | None = None,
    classifier: ClassifierFn | None = None,
) -> dict[str, Any]:
    writer = writer or _default_writer
    classifier = classifier or _default_classifier
    facts = list((image_read or {}).get("facts") or [])
    title_zh = _clean(capture.get("title_zh"))

    specs, other = merge_specs(capture, facts)
    variants = build_variants(capture)
    # 批发外箱的装箱信息(「一箱 12 盒 144 个」)不是买家收到的东西,不进包装清单。
    package_facts = [
        f for f in facts if _clean(f.get("field")).casefold() in PACKAGE_FIELDS and f.get("scope") != "carton"
    ]

    fields: dict[str, dict[str, Any]] = {}
    fields["name_zh"] = (
        _field(title_zh, sources=[{"kind": "page_text", "ref": "商品标题", "raw": title_zh[:300]}])
        if title_zh
        else _field(None, status="missing", note="页面上没拿到标题")
    )

    # 一次 writer 调用:英文品名 + 变体英文名 + 包装清单英文。
    writer_payload = {
        "title_zh": title_zh,
        "facts": {k: v["value"] for k, v in specs.items() if v["status"] == "ok"},
        "other_attributes": other[:20],
        "variant_names": [v["name_zh"] for v in variants],
        "package_facts": [f"{_clean(f.get('value'))} {_clean(f.get('raw_text'))}".strip() for f in package_facts],
    }
    written: dict[str, Any] | None = None
    if title_zh:
        try:
            written = writer(writer_payload)
        except Exception as exc:  # noqa: BLE001 —— 英文名写不出来就空着,标 missing,不编
            logger.warning("dossier writer failed: %s", exc)
            written = None
    # 提示词要求 ≤75 字;硬上限放到 120——模型偶尔超一点,宁可长一点也别在半截处截断(10-23 首测出现「…, 12」)。
    name_en = _english_ok((written or {}).get("name_en"), 120)
    writer_source = {"kind": "writer", "ref": "据事实改写(Opus)", "raw": ""}
    fields["name_en"] = (
        _field(name_en, sources=[writer_source]) if name_en
        else _field(None, status="missing", note="英文品名没写出来,等老板或下一轮补")
    )
    names = (written or {}).get("variant_names")
    if isinstance(names, list) and len(names) == len(variants):
        for variant, name in zip(variants, names, strict=True):
            variant["name_en"] = _english_ok(name, 60)

    is_variable = len(variants) > 1
    fields["product_type"] = _field(
        "variable_product" if is_variable else "simple_product",
        sources=[{"kind": "page_json", "ref": "SKU 列表", "raw": f"{len(variants)} 个 SKU"}],
    )

    moq = capture.get("moq")
    fields["moq"] = _field(moq, unit=_clean(capture.get("unit")) or None,
                           sources=[{"kind": "page_json", "ref": "起批量", "raw": str(moq)}]) if moq else _field(None, status="missing")
    fields["retail_price"] = _field(
        None, unit="USD", status="needs_owner",
        note=f"1688 只有进价({_price_summary(capture, variants)}),美国售价请老板定",
    )

    package_en = [item for item in ((written or {}).get("package_includes") or []) if _english_ok(item, 120)]
    if package_en and package_facts:
        fields["package_includes"] = _field([_english_ok(i, 120) for i in package_en],
                                            sources=[_image_source(f) for f in package_facts])
    else:
        fields["package_includes"] = _field(None, status="missing", note="页面和详情图里都没找到包装清单")

    category_text = " ".join(
        part for part in [title_zh, *(f"{SPEC_LABELS_ZH.get(k, k)} {v['value']}" for k, v in specs.items() if v["status"] == "ok")] if part
    )
    if not title_zh:
        fields["category"] = _field(None, status="missing")
    else:
        precedent = _precedent_category(db, (fields.get("name_en") or {}).get("value"))
        fields["category"] = precedent or _category_field(db, category_text, classifier)

    reference_images: list[str] = []
    for url in [*(capture.get("gallery_images") or [])[:3], *(v["image_url"] for v in variants if v.get("image_url"))]:
        if _host_ok(url) and url not in reference_images:
            reference_images.append(url)
    reference_images = reference_images[:8]

    flagged: list[dict[str, str]] = []
    for name, item in fields.items():
        if item["status"] != "ok":
            flagged.append({"path": name, "status": item["status"], "note": item["note"]})
    for key, item in specs.items():
        if item["status"] != "ok":
            flagged.append({"path": f"specs.{key}", "status": item["status"], "note": item["note"]})

    conflicts = sum(1 for f in flagged if f["status"] == "conflict")
    missing = sum(1 for f in flagged if f["status"] == "missing")
    owner = sum(1 for f in flagged if f["status"] == "needs_owner")
    summary = (
        f"{title_zh[:30] or '这个品'}:{len(variants)} 个 SKU,规格 {len(specs)} 项;"
        f"标红 {len(flagged)} 项(说法不一 {conflicts}、没找到 {missing}、要老板定 {owner})。"
    )
    return {
        "version": DRAFT_VERSION,
        "offer_id": capture.get("offer_id"),
        "source_url": capture.get("url"),
        "fields": fields,
        "specs": specs,
        "variants": variants,
        "price_tiers": capture.get("price_tiers") or [],
        "reference_images": reference_images,
        "other_attributes": other,
        "supplier": capture.get("supplier") or {},
        "image_read": {
            "segments_seen": (image_read or {}).get("segments_seen"),
            "segments_read": (image_read or {}).get("segments_read"),
            "stopped_reason": (image_read or {}).get("stopped_reason"),
        },
        "flagged": flagged,
        "flagged_count": len(flagged),
        "summary_zh": summary,
    }
