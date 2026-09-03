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

# 通用技术/接口/标准/评级/材料词——永远不是"品牌"。AI 文本审查偶尔把它们误判成
# 商标(如 USB-C 被当品牌名挡上架),这里兜底过滤,避免误报。运营者仍可对个别
# 判定用「忽略」放行(ignored_findings),两条路互补。
_GENERIC_TERM_WHITELIST = {
    "usb", "usb-c", "usb c", "usbc", "usb-a", "usb a", "type-c", "type c",
    "usb type-c", "usb type c", "micro-usb", "micro usb", "usb-micro", "usb 2.0",
    "usb 3.0", "usb-c cable", "usb c cable",
    "bluetooth", "wi-fi", "wifi",
    "led", "lcd", "oled",
    "ipx4", "ipx5", "ipx6", "ipx7", "ipx8", "ip65", "ip66", "ip67", "ip68",
    "li-ion", "lithium-ion", "lithium ion", "mah", "wh",
    "qi", "pd", "quick charge",
    "abs", "tpu", "tpe", "pvc", "eva", "silicone",
}


def _is_generic_non_brand(term: str) -> bool:
    """通用技术/接口/标准/材料词,永不视作第三方品牌。"""
    normalized = " ".join(str(term or "").strip().lower().split())
    return (
        normalized in SITE_BRAND_WHITELIST
        or normalized in _GENERIC_TERM_WHITELIST
    )

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
    # staged(暂存待保存) 的图同样要审：2026-08-03 熊猫花洒——审查原本只在人工
    # 点「保存」之后才跑，于是运营者打开产品页时，系统对这批图一次检查都没做
    # 过，等于让人当第一道质检（用户就是这样自己发现了三处软管接错的）。
    # 渲染批次收尾现在直接入队审查，问题图会被自动重渲，人看到的是已过检的图。
    rows = db.scalars(
        select(KProductKnowledgeMediaAsset).where(
            KProductKnowledgeMediaAsset.product_id == product.id,
            KProductKnowledgeMediaAsset.status.in_(("available", "staged")),
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

# 渲染 prompt 追加块：产品表面的**文字**标识一律无差别清除 —— 不判断是不是
# 品牌（判断会漏），只要是印在产品上的字就删。保形状/颜色/结构。
#
# 2026-08-03 熊猫花洒(PSPE-002)教训：这里原本还写了 "symbols"，与
# image_render_jobs.PRODUCT_FIDELITY_BLOCK 的「buttons/ports/display/controls
# 的布局和数量必须一致」直接打架 —— 电源符号 ⏻ 既是 symbol 又是 control，
# 模型每张图随机挑一边执行，于是同一批 9 张图里电源键出现了「绿色电源符号 /
# 空白椭圆 / 黑色椭圆 / 黑色圆形」四种长相。功能件是产品结构，永远不删；
# 只删品牌字样和文字。
BRAND_REMOVAL_PROMPT_BLOCK = (
    "\n\nTEXT & LOGO REMOVAL (MANDATORY, do not skip): remove ALL text, "
    "lettering, wordmarks, and printed labels from the product "
    "surface itself — every character, no matter what it says. Replace each "
    "removed mark with a clean blank surface matching the product's material, "
    "color, and texture. Do NOT alter the product's shape, structure, "
    "proportions, or colors in any other way. Packaging, tags, and background "
    "props must also carry no readable text or logos. No text is allowed in "
    "the model output; verified information overlays are added server-side.\n"
    "FUNCTIONAL-PART EXEMPTION (overrides the removal rule above): a product's "
    "FUNCTIONAL parts are structure, not branding, and must be preserved "
    "EXACTLY as they appear in the reference photo — power buttons and their "
    "printed power icon, control buttons and their icons, indicator lights, "
    "displays and screens, ports and their icons, dials, switches, and any "
    "moulded or printed mark that identifies a control. Never blank out, "
    "flatten, recolour, move, or delete a control or its icon in the name of "
    "removing branding. If a mark is a control, KEEP it."
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


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")


def _product_own_words(product: KProductKnowledgeProduct) -> set[str]:
    """产品自己名字里的词——AI 文本审查不得把它们当第三方品牌。

    2026-08-03 熊猫花洒：产品叫 "Panda Outdoor Shower"，"Panda" 是造型描述，
    但确实存在同名品牌，于是 AI 把它当商标，一口气报了 52 条违规（产品名、
    关键词、文案、每张图的 title/alt/caption/description 全中），把 clean 打成
    false、连带把自动重渲闭环整个卡死（有文本违规就不重渲图）。

    产品名和主关键词是运营者审定过的自有描述；真品牌走的是源头黑名单
    ``detected_brand_terms``（R→K 搬运时剥离并记录），那条路不受影响。
    """
    words: set[str] = set()
    for field in ("product_name_en", "primary_keyword"):
        value = getattr(product, field, None)
        if isinstance(value, str):
            words.update(match.group(0).lower() for match in _WORD_RE.finditer(value))
    return {word for word in words if len(word) >= 2}


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
    "Do NOT flag generic technical, connector, interface, standard, rating, or "
    "material terms — e.g. USB, USB-C, Type-C, Bluetooth, Wi-Fi, LED, LCD, IPX8, "
    "IP67, Li-ion, mAh, ABS, TPU, silicone — these are industry-standard terms, "
    "not brands. "
    f'"{SITE_BRAND}" and its variants are the site\'s own brand and are ALLOWED. '
    "Return ONLY JSON: {\"violations\": [{\"surface\": \"<surface id>\", "
    "\"term\": \"<the brand term>\", \"evidence\": \"<short quote>\"}]} — empty "
    "array if fully clean. Be strict: when a token looks like a brand, flag it."
)


def ai_text_violations(
    key,
    surfaces: list[tuple[str, str]],
    own_words: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not surfaces:
        return []
    listing = "\n".join(
        f"[{surface}] {text_value}" for surface, text_value in surfaces
    )
    instruction = _TEXT_AUDIT_INSTRUCTION
    if own_words:
        # 把产品自己的名字告诉审查器。2026-08-11：熊猫花洒叫 "Panda Outdoor
        # Shower"，AI 把每一个含 panda 的描述短语都报成商标——"panda pump"、
        # "panda unit"、"Panda portable shower head"…… 一口气十条，全是误报，
        # 直接把上架门堵死。
        instruction += (
            "\nPRODUCT'S OWN WORDS (never a third-party brand): "
            + ", ".join(sorted(own_words))
            + ". These come from this product's own name and primary keyword. "
            "Any phrase built out of them — on its own or combined with generic "
            "nouns like pump, unit, set, head, kit — is a DESCRIPTION of this "
            "product, not a trademark. Never flag those."
        )
    reply = _chat_completion(
        key,
        [
            {"role": "system", "content": instruction},
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
        if _is_generic_non_brand(term):
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
    "NOT a defect (never flag these): the product's OWN functional parts — a "
    "power button and its printed power icon, control icons, indicator lights, "
    "a display, port icons, dials and switches moulded into the product. Those "
    "belong to the physical product, not to the page design.\n"
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


# 2026-08-03 熊猫花洒教训：旧版结尾写着「Only flag clear, obvious product
# distortion; when the product looks like the same physical object, do NOT
# flag」——这句把门槛抬到「还认得出是同一个东西就放行」，于是主图上电源座
# 凸台多长出一块、耳朵不对称、边缘串色全部被放行到 staged。改成逐项检查表：
# 先分项判定再给结论，让审查器没法用一句「看着还是同一个东西」糊过去。
_GEOMETRY_AUDIT_INSTRUCTION = (
    "You are a product-fidelity auditor for an e-commerce catalog. The FIRST "
    "image(s) are the TRUE reference photo(s) of the product, possibly shot "
    "from different angles. The LAST image is an AI-rendered marketing image of "
    "the SAME product that will be published only if the product's physical "
    "form was preserved.\n"
    "The reference photos may carry marketing text, badges or busy backgrounds "
    "— ignore all of that and compare ONLY the physical product.\n"
    "SCOPE — read this first, it prevents the most common false alarm: you are "
    "judging ONLY the physical integrity of the product parts that are ACTUALLY "
    "SHOWN in the rendered image. The rendered image is a different photograph "
    "with its own composition: it may legitimately show only the main unit, or "
    "only one accessory, or the product from a new angle, cropped or partly out "
    "of frame. **An item that appears in a reference photo but is simply not "
    "included in this shot is NOT a defect — never flag something as missing "
    "just because the reference had it.** Likewise a genuine accessory of this "
    "product appearing here is not an 'extra part'. Judge what IS shown.\n"
    "Work through this checklist and judge EACH item before concluding:\n"
    "1. CONTROL HOUSING: is the button/control housing the same shape and "
    "outline, with the same symmetry, as in the reference? Flag any extra bump, "
    "notch, dent, collapsed edge or lopsided housing.\n"
    "2. CONTROLS: same number, same positions, and same printed icons for "
    "buttons, ports, indicator lights, displays, dials and switches? A control "
    "that was blanked out, filled in, recoloured or turned into a featureless "
    "oval is a FAIL.\n"
    "3. PARTS INTEGRITY: for the parts that ARE shown, is each one shaped and "
    "placed as in the reference (handles, feet, ears, nozzles, ports, trim "
    "rings, fins)? Flag parts that were reshaped, merged, duplicated, or moved "
    "to a different spot ON THE PRODUCT BODY.\n"
    "4. CONNECTIONS & TUBING (check this carefully — it is the most common "
    "failure): follow every hose, tube, cable and cord along its whole length. "
    "Each one must (a) leave the product body at the SAME port/outlet position "
    "as in the reference — not out of the belly, the face, or some invented "
    "opening; (b) run continuously without changing thickness, splitting, or "
    "vanishing behind something and never reappearing; and (c) actually TERMINATE "
    "where it should — a hose must physically reach and connect to the shower "
    "head / handle / device it feeds, not stop in mid-air, not end at a bowl "
    "rim, a table edge, or the picture border. Flag any stray, orphaned, "
    "dead-ended, or duplicated length of tubing, including a short stub that "
    "connects to nothing.\n"
    "5. SILHOUETTE & PROPORTIONS: is the outer contour and the body/head "
    "proportion the same? Flag a body squashed wider, stretched, or reshaped.\n"
    "6. COLOUR BLEEDING: has the colour of one part bled onto an adjacent part "
    "that is a different colour in the reference (e.g. a green base tinting a "
    "black ear)? That is a rendering defect, flag it.\n"
    "IGNORE everything that is NOT the product's physical form: overall colour "
    "variant of the whole product (colour variants are intentional), "
    "background, scene, props, people, lighting, angle, framing, zoom, crop, "
    "which accessories were included in the shot, and whether water is "
    "spraying.\n"
    "Do not excuse a defect just because the render still looks like the same "
    "kind of object. If any checklist item fails, flag it.\n"
    'Return ONLY JSON: {"flagged": true|false, "findings": ["<which checklist '
    'item failed and what differs>"]}'
)


def ai_geometry_violation(
    key,
    reference_bytes: bytes,
    reference_mime: str,
    rendered_bytes: bytes,
    rendered_mime: str,
    extra_references: list[tuple[bytes, str]] | None = None,
) -> list[str]:
    """Vision compare rendered image vs reference(s); return product-distortion
    findings (empty = faithful). Sends every reference first, rendered LAST.

    ``extra_references`` are additional original supplier photos of the same
    product from other angles. One frontal marketing shot is not enough to
    judge part count or symmetry — 2026-08-03 熊猫花洒 shipped a main image
    whose control housing had grown an extra lump and whose ears were
    asymmetric, and a single-reference audit passed it.
    """
    ren_b64 = base64.b64encode(rendered_bytes).decode("ascii")
    content: list[dict[str, Any]] = [
        {"type": "text", "text": _GEOMETRY_AUDIT_INSTRUCTION}
    ]
    for ref_payload, ref_mime in [
        (reference_bytes, reference_mime),
        *(extra_references or []),
    ]:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{ref_mime};base64,"
                        + base64.b64encode(ref_payload).decode("ascii")
                    )
                },
            }
        )
    content.append(
        {
            "type": "image_url",
            "image_url": {"url": f"data:{rendered_mime};base64,{ren_b64}"},
        }
    )
    reply = _chat_completion(key, [{"role": "user", "content": content}])
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


# 几何/物理审查一次最多送几张参考图：多角度才判得出部件数量与对称性，
# 但每张都要烧 vision token，3 张是效果与成本的平衡点。
MAX_AUDIT_REFERENCES = 3


# --- 工作原理推导 + 物理可信度审查 -------------------------------------------
#
# 2026-08-03 熊猫花洒(PSPE-002)：这是一台潜水泵——整机浸没才出水、没有吸水
# 管。但作图链路上没有任何一环知道这件事：作图简报只拿到文字规格(2.11 GPM /
# 6.5 ft 软管 / IPX8)，从没见过产品照片，于是把泵画在干燥地面上却在喷水，
# 9 张图里 3 张物理不成立。PSPE-001 早就栽过同一个坑，当时只修了那个产品、
# 没修模块，所以原样再犯。
#
# 这里补上缺失的那一层：看原厂参考图 + 规格，推导出「这东西怎么工作、怎样
# 才算把它画对、谁在用」，结果贯穿排图组(简报) → 渲染(prompt) → 审查(本模块)
# 三个环节。存进已有的 image_instruction_json["operating_model"]，零迁移。

_OPERATING_MODEL_INSTRUCTION = (
    "You are a product engineer briefing a photographer who has never seen this "
    "product. The images are the real supplier photos; the JSON below carries "
    "its verified specifications. Work out how this product physically WORKS, "
    "so that nobody photographs it in a way that could not happen in reality.\n"
    "Think about: what has to be true for it to operate at all (does part of it "
    "have to be submerged, plugged in, filled, mounted, held, opened, "
    "assembled?); which parts move or emit something; what it connects to; and "
    "what a photo would look like if someone got that wrong.\n"
    "Be strict about only stating what the photos and specs actually support. "
    "If the product has no special operating requirement — it just sits there, "
    "or is simply held or worn — return EMPTY arrays rather than inventing "
    "constraints. An invented constraint is worse than none.\n"
    "Also infer who realistically buys and uses it, reading the product's form "
    "and styling as evidence: a cute animal-shaped consumer product is bought "
    "for children or pets, a rugged technical one for outdoor or trade use. "
    "List the distinct kinds of people and settings, not one generic persona.\n"
    "FINALLY, classify EVERY supplied image, in the order they were given. The "
    "ONLY question is: **can the real product itself be seen clearly enough in "
    "this image to copy its true appearance?**\n"
    "Judge ONLY that. Supplier images are nearly always designed e-commerce "
    "graphics — headline text, callouts, coloured backgrounds, cut-out "
    "collages, retail boxes, lifestyle models. **None of that disqualifies an "
    "image**: the product inside it was still really photographed, and it is "
    "often the only place an accessory's true shape and colour can be seen.\n"
    "- 'product_visible' — the product (or one of its accessories/parts) appears "
    "clearly enough to copy its shape, colour and details. This INCLUDES "
    "designed sales images, what's-in-the-box lay-outs, close-ups, and "
    "lifestyle shots where the product reads clearly. **When in doubt, choose "
    "this.**\n"
    "- 'no_product' — nothing about the real product can be learned here: a "
    "certificate / patent / test-report document, a pure text or pure "
    "background banner, or a shot where the product is absent, tiny, or almost "
    "entirely hidden.\n"
    "ALSO tag what each image is USEFUL AS — this decides which photo becomes the "
    "base plate for which kind of marketing shot. **Look at each image one at a "
    "time and decide independently; do not give them all the same tag.** The "
    "product's pose in a photo can never be changed later, so a photo showing it "
    "mid-use is the single most valuable asset there is.\n"
    "- 'in_use' — TAG THIS IF **ANY** OF THESE IS TRUE: a person's hand or body "
    "is holding, touching or operating the product; its hose/cable/cord is "
    "EXTENDED and connected to the thing it feeds (rather than coiled up); water, "
    "light, steam or spray is coming out of it; or it is sitting in its working "
    "position (in the basin, on the wall mount, in the water). A model, a "
    "bathroom/outdoor setting, or headline text in the frame does NOT disqualify "
    "it — those are exactly what in-use supplier photos look like.\n"
    "- 'product_only' — ONLY when the product is presented by itself with **no "
    "person and no sign of operation**: hose coiled, nothing emitted, nobody "
    "touching it. A pure packshot.\n"
    "- 'accessories' — a contents / what's-in-the-box lay-out where the separate "
    "accessories are laid out side by side.\n"
    "- 'detail' — a tight close-up of one part, control, texture or connector.\n"
    "- 'none' — for images tagged no_product.\n"
    "Most supplier image sets contain a MIX of these. If you tagged every image "
    "the same way, re-check them — you almost certainly missed an in-use shot.\n"
    "Return ONLY JSON:\n"
    "{\n"
    '  "how_it_works": "<2-4 plain sentences: how the product actually '
    'operates>",\n'
    '  "hard_constraints": ["<a physical condition that MUST hold in any photo '
    'showing it in use, e.g. the pump body must be fully submerged in water for '
    'water to come out>"],\n'
    '  "forbidden_depictions": ["<a concrete wrong picture to never produce, '
    'e.g. the pump sitting on dry ground while water sprays from the hose>"],\n'
    '  "buyer_personas": ["<a distinct kind of user + the setting they use it '
    'in, e.g. a parent bathing a toddler in a backyard>"],\n'
    '  "reference_kinds": ["<one of product_visible|no_product for EACH supplied '
    'image, same order, same count>"],\n'
    '  "reference_poses": ["<one of in_use|product_only|accessories|detail|none '
    'for EACH supplied image, same order, same count>"]\n'
    "}"
)


REFERENCE_KIND_PRODUCT_VISIBLE = "product_visible"
REFERENCE_KIND_NO_PRODUCT = "no_product"

# 底图姿态 —— 决定哪张实拍能当哪类成品图的底板。
# 2026-08-03：产品的姿态在照片里定死了，事后改不了(行业边界,Flair 这类工具
# 同样靠人摆素材)。所以「软管展开、连着花洒头、有人在用」的那张实拍，价值
# 远高于又一张摆拍——场景图只能拿它当底板。
POSE_IN_USE = "in_use"
POSE_PRODUCT_ONLY = "product_only"
POSE_ACCESSORIES = "accessories"
POSE_DETAIL = "detail"
POSE_NONE = "none"
_REFERENCE_POSES = (
    POSE_IN_USE,
    POSE_PRODUCT_ONLY,
    POSE_ACCESSORIES,
    POSE_DETAIL,
    POSE_NONE,
)
# 只有「压根看不到产品」的图才排除（证书/纯文字/产品缺席）。
# 2026-08-03 用户纠正：电商合成图里的产品也是实拍抠出来的，带版式≠不能用；
# 熊猫那张白底全家福正是唯一能看清全部配件真实长相的图，扔掉它等于白修。
# 旧值(product_photo/marketing_graphic)一律按可用处理，存量数据无需重跑。
_REFERENCE_KINDS = (
    REFERENCE_KIND_PRODUCT_VISIBLE,
    REFERENCE_KIND_NO_PRODUCT,
)
_REFERENCE_KINDS_UNUSABLE = frozenset({REFERENCE_KIND_NO_PRODUCT, "certificate"})


def reference_kind_usable(kind: Any) -> bool:
    """这张参考图能不能喂给作图模型（默认能——不确定时宁可多送）。"""
    return str(kind or "").strip().lower() not in _REFERENCE_KINDS_UNUSABLE


# 每类成品图偏好哪种底图姿态，从左到右依次退让。
# 场景图必须优先拿 in_use（软管展开、连着花洒头的那张）——拿摆拍当底板，
# 出来就是「产品静静躺着而水在喷」的假图。
PLATE_POSE_PREFERENCE: dict[str, tuple[str, ...]] = {
    "proof_scene": (POSE_IN_USE, POSE_PRODUCT_ONLY, POSE_DETAIL),
    "main": (POSE_PRODUCT_ONLY, POSE_DETAIL, POSE_IN_USE),
    "feature_callout": (POSE_PRODUCT_ONLY, POSE_DETAIL, POSE_IN_USE),
    "dimension": (POSE_PRODUCT_ONLY, POSE_DETAIL, POSE_IN_USE),
    "accessory": (POSE_ACCESSORIES, POSE_PRODUCT_ONLY, POSE_IN_USE),
    "detail": (POSE_DETAIL, POSE_PRODUCT_ONLY, POSE_IN_USE),
}


def reference_pose(operating_model: dict[str, Any], object_key: str) -> str:
    """这张参考图的姿态（缺省按「干净产品展示」处理）。"""
    poses = operating_model.get("reference_poses")
    if not isinstance(poses, dict):
        return POSE_PRODUCT_ONLY
    value = str(poses.get(object_key) or "").strip().lower()
    return value if value in _REFERENCE_POSES else POSE_PRODUCT_ONLY
# 分类这一步要把参考图全看一遍才分得全（渲染只挑得出它见过的那些），所以
# 比几何门的 3 张放宽。一个产品一辈子只跑几次，成本可忽略。
MAX_OPERATING_MODEL_REFERENCES = 8


def ai_operating_model(
    key,
    *,
    product_facts: dict[str, Any],
    references: list[tuple[bytes, str]],
    reference_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Vision-derive how the product physically works, who uses it, and which
    supplied reference images are real product photos.

    ``reference_keys`` are stable ids (asset object_key) positionally aligned
    with ``references``; when given, the returned payload carries
    ``reference_classification`` as {key: kind} so the renderer can feed only
    real product photos to the image model instead of supplier sales banners.

    Returns the ``operating_model`` payload (see module note above). Raises on
    provider/parse failure — the caller decides whether that is fatal.
    """
    content: list[dict[str, Any]] = [
        {"type": "text", "text": _OPERATING_MODEL_INSTRUCTION},
        {
            "type": "text",
            "text": json.dumps(product_facts, ensure_ascii=False, default=str)[
                :20000
            ],
        },
    ]
    sent = references[:MAX_OPERATING_MODEL_REFERENCES]
    for ref_payload, ref_mime in sent:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{ref_mime};base64,"
                        + base64.b64encode(ref_payload).decode("ascii")
                    )
                },
            }
        )
    parsed = _json_from_reply(_chat_completion(key, [{"role": "user", "content": content}]))

    def _clean_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            text_value = str(item).strip()[:300]
            if text_value and text_value not in out:
                out.append(text_value)
        return out[:8]

    # 逐张分类按顺序对齐回 asset key。模型少给/多给/给了不认识的值都当作
    # 「不确定」——不确定一律按 product_photo 处理：漏送一张真实拍图的损失
    # (AI 又看不见配件了)远大于误送一张营销图(prompt 里已明令不许抄版式)。
    classification: dict[str, str] = {}
    poses: dict[str, str] = {}
    if reference_keys:
        raw_kinds = parsed.get("reference_kinds")
        kinds = raw_kinds if isinstance(raw_kinds, list) else []
        raw_poses = parsed.get("reference_poses")
        pose_list = raw_poses if isinstance(raw_poses, list) else []
        for index, asset_key in enumerate(reference_keys[: len(sent)]):
            kind = str(kinds[index]).strip().lower() if index < len(kinds) else ""
            classification[asset_key] = (
                kind if kind in _REFERENCE_KINDS else REFERENCE_KIND_PRODUCT_VISIBLE
            )
            pose = str(pose_list[index]).strip().lower() if index < len(pose_list) else ""
            # 认不出来的一律当「干净产品展示」——它是最保守的底板用途，
            # 不会让一张营销图冒充成「正在使用」的场景底图。
            poses[asset_key] = (
                pose if pose in _REFERENCE_POSES else POSE_PRODUCT_ONLY
            )

    return {
        "how_it_works": str(parsed.get("how_it_works") or "").strip()[:1200],
        "hard_constraints": _clean_list(parsed.get("hard_constraints")),
        "forbidden_depictions": _clean_list(parsed.get("forbidden_depictions")),
        "buyer_personas": _clean_list(parsed.get("buyer_personas")),
        "reference_classification": classification,
        "reference_poses": poses,
        "edited_by_user": False,
        "derived_at": datetime.now(UTC).isoformat(),
    }


_PHYSICS_AUDIT_INSTRUCTION = (
    "You are a product-photography plausibility auditor. You are given how a "
    "product physically works, a list of depictions that must never be "
    "published, and one rendered marketing image.\n"
    "Flag the image ONLY if it actually shows the product in a physically "
    "impossible or self-contradictory state — for example the product visibly "
    "operating while a stated precondition for operating is visibly not met.\n"
    "Judge only what is VISIBLE. Do not flag an image because a precondition is "
    "merely out of frame or ambiguous, and do not flag a static product that is "
    "plainly not in use (a packshot, a flat-lay of what's in the box, a "
    "carry/packed shot, a clean infographic base). Those are legitimate.\n"
    'Return ONLY JSON: {"flagged": true|false, "findings": ["<which constraint '
    'is visibly violated and how>"]}'
)


def ai_physics_violation(
    key,
    *,
    operating_model: dict[str, Any],
    rendered_bytes: bytes,
    rendered_mime: str,
) -> list[str]:
    """Vision-check one render against the product's operating constraints."""
    constraints = operating_model.get("hard_constraints") or []
    forbidden = operating_model.get("forbidden_depictions") or []
    if not constraints and not forbidden:
        return []
    briefing = json.dumps(
        {
            "how_it_works": operating_model.get("how_it_works") or "",
            "hard_constraints": constraints,
            "forbidden_depictions": forbidden,
        },
        ensure_ascii=False,
        default=str,
    )
    reply = _chat_completion(
        key,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PHYSICS_AUDIT_INSTRUCTION},
                    {"type": "text", "text": briefing[:8000]},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:{rendered_mime};base64,"
                                + base64.b64encode(rendered_bytes).decode("ascii")
                            )
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
    return out or ["render contradicts how the product physically works"]


def product_operating_model(
    product: KProductKnowledgeProduct,
) -> dict[str, Any]:
    """Read the stored operating model off the image brief (empty dict = none)."""
    brief = product.image_instruction_json
    if not isinstance(brief, dict):
        return {}
    model = brief.get("operating_model")
    return model if isinstance(model, dict) else {}


def reference_assets_for_derivation(
    db: Session,
    product: KProductKnowledgeProduct,
) -> list[tuple[str, bytes, str]]:
    """所有原厂参考图的 (object_key, bytes, mime)，按入库顺序。

    给 :func:`ai_operating_model` 逐张分类用——它要按稳定 key 把分类结果贴
    回资产，渲染侧才挑得出「哪几张是真实产品照」。
    """
    rows = db.scalars(
        select(KProductKnowledgeMediaAsset)
        .where(
            KProductKnowledgeMediaAsset.product_id == product.id,
            KProductKnowledgeMediaAsset.status == "available",
            KProductKnowledgeMediaAsset.asset_type == "image",
            KProductKnowledgeMediaAsset.asset_role == "reference",
        )
        .order_by(KProductKnowledgeMediaAsset.created_at.asc())
    ).all()
    out: list[tuple[str, bytes, str]] = []
    for row in rows:
        loaded = _asset_preview_bytes(row)
        if loaded is None or not row.object_key:
            continue
        out.append((str(row.object_key), loaded[0], loaded[1]))
    return out


def _reference_previews(
    db: Session,
    product: KProductKnowledgeProduct,
) -> tuple[
    dict[str, tuple[bytes, str]],
    tuple[bytes, str] | None,
    list[tuple[bytes, str]],
]:
    """Load reference product photos for the geometry check: a {variant_color:
    (bytes, mime)} map, a default, plus up to ``MAX_AUDIT_REFERENCES``-1 extra
    angles. Reference assets are the original supplier photos
    (asset_role='reference'), never pipeline renders."""
    rows = db.scalars(
        select(KProductKnowledgeMediaAsset)
        .where(
            KProductKnowledgeMediaAsset.product_id == product.id,
            KProductKnowledgeMediaAsset.status == "available",
            KProductKnowledgeMediaAsset.asset_type == "image",
            KProductKnowledgeMediaAsset.asset_role == "reference",
        )
        # 排序必须确定：没有 order_by 时「送哪 3 张进几何门」由数据库返回顺序
        # 决定，同一产品两次审查可能拿到不同的参考图，结果无法复现。
        .order_by(KProductKnowledgeMediaAsset.created_at.asc())
    ).all()
    by_color: dict[str, tuple[bytes, str]] = {}
    default: tuple[bytes, str] | None = None
    extras: list[tuple[bytes, str]] = []
    for row in rows:
        loaded = _asset_preview_bytes(row)
        if loaded is None:
            continue
        if default is None:
            default = loaded
        elif len(extras) < MAX_AUDIT_REFERENCES - 1:
            extras.append(loaded)
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        color = str(meta.get("variant_color") or "").strip().lower()
        if color:
            by_color[color] = loaded
    return by_color, default, extras


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


# --- 忽略/人工放行 --------------------------------------------------------

def brand_finding_fingerprint(kind: str, finding: dict[str, Any]) -> str:
    """一条审查发现的稳定指纹,用于「忽略」放行(跨审查重跑保持一致)。

    text = surface + term;image = **asset_id** + position + category。

    2026-08-31 体检:图片指纹以前只由 (位号, 类别) 组成,**不含任何图片内容标识**。
    而 K 的出图流程就是按位号覆盖——忽略了第 3 张图的一条 geometry 违规之后,
    第 3 张位号重渲成一张全新的、有别的毛病的图,指纹仍然是 image::3::geometry,
    照旧命中忽略清单直接放行,而且静默无提示。线上实测 PSPE-002 的第 2、5 张图
    就处在这种「品牌类别永久放行」状态。这打穿的是「独立站品牌只有 Barong Yekhna」
    四层防线里的最后一层。

    加进 asset_id 之后:重渲产生新 asset ⇒ 新指纹 ⇒ 旧放行不再继承,必须重新看一眼。
    **代价是存量 ignored_findings 全部失效**(旧格式对不上),这是有意为之——
    那些放行本来就是在「不知道自己在放行什么」的前提下点的。
    """
    if kind == "text":
        surface = str(finding.get("surface") or "").strip().lower()
        term = " ".join(str(finding.get("term") or "").strip().lower().split())
        return f"text::{surface}::{term}"
    if kind == "image":
        category = str(finding.get("category") or "").strip().lower()
        asset_id = str(finding.get("asset_id") or "").strip().lower()
        return f"image::{asset_id}::{finding.get('position')}::{category}"
    return f"{kind}::{finding}"


def _audit_violation_fingerprints(
    text_violations: list[dict[str, Any]],
    image_violations: list[dict[str, Any]],
) -> list[str]:
    return [brand_finding_fingerprint("text", v) for v in text_violations] + [
        brand_finding_fingerprint("image", v) for v in image_violations
    ]


def set_operator_override(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    enabled: bool,
    user: User | None,
    reason: str = "",
) -> dict[str, Any]:
    """人工放行：这个产品的品牌审查从此不再拥有否决权。

    2026-08-11 用户拍板的规矩：**这个控制台里，人的命令高于任何一道程序。**
    起因是审查器把花洒手柄上的 "STOP"（一键止水的功能标识）判成品牌字样、
    把 "panda pump"（产品描述）判成商标——它不真正了解这个产品，而运营者了解。

    审查照跑、结论照存照显示，只是不再挡上架。开关本身留痕（谁、何时、为何），
    出了事查得到是谁拍的板。调用方 commit。
    """
    from sqlalchemy.orm.attributes import flag_modified

    audit = (
        dict(product.brand_audit_json)
        if isinstance(product.brand_audit_json, dict)
        else {}
    )
    if enabled:
        audit["operator_override"] = {
            "enabled": True,
            "by": getattr(user, "username", None),
            "at": datetime.now(UTC).isoformat(),
            "reason": str(reason or "").strip()[:500],
        }
    else:
        audit.pop("operator_override", None)
    product.brand_audit_json = audit
    flag_modified(product, "brand_audit_json")
    db.add(product)
    return audit


def set_brand_finding_ignored(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    fingerprint: str,
    ignored: bool,
    user: User | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """把某条审查发现标记为「忽略」(人工放行)或撤销,并按忽略后重算 clean。

    忽略清单存在 brand_audit_json.ignored_findings,审查重跑会结转(见 run_brand_audit)。
    调用方 commit。

    **留痕**(2026-08-31 补):同文件的 set_operator_override 一直记着 by/at/reason,
    这条路径却只往数组里塞一个指纹字符串——放行了什么、谁放的、为什么,事后一概查不到。
    品牌门是「独立站品牌只有 Barong Yekhna」这条家规的执行面,两条放行路径必须同等留痕。
    """
    from sqlalchemy.orm.attributes import flag_modified

    audit = (
        dict(product.brand_audit_json)
        if isinstance(product.brand_audit_json, dict)
        else {}
    )
    ignore_set = set(audit.get("ignored_findings") or [])
    trail = dict(audit.get("ignored_findings_trail") or {})
    if ignored:
        ignore_set.add(fingerprint)
        trail[fingerprint] = {
            "by": str(getattr(user, "username", "") or "unknown"),
            "by_user_id": str(getattr(user, "id", "") or ""),
            "at": _now().isoformat(),
            "reason": reason.strip(),
        }
    else:
        ignore_set.discard(fingerprint)
        trail.pop(fingerprint, None)
    audit["ignored_findings"] = sorted(ignore_set)
    audit["ignored_findings_trail"] = trail
    unresolved = [
        fp
        for fp in _audit_violation_fingerprints(
            audit.get("text_violations") or [],
            audit.get("image_violations") or [],
        )
        if fp not in ignore_set
    ]
    audit["clean"] = not unresolved and not (audit.get("errors"))
    audit["unresolved_count"] = len(unresolved)
    product.brand_audit_json = audit
    flag_modified(product, "brand_audit_json")
    db.add(product)
    return audit


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

    运营者「忽略」放行的发现(brand_audit_json.ignored_findings)会结转,重跑后仍
    生效——被忽略的 text/image 违规不再计入 clean。errors 永不可忽略。
    """
    prev_audit = (
        product.brand_audit_json
        if isinstance(product.brand_audit_json, dict)
        else {}
    )
    ignored_findings = list(prev_audit.get("ignored_findings") or [])

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
    reference_extras: list[tuple[bytes, str]] = []
    # 物理可信度检查(潜水泵放在干地上却在喷水这类)。约束来自作图简报里推导出的
    # operating_model；没有约束就自动跳过(普通产品不会凭空长出物理限制)。
    operating_model = product_operating_model(product)
    physics_audit_on = os.getenv("K_PHYSICS_AUDIT_ENABLED", "1").strip() not in (
        "0",
        "false",
        "off",
        "",
    ) and bool(
        (operating_model.get("hard_constraints") or [])
        or (operating_model.get("forbidden_depictions") or [])
    )
    if geometry_audit_on and images_to_audit:
        try:
            (
                reference_by_color,
                reference_default,
                reference_extras,
            ) = _reference_previews(db, product)
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
            blacklist = {term.strip().lower() for term in terms}
            own_words = _product_own_words(product)

            def _is_own_description(term: str) -> bool:
                """这个 term 是在描述我们自己的产品，而不是第三方品牌。

                按**词**判断，不是整串比对：报上来的多是短语（"panda pump"、
                "Panda portable shower head"），整串永远不会等于产品名里的单词。
                只要短语里用到了产品自己的名字，它就是描述——第三方品牌不会
                拿我们的产品名造词。真品牌仍由源头黑名单独立拦截。
                """
                words = {
                    match.group(0).lower() for match in _WORD_RE.finditer(term)
                }
                return bool(words & own_words)

            text_violations.extend(
                violation
                for violation in ai_text_violations(key, surfaces, own_words)
                # 自有描述放行——除非它同时上了源头黑名单(那是真品牌混进了
                # 产品名，必须照挡)。
                if not _is_own_description(violation["term"])
                or violation["term"].strip().lower() in blacklist
            )
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
                        key,
                        reference[0],
                        reference[1],
                        contents,
                        mime,
                        extra_references=[
                            extra for extra in reference_extras if extra != reference
                        ],
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
            # 3) 物理可信度审查(fail-open,同几何门)：这张图有没有把产品画成
            #    根本不可能工作的样子(潜水泵搁干地上却在喷水)。
            if physics_audit_on:
                try:
                    physics_findings = ai_physics_violation(
                        key,
                        operating_model=operating_model,
                        rendered_bytes=contents,
                        rendered_mime=mime,
                    )
                except Exception as exc:  # noqa: BLE001 - quality gate, never fail-closed
                    _LOGGER.warning(
                        "physics audit failed for %s pos %s: %s",
                        product.id,
                        position,
                        exc,
                    )
                    physics_findings = []
                if physics_findings:
                    image_violations.append(
                        {
                            "asset_id": asset_id,
                            "position": position,
                            "category": "physics",
                            "finding": "画面与产品工作原理矛盾: "
                            + "; ".join(physics_findings)[:400],
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

    ignore_set = set(ignored_findings)
    unresolved = [
        fp
        for fp in _audit_violation_fingerprints(deduped, image_violations)
        if fp not in ignore_set
    ]
    audit = {
        "clean": not unresolved and not errors,
        "fingerprint": fingerprint,
        "audited_at": datetime.now(UTC).isoformat(),
        "attempt": attempt,
        "site_brand": SITE_BRAND,
        "blacklist_terms": terms,
        "text_violations": deduped,
        "image_violations": image_violations,
        "ignored_findings": ignored_findings,
        "unresolved_count": len(unresolved),
        "errors": errors,
    }
    fresh = db.get(KProductKnowledgeProduct, product.id)
    if fresh is not None:
        fresh.brand_audit_json = audit
        db.add(fresh)
        db.flush()
    return audit


def operator_override(audit: Any) -> dict[str, Any]:
    """运营者的「一律放行」决定（空 dict = 没有）。"""
    if not isinstance(audit, dict):
        return {}
    value = audit.get("operator_override")
    return value if isinstance(value, dict) and value.get("enabled") else {}


def audit_gate_blockers(
    db: Session,
    product: KProductKnowledgeProduct,
) -> list[str]:
    """P 上架门禁用：返回品牌相关 blocker 列表（空 = 放行）。默认 fail-closed。

    **例外：人工放行高于一切。** 2026-08-11 用户拍板——审查器是 AI，它不真正
    了解这个产品：花洒手柄上的 "STOP" 是一键止水的功能标识，它判成品牌字样；
    "panda pump" 是产品描述，它判成商标。运营者看过图、做出决定之后，
    这个控制台里不允许任何一道程序再拦他。

    所以 override 一旦打开，本门禁**无条件放行**：不看违规、不看 errors、
    也不看指纹是否过期。审查结论仍然照常计算和展示，只是不再拥有否决权。
    """
    audit = product.brand_audit_json
    override = operator_override(audit)
    if override:
        return []
    if not isinstance(audit, dict):
        return ["品牌审查未跑：先在产品页跑「品牌审查」并通过"]
    if audit.get("fingerprint") != brand_fingerprint(db, product):
        return ["内容在品牌审查后有改动：请重新跑「品牌审查」"]
    # 忽略清单权威:被人工放行的发现不再阻塞上架。errors 永不可忽略(fail-closed)。
    ignore_set = set(audit.get("ignored_findings") or [])
    text_unresolved = [
        v
        for v in (audit.get("text_violations") or [])
        if brand_finding_fingerprint("text", v) not in ignore_set
    ]
    image_unresolved = [
        v
        for v in (audit.get("image_violations") or [])
        if brand_finding_fingerprint("image", v) not in ignore_set
    ]
    errors = audit.get("errors") or []
    if not text_unresolved and not image_unresolved and not errors:
        return []
    problems = []
    for violation in text_unresolved[:5]:
        problems.append(f"{violation.get('term')}({violation.get('surface')})")
    for violation in image_unresolved[:5]:
        problems.append(f"第{violation.get('position')}张图:{violation.get('finding', '')[:60]}")
    if errors:
        problems.append(f"审查有 {len(errors)} 步失败(fail-closed)")
    return ["品牌审查未通过：" + "；".join(problems)]
