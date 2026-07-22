"""运营者对作图方案的手动编辑:单张专属参考图、新增图片、加标注。

2026-07-22 用户拍板的三件套:
1. 单张重做可贴专属参考图(落地为 media asset,渲染任务经
   ``reference_asset_id`` 优先取用——复用既有渲染管线,零新管道);
2. 在 AI 方案之外新增图片,建图时手选去处(轮播 gallery / 描述 description),
   SEO 四件套(title/alt/caption/description)一个不能少:DeepSeek 生成,
   任何失败落回确定性模板,绝不出空字段;
3. 「加标注」:从已核实规格里挑字段,按预设锚位生成 v1 标注层契约,
   由渲染管线的确定性合成器把真实数据画上图(亚马逊风信息图的合规姿势)。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ....models.user import User
from .info_overlay import (
    MAX_OVERLAY_ITEMS,
    OVERLAY_FIELD_LABELS,
    OVERLAY_SCHEMA_VERSION,
    OVERLAY_SOURCE_FIELDS,
    normalize_overlay_contract,
)
from .models import KProductKnowledgeMediaAsset, KProductKnowledgeProduct

logger = logging.getLogger(__name__)

_SEO_PROMPT_TIMEOUT_SECONDS = 40
# 一张图最多勾 4 条标注:再多画面就挤了(合成器上限 12 是硬约束,这里是审美约束)
MAX_OPERATOR_OVERLAY_FIELDS = 4


def store_operator_reference_asset(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    reference_image_url: str,
    user: User | None,
) -> KProductKnowledgeMediaAsset:
    """把运营者贴的参考图链接落成本地 reference 媒资(不改产品主参考图)。

    走 F 系列守卫下载(域名白名单/防盗链头/磁盘缓存),渲染读本地字节。
    """

    from ...f_series.enrichment.images import get_candidate_image
    from .image_render_jobs import store_reference_image_asset

    contents, mime_type = get_candidate_image(
        f"k-operator-ref-{product.id}", reference_image_url, "full"
    )
    return store_reference_image_asset(
        db,
        product=product,
        contents=contents,
        mime_type=mime_type,
        source_url=reference_image_url,
        user=user,
    )


def _template_prompt_and_seo(
    product: KProductKnowledgeProduct, scene: str
) -> dict[str, str]:
    """确定性兜底:AI 不可用时的完整 SEO 四件套 + 英文渲染提示词。"""

    name = (product.product_name_en or product.primary_keyword or "product").strip()
    keyword = (product.primary_keyword or name).strip()
    scene_text = scene.strip()
    return {
        "prompt": (
            f"Photorealistic ecommerce product photo of {name}. Scene: "
            f"{scene_text}. Natural realistic environment, sharp focus on the "
            "product, no text or logos in the image."
        ),
        "title": f"{name} – {keyword}"[:180],
        "alt": f"{name} – {scene_text}"[:180],
        "caption": scene_text[:160],
        "description": f"{name}: {scene_text}"[:300],
    }


def operator_image_prompt_and_seo(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    scene: str,
) -> dict[str, str]:
    """运营者的一句话画面 → 英文渲染提示词 + SEO 四件套(铁律:字段不缺)。"""

    fallback = _template_prompt_and_seo(product, scene)
    try:
        from ...w_series.logistics import _target_org_id
        from r_system_v2.core.secret_manager import SecretManager

        org_id = _target_org_id(db)
        if not org_id:
            return fallback
        key = SecretManager(db_session=db).get_key("deepseek", org_id)
        db.rollback()
        response = httpx.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "You write ecommerce image prompts and WordPress media "
                            "SEO. Product name: "
                            f"{product.product_name_en or ''}. Main keyword: "
                            f"{product.primary_keyword or ''}. The operator wants an "
                            f"extra product image showing: {scene}\n"
                            "Return STRICT JSON with keys prompt (English photo "
                            "prompt, photorealistic, no text in image), title, alt, "
                            "caption, description (English media SEO, keyword-aware, "
                            "non-empty each)."
                        ),
                    }
                ],
            },
            timeout=_SEO_PROMPT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        parsed = json.loads(response.json()["choices"][0]["message"]["content"])
        output = dict(fallback)
        for field in ("prompt", "title", "alt", "caption", "description"):
            value = str(parsed.get(field) or "").strip()
            if value:
                output[field] = value[:1000 if field == "prompt" else 300]
        return output
    except Exception:  # noqa: BLE001 - SEO 兜底模板保证四件套永不缺
        logger.exception(
            "operator image seo generation failed product=%s", product.id
        )
        return fallback


def build_operator_brief_image(
    *,
    position: int,
    placement: str,
    scene: str,
    prompt_and_seo: dict[str, str],
    reference_asset_id: str | None,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "position": position,
        "role": "proof_scene",
        "placement": placement,
        "prompt": prompt_and_seo["prompt"],
        "scene": scene,
        "proof_intent": scene,
        "title": prompt_and_seo["title"],
        "alt": prompt_and_seo["alt"],
        "caption": prompt_and_seo["caption"],
        "description": prompt_and_seo["description"],
        "operator_added": True,
    }
    if reference_asset_id:
        spec["reference_asset_id"] = reference_asset_id
    return spec


def available_overlay_fields(
    db: Session, product: KProductKnowledgeProduct
) -> list[dict[str, str]]:
    """当前产品可用于标注的已核实规格字段(值不存在的字段不给选)。"""

    from .evidence_guard import canonical_package_includes
    from .router import _structured_spec_evidence_snapshot

    structured_specs = dict(product.structured_specs_json or {})
    package_includes = canonical_package_includes(
        getattr(product, "package_includes_json", None),
        product.structured_specs_json,
    )
    if package_includes:
        structured_specs["package_includes"] = package_includes
    fields: list[dict[str, str]] = []
    for field in OVERLAY_SOURCE_FIELDS:
        snapshot = _structured_spec_evidence_snapshot(structured_specs, field)
        if snapshot is None:
            continue
        value_text = str(snapshot.get("value_text") or "").strip()
        if not value_text:
            continue
        fields.append(
            {
                "field": field,
                "label": OVERLAY_FIELD_LABELS.get(field, field),
                "value_text": value_text,
            }
        )
    # 运营者在「规格(事实)」手填的附加规格同样可标注(additional_specs.<key>)
    additional = structured_specs.get("additional_specs")
    if isinstance(additional, list):
        for item in additional:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            ref = f"additional_specs.{key}"
            if ref not in OVERLAY_SOURCE_FIELDS:
                continue
            snapshot = _structured_spec_evidence_snapshot(structured_specs, ref)
            if snapshot is None:
                continue
            value_text = str(snapshot.get("value_text") or "").strip()
            if not value_text:
                continue
            label = str(item.get("label") or key).strip() or key
            fields.append(
                {"field": ref, "label": label, "value_text": value_text}
            )
    return fields


def build_preset_overlay(source_fields: list[str]) -> dict[str, Any]:
    """按预设锚位为选中的规格字段生成 v1 标注层(经契约校验后返回)。

    锚位布局:标注文字沿右侧竖排,引线指向画面中部产品区;合成器负责
    把真实规格值画上去——AI 永远不碰图上的文字。
    """

    cleaned = [str(f or "").strip() for f in source_fields]
    cleaned = [f for f in cleaned if f]
    if not cleaned:
        raise ValueError("至少选择一个标注字段")
    if len(cleaned) > MAX_OPERATOR_OVERLAY_FIELDS:
        raise ValueError(f"一张图最多标注 {MAX_OPERATOR_OVERLAY_FIELDS} 条")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("标注字段重复")
    unknown = [f for f in cleaned if f not in OVERLAY_SOURCE_FIELDS]
    if unknown:
        raise ValueError(f"不支持的标注字段: {', '.join(unknown)}")
    if len(cleaned) > MAX_OVERLAY_ITEMS:  # pragma: no cover - 双保险
        raise ValueError("标注条数超出合成器上限")

    count = len(cleaned)
    items: list[dict[str, Any]] = []
    for index, field in enumerate(cleaned):
        # 文字锚:右侧竖排均匀分布;引线锚:画面中部产品区,随序号微移
        vertical_span = 0.55
        y_start = 0.5 - vertical_span / 2 + vertical_span / (count + 1)
        text_y = y_start + index * (vertical_span / max(count, 1))
        items.append(
            {
                "type": "callout",
                "source_field": field,
                "text_anchor": {"x": 0.82, "y": round(min(max(text_y, 0.08), 0.92), 3)},
                "anchor": {
                    "x": round(0.5 + (index % 2) * 0.06 - 0.03, 3),
                    "y": round(min(max(0.35 + index * 0.1, 0.15), 0.85), 3),
                },
                "leader_direction": "auto",
            }
        )
    overlay = {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "role": "feature_callout",
        "items": items,
    }
    normalized = normalize_overlay_contract(overlay)
    if normalized is None:  # pragma: no cover - 非空 items 不会返回 None
        raise ValueError("标注层生成失败")
    return normalized
