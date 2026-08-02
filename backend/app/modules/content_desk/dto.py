"""统一 article DTO —— 两台引擎在浮窗里长成同一个样子。

三条硬规矩,每条都对应一个已经发生过的问题:

1. **``analysis`` 七个键一个不砍。** SEO 前端现在只渲染 ``risks``,把
   翻译 / GEO 作用 / 为什么这么写 / 优点 / 模型 全藏了 —— 类型定义里明明都有。
   显示层自己挑字段就会这样,所以归一化层原样透传,缺就给 ``null``,
   **绝不省略键**(省略和"值为空"在前端是两种代码路径)。

2. **``body`` 恒有两个键。** SEO 没有 ``answer_blocks``,给 ``[]`` 而不是不给。
   前端只写一套渲染。

3. **``wp_status`` / ``published_url`` / ``wp_post_id`` 两边都出。**
   ``geo_series/content/service.py`` 的 serialize_item 漏了这三列,而前端
   ``GeoItem`` 类型**声明了**它们 —— 类型骗人,后端从没发过。内容台直接读
   ORM 列,不改 geo service(零回归面)。

字段缺失一律给 ``null``,不省略键。
"""

from __future__ import annotations

from typing import Any

from .sources import ContentSource

# DeepSeek 解读的七个键。**这个元组就是契约**——测试拿它断言后端不砍键、
# 前端 AnalysisPanel 每一项都渲染。
ANALYSIS_KEYS: tuple[str, ...] = (
    "translation",
    "geo_role",
    "why_written_this_way",
    "strengths",
    "risks",
    "model",
    "skill_version",
)

# 品牌审查的四族 finding + 元信息。同样恒存在。
AUDIT_KEYS: tuple[str, ...] = (
    "clean",
    "site_brand",
    "brand_violations",
    "cjk_surfaces",
    "ungrounded_numbers",
    "bad_derivations",
    "ignored_findings",
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def normalize_analysis(raw: Any) -> dict[str, Any] | None:
    """七个键补齐。整个 analysis 为空时返回 ``None``——前端据此显示
    「还没解读」+ 一个重跑按钮,而不是显示七个空框。"""
    data = _dict(raw)
    if not data:
        return None
    return {key: data.get(key) for key in ANALYSIS_KEYS}


def normalize_audit(raw: Any) -> dict[str, Any]:
    """四族 finding 补齐。``clean`` 缺失一律当 ``False``(fail-closed):
    没有审查记录不等于审查通过。"""
    data = _dict(raw)
    return {
        "clean": bool(data.get("clean")) if "clean" in data else False,
        "site_brand": data.get("site_brand"),
        "brand_violations": _list(data.get("brand_violations")),
        "cjk_surfaces": _list(data.get("cjk_surfaces")),
        "ungrounded_numbers": _list(data.get("ungrounded_numbers")),
        "bad_derivations": _list(data.get("bad_derivations")),
        "ignored_findings": _list(data.get("ignored_findings")),
        "audited": bool(data),
    }


def normalize_body(raw: Any) -> dict[str, list[Any]]:
    """恒返回两个键。"""
    data = _dict(raw)
    return {
        "sections": _list(data.get("sections")),
        "answer_blocks": _list(data.get("answer_blocks")),
    }


def item_kind(item: Any, source: ContentSource) -> str:
    """体裁。GEO 叫 ``item_type``、SEO 叫 ``item_kind`` —— 列名从来源表里取,
    不写 ``getattr(item, "item_type", None) or getattr(...)`` 那种两头猜。"""
    return str(getattr(item, source.kind_column, "") or "")


def to_article(
    item: Any,
    *,
    source: ContentSource,
    parent: Any = None,
    product_labels: dict[str, str] | None = None,
    permissions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """一篇文章在内容台眼里的完整样子。"""
    kind = item_kind(item, source)
    extra: dict[str, Any] = {}
    for out_key, column in source.extra_columns:
        value = getattr(item, column, None)
        extra[out_key] = _iso(value) if hasattr(value, "isoformat") else value
    if source.resolves_product_labels:
        labels = product_labels or {}
        extra["source_product_labels"] = [
            labels.get(str(pid), str(pid))
            for pid in _list(getattr(item, "source_product_ids_json", None))
        ]

    return {
        "source": source.key,
        "source_label": source.label,
        "id": str(item.id),
        "kind": kind,
        "kind_label": source.kind_labels.get(kind, kind),
        "title": str(item.title or ""),
        "parent_id": str(getattr(item, source.parent_fk, "") or "") or None,
        "parent_label": (
            str(getattr(parent, source.parent_label_column, "") or "")
            if parent is not None
            else None
        ),
        "body": normalize_body(getattr(item, "body_json", None)),
        # 键名叫 seo_meta 不叫 seo:它是 SEO 元数据(标题/描述/slug),
        # 两个引擎的文章都有。和同一对象里的 "source": "seo" 挤在一起,
        # 看的人和 grep 都会认错。
        "seo_meta": _dict(getattr(item, "seo_json", None)),
        "analysis": normalize_analysis(getattr(item, "analysis_json", None)),
        "brand_audit": normalize_audit(getattr(item, "brand_audit_json", None)),
        "revision": _dict(getattr(item, "revision_json", None)) or None,
        "review_status": getattr(item, "review_status", None),
        "generation_status": getattr(item, "generation_status", None),
        # 三列 geo serialize_item 漏掉的,这里两边都出。
        "wp_post_id": getattr(item, "wp_post_id", None),
        "wp_status": getattr(item, "wp_status", None),
        "published_url": getattr(item, "published_url", None),
        "published_at": _iso(getattr(item, "published_at", None)),
        "created_at": _iso(getattr(item, "created_at", None)),
        "skill_version": getattr(item, "skill_version", None),
        "provider": getattr(item, "provider", None),
        "revise_mode": source.revise_mode,
        "extra": extra,
        # 前端据此置灰按钮并写明原因，而不是让人点下去吃 403。
        "permissions": permissions
        or {"can_review": None, "can_revise": None, "can_publish": None},
    }


__all__ = [
    "ANALYSIS_KEYS",
    "AUDIT_KEYS",
    "item_kind",
    "normalize_analysis",
    "normalize_audit",
    "normalize_body",
    "to_article",
]
