"""品牌硬门（brand guard）：独立站页面绝不允许出现第三方品牌名/logo。

死命令：这个独立站所有产品的对外品牌永远只有一个 —— ``SITE_BRAND``
（Barong Yekhna）。第三方品牌既不许进文字面（标题/文案/SEO/图片四字段/
overlay），也不许留在成品图像素里（产品实拍上的 logo 必须在渲染时抹掉）。

防线分四层，这个模块承担第 3 层（独立 AI 审查）+ 全链共享的工具：
1. 源头：R→K 搬运剥品牌、落 ``detected_brand_terms`` 黑名单（r_to_k_transfer）。
2. 生成：文案/作图指令红线带黑名单（prompt_skills / workflow_engine）。
3. 审查（本模块）：文本面 = 黑名单精确匹配 + gpt-5.6-luna 语义识别；
   图像面 = 每张成品图过视觉模型找品牌标识。fail-closed：任何一步
   出错都算未通过，宁可拦住也不放行。
4. 门禁：P 上架要求 audit 存在 + clean + 内容指纹一致（p_series assemble）。

审查结果落 ``product.brand_audit_json``::

    {
      "clean": bool,
      "fingerprint": "<sha256 of everything audited>",
      "audited_at": iso8601,
      "attempt": int,                # 自动重渲染闭环计数
      "text_violations": [{"surface", "term", "evidence"}],
      "image_violations": [{"asset_id", "position", "finding"}],
      "errors": ["<audit step that failed>"],   # 非空 => clean 必为 False
    }
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.user import User
from ....services.module_execution_gate import require_module_execution_ready
from .constants import MODULE_KEY
from .models import KProductKnowledgeMediaAsset, KProductKnowledgeProduct

_LOGGER = logging.getLogger("k-brand-guard")

# 死命令：独立站唯一对外品牌。所有 json_ld / 上架包 brand 由代码强制写死，
# 不依赖 AI 自觉。
SITE_BRAND = "Barong Yekhna"

# 自有品牌及其常见写法 —— 审查白名单（出现它们不算违规）。
SITE_BRAND_WHITELIST = {
    "barong yekhna",
    "barongyekhna",
    "barong",
    "yekhna",
}

_AUDIT_TIMEOUT_SECONDS = 150.0
_VISION_DETAIL_MAX_SIDE = 1280  # 用 preview 尺寸足够认 logo


# --- 文本面收集 + 指纹 -------------------------------------------------------

def _walk_strings(value: Any, path: str, out: list[tuple[str, str]]) -> None:
    if isinstance(value, str):
        if value.strip():
            out.append((path, value))
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk_strings(item, f"{path}.{key}", out)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_strings(item, f"{path}[{index}]", out)


def _render_assets(
    db: Session,
    product: KProductKnowledgeProduct,
) -> list[KProductKnowledgeMediaAsset]:
    rows = db.scalars(
        select(KProductKnowledgeMediaAsset).where(
            KProductKnowledgeMediaAsset.product_id == product.id,
            KProductKnowledgeMediaAsset.status == "available",
            KProductKnowledgeMediaAsset.asset_type == "image",
        )
    ).all()
    out = []
    for row in rows:
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if meta.get("render_pipeline") == "k_auto_render":
            out.append(row)
    out.sort(key=lambda row: int((row.metadata_json or {}).get("position") or 0))
    return out


def collect_text_surfaces(
    db: Session,
    product: KProductKnowledgeProduct,
) -> list[tuple[str, str]]:
    """上架会出现在站点上的全部文字面（surface 标签 -> 文本）。"""
    surfaces: list[tuple[str, str]] = []
    for field in ("product_name_en", "primary_keyword"):
        value = getattr(product, field, None)
        if isinstance(value, str) and value.strip():
            surfaces.append((field, value))
    if isinstance(product.marketing_copy_json, dict):
        _walk_strings(product.marketing_copy_json, "copy", surfaces)
    if isinstance(product.image_instruction_json, dict):
        # 只审会“上页面/上图”的字段；prompt 是给模型看的，交给图像审查兜底
        for index, spec in enumerate(
            product.image_instruction_json.get("images") or []
        ):
            if not isinstance(spec, dict):
                continue
            for key in ("title", "alt", "caption", "description", "overlay_text"):
                value = spec.get(key)
                if isinstance(value, str) and value.strip():
                    surfaces.append((f"image_brief[{index}].{key}", value))
            if isinstance(spec.get("overlay"), dict):
                _walk_strings(
                    spec["overlay"],
                    f"image_brief[{index}].overlay",
                    surfaces,
                )
    for asset in _render_assets(db, product):
        meta = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
        position = meta.get("position")
        for key in ("title", "alt", "caption", "description", "overlay_text"):
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                surfaces.append((f"render_image[{position}].{key}", value))
        if isinstance(meta.get("overlay"), dict):
            _walk_strings(
                meta["overlay"],
                f"render_image[{position}].overlay",
                surfaces,
            )
    return surfaces


def brand_fingerprint(db: Session, product: KProductKnowledgeProduct) -> str:
    """当前“会上站的内容”的指纹。内容一变指纹就变 -> 旧审查作废。"""
    surfaces = collect_text_surfaces(db, product)
    image_parts = [
        f"{row.id}:{(row.metadata_json or {}).get('content_sha256', '')}"
        for row in _render_assets(db, product)
    ]
    payload = json.dumps(
        {"text": surfaces, "images": image_parts},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- 生成侧红线工具 -----------------------------------------------------------

# 渲染 prompt 追加块：产品表面的文字/图案标识一律无差别清除 —— 不判断
# 是不是品牌（判断会漏），只要是印在产品上的文字就删。保形状/颜色/结构。
BRAND_REMOVAL_PROMPT_BLOCK = (
    "\n\nTEXT & LOGO REMOVAL (MANDATORY, do not skip): remove ALL text, "
    "lettering, wordmarks, logos, symbols, and printed labels from the product "
    "surface itself — every character, no matter what it says. Replace each "
    "removed mark with a clean blank surface matching the product's material, "
    "color, and texture. Do NOT alter the product's shape, structure, "
    "proportions, or colors in any other way. Packaging, tags, and background "
    "props must also carry no readable text or logos. No text is allowed in "
    "the model output; verified information overlays are added server-side."
)


def strip_brand_terms(text_value: str, terms: list[str]) -> str:
    """从文本里确定性剥除品牌词（大小写不敏感，压缩多余空格）。"""
    cleaned = text_value
    for term in terms:
        if len(term.strip()) < 2:
            continue
        cleaned = re.sub(re.escape(term), " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" -–—·,")


def sanitize_snapshot_for_generation(
    snapshot: dict[str, Any],
    product: KProductKnowledgeProduct,
) -> dict[str, Any]:
    """喂给文案/作图 AI 之前给产品快照消毒：AI 看不到第三方品牌就写不出来。"""
    terms = _normalized_terms(product)
    cleaned: dict[str, Any] = {}
    for key, value in snapshot.items():
        if key in ("brand_name", "manufacturer"):
            cleaned[key] = None
            continue
        if isinstance(value, str) and terms:
            cleaned[key] = strip_brand_terms(value, terms)
        else:
            cleaned[key] = value
    return cleaned


# --- 第 1 道：黑名单精确匹配（确定性，零漏判） ------------------------------

def _normalized_terms(product: KProductKnowledgeProduct) -> list[str]:
    terms = product.detected_brand_terms
    if not isinstance(terms, list):
        return []
    out = []
    for term in terms:
        cleaned = str(term or "").strip()
        if len(cleaned) >= 2 and cleaned.lower() not in SITE_BRAND_WHITELIST:
            out.append(cleaned)
    return out


def normalized_brand_terms(product: KProductKnowledgeProduct) -> list[str]:
    """公开版黑名单读取（生成红线 / 门禁 / 审查共用）。"""
    return _normalized_terms(product)


def blacklist_violations(
    surfaces: list[tuple[str, str]],
    terms: list[str],
) -> list[dict[str, Any]]:
    violations = []
    for term in terms:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        for surface, text_value in surfaces:
            match = pattern.search(text_value)
            if match:
                start = max(0, match.start() - 40)
                violations.append(
                    {
                        "surface": surface,
                        "term": term,
                        "evidence": text_value[start : match.end() + 40],
                    }
                )
    return violations


# --- AI 调用（gpt-5.6-luna 文本审 + 视觉审图，httpx 直连 4sapi） ------------------

def _resolve_chat_key(db: Session, user: User | None):
    context = require_module_execution_ready(
        db,
        module_id=MODULE_KEY,
        user=user,
        request=None,
        key_requirements={"brand_audit": "chatgpt"},
    )
    return context.key_for_step("brand_audit")


# 与 ai_provider_router.MODEL_FALLBACKS 同思路:4sapi「OpenAI优质」分组
# 会整组掉线(503 No available channel),低档通道仍在。审查是 fail-closed
# 硬门,通道故障时按序降级,恢复后自动回到首选模型。
_AUDIT_MODEL_CANDIDATES = ("gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.2-high")


def _chat_completion(key, messages: list[dict[str, Any]]) -> str:
    url = key.url.rstrip("/")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    url = f"{url}/chat/completions"
    last_error: Exception | None = None
    with httpx.Client(timeout=_AUDIT_TIMEOUT_SECONDS) as client:
        for model in _AUDIT_MODEL_CANDIDATES:
            response = client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    key.header_name: key.header_value,
                },
                json={"model": model, "messages": messages},
            )
            if response.status_code >= 500:
                # 503=通道下线、504=上游超时——都是代理侧故障,换模型再试
                last_error = httpx.HTTPStatusError(
                    f"upstream {response.status_code} for {model}",
                    request=response.request,
                    response=response,
                )
                continue
            response.raise_for_status()
            payload = response.json()
            return str(payload["choices"][0]["message"]["content"] or "")
    raise last_error or RuntimeError("brand audit: no AI channel available")


def _json_from_reply(reply: str) -> dict[str, Any]:
    text_value = reply.strip()
    if text_value.startswith("```"):
        text_value = re.sub(r"^```[a-z]*\s*|\s*```$", "", text_value, flags=re.S)
    start = text_value.find("{")
    end = text_value.rfind("}")
    if start >= 0 and end > start:
        text_value = text_value[start : end + 1]
    return json.loads(text_value)


_TEXT_AUDIT_INSTRUCTION = (
    "You are a trademark-compliance auditor for an independent e-commerce site. "
    f'The site sells everything under its OWN brand "{SITE_BRAND}" only. '
    "Below are text surfaces that will appear on a live product page. Find EVERY "
    "occurrence of a third-party brand name, trademark, manufacturer name, or "
    "model-series name that implies a brand (e.g. 'ididi', 'Lululemon', "
    "'Gruper'). Generic product words (yoga mat, stainless steel) are fine. "
    f'"{SITE_BRAND}" and its variants are the site\'s own brand and are ALLOWED. '
    "Return ONLY JSON: {\"violations\": [{\"surface\": \"<surface id>\", "
    "\"term\": \"<the brand term>\", \"evidence\": \"<short quote>\"}]} — empty "
    "array if fully clean. Be strict: when a token looks like a brand, flag it."
)


def ai_text_violations(
    key,
    surfaces: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    if not surfaces:
        return []
    listing = "\n".join(
        f"[{surface}] {text_value}" for surface, text_value in surfaces
    )
    reply = _chat_completion(
        key,
        [
            {"role": "system", "content": _TEXT_AUDIT_INSTRUCTION},
            {"role": "user", "content": listing[:60000]},
        ],
    )
    parsed = _json_from_reply(reply)
    violations = parsed.get("violations")
    out = []
    for item in violations if isinstance(violations, list) else []:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        if term.lower() in SITE_BRAND_WHITELIST:
            continue
        out.append(
            {
                "surface": str(item.get("surface") or "?"),
                "term": term or "?",
                "evidence": str(item.get("evidence") or "")[:200],
            }
        )
    return out


_IMAGE_AUDIT_INSTRUCTION = (
    "You are a publish-readiness image auditor for an e-commerce product page. "
    "Inspect this image and flag it if EITHER check fails:\n"
    "1. BRAND: any visible brand name, logo, trademark, wordmark, or "
    "brand-identifying text ANYWHERE (product, packaging, labels, overlays, "
    f'background props). Generic descriptive overlay text is fine. "{SITE_BRAND}" '
    "is the site's own brand and is allowed.\n"
    "2. UNFINISHED DESIGN: empty text boxes, blank label rows, placeholder "
    "frames waiting for text, icons with no caption beside them, garbled or "
    "misspelled overlay text, or any obviously incomplete infographic element — "
    "this image goes live exactly as-is, so unfinished design is a defect.\n"
    "Return ONLY JSON: "
    '{"flagged": true|false, "findings": ["<what and where>"]}'
)


def ai_image_violation(key, image_bytes: bytes, mime_type: str) -> list[str]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    reply = _chat_completion(
        key,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _IMAGE_AUDIT_INSTRUCTION},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{encoded}"
                        },
                    },
                ],
            }
        ],
    )
    parsed = _json_from_reply(reply)
    if not (parsed.get("flagged") or parsed.get("has_brand")):
        return []
    findings = parsed.get("findings")
    out = [str(f)[:300] for f in findings if str(f).strip()] if isinstance(
        findings, list
    ) else []
    return out or ["image flagged (no detail returned)"]


_GEOMETRY_AUDIT_INSTRUCTION = (
    "You are a product-fidelity auditor for an e-commerce catalog. The FIRST "
    "image is the TRUE reference photo of the product. The SECOND image is an "
    "AI-rendered marketing image of the SAME product that will be published only "
    "if the product's physical form was preserved. Compare ONLY the product "
    "itself and flag the rendered image if the product's SHAPE, PROPORTIONS, "
    "body or head/nozzle geometry, or the layout/number/position of its buttons, "
    "ports, screen/display, hose, or controls is CLEARLY different from the "
    "reference — i.e. the AI redrew, distorted, merged, added or removed physical "
    "product parts. IGNORE every difference that is NOT the product's physical "
    "form: colour and finish (colour variants are intentional), background, "
    "scene, props, people, lighting, angle, framing, zoom, and whether water is "
    "spraying. Only flag clear, obvious product distortion; when the product "
    "looks like the same physical object, do NOT flag. "
    'Return ONLY JSON: {"flagged": true|false, "findings": ["<what differs>"]}'
)


def ai_geometry_violation(
    key,
    reference_bytes: bytes,
    reference_mime: str,
    rendered_bytes: bytes,
    rendered_mime: str,
) -> list[str]:
    """Vision compare rendered image vs reference; return product-distortion
    findings (empty = faithful). Sends reference first, rendered second."""
    ref_b64 = base64.b64encode(reference_bytes).decode("ascii")
    ren_b64 = base64.b64encode(rendered_bytes).decode("ascii")
    reply = _chat_completion(
        key,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _GEOMETRY_AUDIT_INSTRUCTION},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{reference_mime};base64,{ref_b64}"
                        },
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{rendered_mime};base64,{ren_b64}"
                        },
                    },
                ],
            }
        ],
    )
    parsed = _json_from_reply(reply)
    if not parsed.get("flagged"):
        return []
    findings = parsed.get("findings")
    out = (
        [str(f)[:300] for f in findings if str(f).strip()]
        if isinstance(findings, list)
        else []
    )
    return out or ["product geometry differs from the reference photo"]


def _reference_previews(
    db: Session,
    product: KProductKnowledgeProduct,
) -> tuple[dict[str, tuple[bytes, str]], tuple[bytes, str] | None]:
    """Load reference product photos for the geometry check: a {variant_color:
    (bytes, mime)} map plus a default. Reference assets are the original supplier
    photos (asset_role='reference'), never pipeline renders."""
    rows = db.scalars(
        select(KProductKnowledgeMediaAsset).where(
            KProductKnowledgeMediaAsset.product_id == product.id,
            KProductKnowledgeMediaAsset.status == "available",
            KProductKnowledgeMediaAsset.asset_type == "image",
            KProductKnowledgeMediaAsset.asset_role == "reference",
        )
    ).all()
    by_color: dict[str, tuple[bytes, str]] = {}
    default: tuple[bytes, str] | None = None
    for row in rows:
        loaded = _asset_preview_bytes(row)
        if loaded is None:
            continue
        if default is None:
            default = loaded
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        color = str(meta.get("variant_color") or "").strip().lower()
        if color:
            by_color[color] = loaded
    return by_color, default


def _asset_preview_bytes(
    asset: KProductKnowledgeMediaAsset,
) -> tuple[bytes, str] | None:
    """优先用 preview 派生图（小、省 token），退回原图。"""
    from pathlib import Path

    root = Path(os.getenv("K_PRODUCT_MEDIA_STORAGE_DIR", "/var/lib/barong/k-media"))
    meta = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    preview_key = meta.get("preview_object_key")
    if isinstance(preview_key, str) and preview_key:
        path = root / preview_key
        if path.is_file():
            return path.read_bytes(), "image/webp"
    if asset.object_key:
        path = root / asset.object_key
        if path.is_file():
            return path.read_bytes(), asset.mime_type or "image/png"
    return None


# --- 主入口 -------------------------------------------------------------------

def run_brand_audit(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    user: User | None,
    attempt: int = 0,
) -> dict[str, Any]:
    """跑一次完整审查并把结果写到 product.brand_audit_json（调用方 commit）。

    fail-closed：AI 调用失败会记进 errors 且 clean=False，门禁照样拦。
    """
    surfaces = collect_text_surfaces(db, product)
    terms = _normalized_terms(product)
    fingerprint = brand_fingerprint(db, product)

    text_violations = blacklist_violations(surfaces, terms)
    image_violations: list[dict[str, Any]] = []
    errors: list[str] = []

    # 图像字节先全部载入内存 —— 后面的 AI 循环要几分钟，期间绝不能持有
    # 打开的 DB 事务（idle-in-transaction 8s 就会被杀）。
    images_to_audit: list[tuple[str, Any, str, bytes, str]] = []
    for asset in _render_assets(db, product):
        meta = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
        position = meta.get("position")
        loaded = _asset_preview_bytes(asset)
        if loaded is None:
            errors.append(f"image_load[{position}]: file missing")
            continue
        contents, mime = loaded
        variant_color = str(meta.get("variant_color") or "").strip().lower()
        images_to_audit.append((str(asset.id), position, variant_color, contents, mime))

    # 产品几何保真检查用的参考图(原厂图,非渲染图);缺失=跳过几何检查(fail-open)。
    geometry_audit_on = os.getenv("K_GEOMETRY_AUDIT_ENABLED", "1").strip() not in (
        "0",
        "false",
        "off",
        "",
    )
    reference_by_color: dict[str, tuple[bytes, str]] = {}
    reference_default: tuple[bytes, str] | None = None
    if geometry_audit_on and images_to_audit:
        try:
            reference_by_color, reference_default = _reference_previews(db, product)
        except Exception as exc:  # noqa: BLE001 - geometry check is best-effort
            _LOGGER.warning("reference load for geometry audit failed %s: %s",
                            product.id, exc)

    key = None
    try:
        key = _resolve_chat_key(db, user)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"key_resolution: {exc}")

    # 长 AI 调用前释放读事务；循环期间不碰 db。
    db.commit()

    if key is not None:
        try:
            text_violations.extend(ai_text_violations(key, surfaces))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("text audit failed for %s: %s", product.id, exc)
            errors.append(f"text_audit: {str(exc)[:200]}")

        for asset_id, position, variant_color, contents, mime in images_to_audit:
            # 1) 品牌 + 半成品审查(fail-closed:失败记 errors 挡门)。
            try:
                findings = ai_image_violation(key, contents, mime)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "image audit failed for %s pos %s: %s",
                    product.id,
                    position,
                    exc,
                )
                errors.append(f"image_audit[{position}]: {str(exc)[:200]}")
                continue
            if findings:
                image_violations.append(
                    {
                        "asset_id": asset_id,
                        "position": position,
                        "category": "brand",
                        "finding": "; ".join(findings)[:500],
                    }
                )
            # 2) 产品几何保真审查(fail-open:审查器出错不挡门,只有明确变形才挡)。
            reference = reference_by_color.get(variant_color) or reference_default
            if geometry_audit_on and reference is not None:
                try:
                    geo_findings = ai_geometry_violation(
                        key, reference[0], reference[1], contents, mime
                    )
                except Exception as exc:  # noqa: BLE001 - quality gate, never fail-closed
                    _LOGGER.warning(
                        "geometry audit failed for %s pos %s: %s",
                        product.id,
                        position,
                        exc,
                    )
                    geo_findings = []
                if geo_findings:
                    image_violations.append(
                        {
                            "asset_id": asset_id,
                            "position": position,
                            "category": "geometry",
                            "finding": "产品几何与原图不符(AI画变形): "
                            + "; ".join(geo_findings)[:400],
                        }
                    )

    # 去重文本违规
    seen = set()
    deduped = []
    for violation in text_violations:
        marker = (violation["surface"], violation["term"].lower())
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(violation)

    audit = {
        "clean": not deduped and not image_violations and not errors,
        "fingerprint": fingerprint,
        "audited_at": datetime.now(UTC).isoformat(),
        "attempt": attempt,
        "site_brand": SITE_BRAND,
        "blacklist_terms": terms,
        "text_violations": deduped,
        "image_violations": image_violations,
        "errors": errors,
    }
    fresh = db.get(KProductKnowledgeProduct, product.id)
    if fresh is not None:
        fresh.brand_audit_json = audit
        db.add(fresh)
        db.flush()
    return audit


def audit_gate_blockers(
    db: Session,
    product: KProductKnowledgeProduct,
) -> list[str]:
    """P 上架门禁用：返回品牌相关 blocker 列表（空 = 放行）。fail-closed。"""
    audit = product.brand_audit_json
    if not isinstance(audit, dict):
        return ["品牌审查未跑：先在产品页跑「品牌审查」并通过"]
    if audit.get("fingerprint") != brand_fingerprint(db, product):
        return ["内容在品牌审查后有改动：请重新跑「品牌审查」"]
    if audit.get("clean"):
        return []
    problems = []
    for violation in (audit.get("text_violations") or [])[:5]:
        problems.append(f"{violation.get('term')}({violation.get('surface')})")
    for violation in (audit.get("image_violations") or [])[:5]:
        problems.append(f"第{violation.get('position')}张图:{violation.get('finding', '')[:60]}")
    if audit.get("errors"):
        problems.append(f"审查有 {len(audit['errors'])} 步失败(fail-closed)")
    return ["品牌审查未通过：" + "；".join(problems)]
