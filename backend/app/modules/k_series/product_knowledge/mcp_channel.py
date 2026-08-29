"""K 外部精修通道(MCP)—— 业务层,不含协议。

背景(2026-08-26 拍板):K 的 worker 管线一次性出图,长期栽在「产品几何变形」
和「物理机制画错」(潜水泵搁岸上)。Codex 桌面版这类**有眼睛的代理**(内置
gpt-image-2 + 看图迭代)实测把这两处都做对了。于是给 K 加一条精修通道:外部
代理经 MCP 取简报+参考图,把成图交回来。

三条硬边界(不要在别处绕开):
1. 交回来的图走 worker 自己的 :func:`_store_render_asset` —— WebP 强转、信息层、
   派生图、完整 metadata、品牌/几何/物理审查一个不少;和 worker 出的图一视同仁。
2. 只落 ``staged``;人在控制台点「保存」才 ``available``。机器人只能交稿,不能发布。
3. 执行者是「用户管理」里注册的机器人账号;它挂哪个组织,K 的作用域就是哪个组织
   (workspace_key == org_id),不设环境变量、不问用户。

这个文件只做「取/交」,协议层在 ``backend/app/mcp``,测试直接打这里。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ....core.roles import is_super_admin_role
from ....models.org_membership import OrgMembershipRecord
from ....models.user import User
from ....services.permission_service import resolve_current_user_permission_info
from .constants import (
    DEFAULT_BUSINESS_CONTEXT,
    PERMISSION_PRODUCTS_READ,
    PERMISSION_READ,
    PERMISSION_UPDATE,
)
from .generation_jobs import enqueue_generation_jobs
from .image_render_jobs import (
    EXTERNAL_SUBMISSION_TAG,
    KImageRenderError,
    RenderPromptContext,
    _json_dumps,
    _overlay_snapshot,
    _resolve_aspect_ratio,
    _role_label,
    _spec_placement,
    _spec_seo,
    _store_render_asset,
    build_render_prompt,
    list_render_assets,
    resolve_asset_role,
    resolve_render_specs,
)
from .models import KProductKnowledgeMediaAsset, KProductKnowledgeProduct
from .scope_shim import KScopeContext, apply_scope_filters

# 单张交稿上限(解码前字节)。gpt-image-2 的 2K PNG 约 5-8MB,4K 也在此之下;
# 超过这个量基本是拼版/未压缩的意外,直接拒,别让它进后处理。
MAX_SUBMISSION_BYTES = 25 * 1024 * 1024
SUBMITTER_DEFAULT = "codex"
# router 硬编码 "production"(不是 constants.DEFAULT_SCOPE_MODE),照抄。
_SCOPE_MODE = "production"


class KMcpChannelError(KImageRenderError):
    """通道层校验失败;code 给机器看,message 给人看。"""


@dataclass(frozen=True)
class ExternalActor:
    """经 MCP 钥匙认出来的真人 + 他所有活跃组织对应的 K 作用域(owner 挂两个组织就两个)。"""

    user: User
    scopes: tuple[KScopeContext, ...]

    @property
    def scope(self) -> KScopeContext:
        return self.scopes[0]


# --- 执行者 -------------------------------------------------------------------


def scopes_for_user(db: Session, user: User) -> tuple[KScopeContext, ...]:
    memberships = db.scalars(
        select(OrgMembershipRecord)
        .where(
            OrgMembershipRecord.user_id == str(user.id),
            OrgMembershipRecord.status == "active",
        )
        .order_by(OrgMembershipRecord.joined_at.asc())
    ).all()
    return tuple(
        KScopeContext(
            workspace_key=membership.org_id,
            business_context=DEFAULT_BUSINESS_CONTEXT,
            scope_mode=_SCOPE_MODE,
        )
        for membership in memberships
    )


def actor_for_user(db: Session, user: User) -> ExternalActor:
    """钥匙认出来的 User → 执行者。没挂组织 → fail-closed(K 数据按组织隔离,没有组织就没有作用域)。"""
    if not user.is_active:
        raise KMcpChannelError("ACTOR_NOT_FOUND", f"账号「{user.username}」已停用。")
    scopes = scopes_for_user(db, user)
    if not scopes:
        raise KMcpChannelError(
            "ACTOR_ORG_MISSING",
            f"账号「{user.username}」没有挂任何组织;K 的作用域由组织决定,请让管理员在用户管理里补上。",
        )
    return ExternalActor(user=user, scopes=scopes)


def require_k_access(db: Session, user: User, *, write: bool) -> None:
    """钥匙只证明你是谁;能不能看/交稿按这个人现有的 K 权限算。
    与 router._require_k_permission 同一判据(owner/super_admin 直通,否则看权限码)。"""
    permission_key = PERMISSION_UPDATE if write else PERMISSION_READ
    info = resolve_current_user_permission_info(db, user, request=None)
    allowed = {permission_key}
    if not write:
        allowed.add(PERMISSION_PRODUCTS_READ)
    if (
        info.is_owner_full_access
        or is_super_admin_role(user.role)
        or allowed.intersection(info.permission_keys)
    ):
        return
    raise KMcpChannelError(
        "PERMISSION_DENIED",
        f"账号「{user.username}」没有 K 系列{'修改' if write else '查看'}权限({permission_key});请让管理员授权。",
        status_code=403,
    )


# --- 取 -----------------------------------------------------------------------


def _as_scopes(scope: KScopeContext | Sequence[KScopeContext]) -> tuple[KScopeContext, ...]:
    return (scope,) if isinstance(scope, KScopeContext) else tuple(scope)


def scope_of_product(
    product: KProductKnowledgeProduct,
    scopes: KScopeContext | Sequence[KScopeContext],
) -> KScopeContext:
    for candidate in _as_scopes(scopes):
        if candidate.workspace_key == product.workspace_key:
            return candidate
    return _as_scopes(scopes)[0]


def get_product_by_sku(
    db: Session,
    sku: str,
    scope: KScopeContext | Sequence[KScopeContext],
) -> KProductKnowledgeProduct:
    value = (sku or "").strip()
    if not value:
        raise KMcpChannelError("SKU_REQUIRED", "缺 sku。", status_code=422)
    product = None
    for candidate in _as_scopes(scope):
        product = db.scalars(
            apply_scope_filters(
                select(KProductKnowledgeProduct).where(KProductKnowledgeProduct.sku == value),
                KProductKnowledgeProduct,
                candidate,
            ).limit(1)
        ).first()
        if product is not None:
            break
    if product is None:
        raise KMcpChannelError(
            "PRODUCT_NOT_FOUND",
            f"K 里没有 SKU「{value}」(或不在这个机器人所属组织的作用域内)。",
            status_code=404,
        )
    return product


def reference_assets(
    db: Session,
    product: KProductKnowledgeProduct,
) -> list[KProductKnowledgeMediaAsset]:
    """原厂参考图(asset_role='reference'),按入库顺序。永远不含管线渲染图。"""
    return list(
        db.scalars(
            select(KProductKnowledgeMediaAsset)
            .where(
                KProductKnowledgeMediaAsset.product_id == product.id,
                KProductKnowledgeMediaAsset.asset_type == "image",
                KProductKnowledgeMediaAsset.asset_role == "reference",
                KProductKnowledgeMediaAsset.status == "available",
            )
            .order_by(KProductKnowledgeMediaAsset.created_at.asc())
        ).all()
    )


def reference_summaries(
    db: Session,
    product: KProductKnowledgeProduct,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in reference_assets(db, product):
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        out.append(
            {
                "asset_id": str(row.id),
                "variant_sku": row.variant_sku,
                "variant_color": str(meta.get("variant_color") or "") or None,
                "filename": str(meta.get("filename") or "") or None,
                "mime_type": row.mime_type,
                "width": row.width,
                "height": row.height,
            }
        )
    return out


def _positions_view(
    db: Session,
    product: KProductKnowledgeProduct,
) -> tuple[list[dict[str, Any]], str | None]:
    """简报里每个位号 + 现有渲染资产状态;结构错误不抛,回一句话。"""
    try:
        specs, main_position, channel = resolve_render_specs(db, product)
    except KImageRenderError as exc:
        return [], f"{exc.code}: {exc.message}"
    instruction = product.image_instruction_json
    instruction = instruction if isinstance(instruction, dict) else {}
    assets = list_render_assets(db, product)
    by_position: dict[int, list[dict[str, Any]]] = {}
    for asset in assets:
        by_position.setdefault(int(asset["position"]), []).append(asset)
    rows: list[dict[str, Any]] = []
    for position, spec in specs:
        placement = _spec_placement(spec)
        asset_role = resolve_asset_role(placement, position, main_position)
        existing = by_position.get(position, [])
        rows.append(
            {
                "position": position,
                "role": str(spec.get("role") or ""),
                "asset_role": asset_role,
                "placement": placement,
                "aspect_ratio": _resolve_aspect_ratio(spec, instruction, channel, placement),
                "variant_color": str(spec.get("variant_color") or "") or None,
                "title": str(spec.get("title") or ""),
                "has_available": any(a["status"] == "available" for a in existing),
                "has_staged": any(a["status"] == "staged" for a in existing),
            }
        )
    return rows, None


def list_products_awaiting_images(
    db: Session,
    *,
    scope: KScopeContext | Sequence[KScopeContext],
    limit: int = 20,
) -> list[dict[str, Any]]:
    """有作图简报的产品(该人所有组织合并),附每个位号的覆盖情况(哪些位还没有已保存的图)。"""
    limit = max(1, min(int(limit or 20), 100))
    products: list[KProductKnowledgeProduct] = []
    for candidate in _as_scopes(scope):
        products.extend(
            db.scalars(
                apply_scope_filters(
                    select(KProductKnowledgeProduct).where(
                        KProductKnowledgeProduct.image_instruction_json.isnot(None),
                        KProductKnowledgeProduct.review_status != "archived",
                    ),
                    KProductKnowledgeProduct,
                    candidate,
                )
                .order_by(KProductKnowledgeProduct.updated_at.desc())
                .limit(limit)
            ).all()
        )
    products.sort(key=lambda p: p.updated_at or p.created_at, reverse=True)
    products = products[:limit]
    out: list[dict[str, Any]] = []
    for product in products:
        positions, brief_error = _positions_view(db, product)
        out.append(
            {
                "sku": product.sku,
                "product_name_en": product.product_name_en,
                "brief_error": brief_error,
                "positions_total": len(positions),
                "positions_missing": [
                    p["position"] for p in positions if not p["has_available"]
                ],
                "positions_staged": [p["position"] for p in positions if p["has_staged"]],
                "reference_images": len(reference_assets(db, product)),
            }
        )
    return out


def _md_list(items: Any) -> list[str]:
    if isinstance(items, list):
        return [str(item).strip() for item in items if str(item).strip()]
    if isinstance(items, str) and items.strip():
        return [items.strip()]
    return []


def build_external_brief(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
) -> str:
    """给外部画师的 Markdown 简报。

    每张图的提示词来自 :func:`build_render_prompt` —— 和 worker 渲染时用的
    **逐字相同**(保真块永远最后一句)。这里只在外面包一层人类可读的说明:
    产品怎么工作、配件只准画哪些、交稿规则。
    """
    instruction = product.image_instruction_json
    instruction = instruction if isinstance(instruction, dict) else {}
    specs, main_position, channel = resolve_render_specs(db, product)
    context = RenderPromptContext.for_product(product)
    operating_model = instruction.get("operating_model")
    operating_model = operating_model if isinstance(operating_model, dict) else {}
    refs = reference_summaries(db, product)
    assets_by_position: dict[int, list[dict[str, Any]]] = {}
    for asset in list_render_assets(db, product):
        assets_by_position.setdefault(int(asset["position"]), []).append(asset)

    name = (product.product_name_en or product.primary_keyword or product.sku or "").strip()
    lines: list[str] = [
        f"# Image brief — {product.sku} · {name}",
        "",
        "Source: Barong Yekhna console, K series (product knowledge). "
        "This brief is generated from the same data the in-house renderer uses.",
        "",
        "## How to work with this brief",
        "",
        "1. Download every reference image listed below (`k_get_reference_images`) "
        "and feed them ALL to your image model as references. The product's pixels "
        "must come from these photos; do not invent geometry, buttons, ports, hoses or colors.",
        "2. Render ONE image per position, at the aspect ratio stated for that position. "
        "Never produce a contact sheet, never add text labels, captions or watermarks.",
        "3. Submit each image with `k_submit_image(sku, position, image_base64)`. "
        "The console converts to WebP and runs brand / geometry / physics review; "
        "nothing you submit is published — a human saves it in the console.",
        "4. After submitting, call `k_get_submission_status` and fix any finding by "
        "re-rendering and re-submitting the same position (the newer one replaces the older one at save time).",
        "",
    ]

    if operating_model:
        lines += ["## How the product works (must read)", ""]
        summary = operating_model.get("summary") or operating_model.get("how_it_works")
        if isinstance(summary, str) and summary.strip():
            lines += [summary.strip(), ""]
        hard = _md_list(operating_model.get("hard_constraints"))
        if hard:
            lines += ["Hard constraints (every non-white-background image must respect these):", ""]
            lines += [f"- {item}" for item in hard]
            lines.append("")
        forbidden = _md_list(operating_model.get("forbidden_depictions"))
        if forbidden:
            lines += ["Forbidden depictions (an image showing any of these is rejected):", ""]
            lines += [f"- {item}" for item in forbidden]
            lines.append("")

    includes = _md_list(getattr(product, "package_includes_json", None))
    lines += ["## What is in the box — the ONLY accessories you may depict", ""]
    if includes:
        lines += [f"- {item}" for item in includes]
    else:
        lines.append("- (not recorded) → depict ONLY items visible in the reference photos; add nothing.")
    lines += [
        "",
        "Do not add cloths, manuals, rings, boxes or any item that is not listed here "
        "or clearly visible in the reference photos.",
        "",
    ]

    lines += ["## Reference images", ""]
    if refs:
        for ref in refs:
            color = f" · variant color: **{ref['variant_color']}**" if ref["variant_color"] else ""
            size = f" ({ref['width']}×{ref['height']})" if ref["width"] and ref["height"] else ""
            lines.append(f"- `{ref['asset_id']}`{size}{color}")
    else:
        lines.append("- (none available — ask the operator to attach reference photos first)")
    lines += [
        "",
        "When a position carries a variant color, use the reference photo of that color "
        "as the primary reference and keep hose / shower head / accessories exactly as "
        "shown for that color variant.",
        "",
    ]

    consistency = str(instruction.get("consistency") or "").strip()
    if consistency:
        lines += ["## Consistency across the set", "", consistency, ""]
    checklist = _md_list(instruction.get("compliance_checklist"))
    if checklist:
        lines += ["## Compliance checklist", ""] + [f"- {c}" for c in checklist] + [""]

    lines += [
        "## Output rules",
        "",
        "- Gallery positions: aspect ratio 1:1, delivered at 1500×1500 or larger (2K preferred).",
        "- Description positions: aspect ratio 4:3, longest side ≥ 1500.",
        "- PNG or WebP, sRGB, no alpha needed. One image per submission, base64-encoded.",
        f"- Position **{main_position}** is the only pure-white-background image; every other image is a real scene.",
        "",
        "## Positions",
        "",
    ]
    for position, spec in specs:
        placement = _spec_placement(spec)
        asset_role = resolve_asset_role(placement, position, main_position)
        aspect = _resolve_aspect_ratio(spec, instruction, channel, placement)
        prompt = build_render_prompt(
            spec,
            instruction,
            asset_role=asset_role,
            context=context,
            position=position,
        )
        existing = assets_by_position.get(position, [])
        state = (
            "saved (available) — re-submit only if the operator asks"
            if any(a["status"] == "available" for a in existing)
            else "staged, awaiting operator save"
            if existing
            else "MISSING"
        )
        color = str(spec.get("variant_color") or "").strip()
        header = f"### Position {position} — {spec.get('role') or asset_role}"
        if color:
            header += f" · variant color: {color}"
        lines += [
            header,
            "",
            f"- placement: {placement} · asset role: {asset_role} · aspect ratio: **{aspect}**",
            f"- status in console: {state}",
        ]
        title = str(spec.get("title") or "").strip()
        if title:
            lines.append(f"- title: {title}")
        mission = str(spec.get("mission") or "").strip()
        if mission:
            lines.append(f"- mission: {mission}")
        note = str(spec.get("note") or "").strip()
        if note:
            lines.append(f"- operator note: {note}")
        lines += ["", "Prompt (use verbatim as the instruction for this image):", "", "```", prompt, "```", ""]
    return "\n".join(lines).rstrip() + "\n"


# --- 交 -----------------------------------------------------------------------


def _validate_image_bytes(contents: bytes) -> tuple[str, int, int]:
    if not contents:
        raise KMcpChannelError("IMAGE_EMPTY", "图片内容为空。", status_code=422)
    if len(contents) > MAX_SUBMISSION_BYTES:
        raise KMcpChannelError(
            "IMAGE_TOO_LARGE",
            f"单张图超过 {MAX_SUBMISSION_BYTES // (1024 * 1024)}MB;请压缩后再交(不要交拼版)。",
            status_code=413,
        )
    try:
        from PIL import Image

        with Image.open(io.BytesIO(contents)) as img:
            img.verify()
        with Image.open(io.BytesIO(contents)) as img:
            fmt = (img.format or "").lower()
            width, height = img.size
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad submission
        raise KMcpChannelError(
            "IMAGE_UNREADABLE",
            f"图片解码失败({type(exc).__name__});请交 PNG/WebP/JPEG 的 base64。",
            status_code=422,
        ) from exc
    if fmt not in {"png", "webp", "jpeg"}:
        raise KMcpChannelError(
            "IMAGE_FORMAT_UNSUPPORTED",
            f"不接受 {fmt or 'unknown'} 格式;请交 PNG/WebP/JPEG。",
            status_code=422,
        )
    return fmt, width, height


def submit_rendered_image(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    position: int,
    image_bytes: bytes,
    user: User,
    scope: KScopeContext,
    note: str | None = None,
    submitter: str = SUBMITTER_DEFAULT,
) -> dict[str, Any]:
    """外部成图 → staged 渲染资产(走 worker 同一条入库路径)→ 立刻排品牌审查。"""
    fmt, width, height = _validate_image_bytes(image_bytes)
    specs, main_position, channel = resolve_render_specs(db, product)
    spec_by_position = {p: spec for p, spec in specs}
    try:
        position = int(position)
    except (TypeError, ValueError) as exc:
        raise KMcpChannelError("POSITION_INVALID", "position 必须是整数。", status_code=422) from exc
    spec = spec_by_position.get(position)
    if spec is None:
        raise KMcpChannelError(
            "UNKNOWN_POSITION",
            f"作图指令里没有位号 {position};可用位号:{sorted(spec_by_position)}。",
            status_code=422,
        )
    instruction = product.image_instruction_json
    instruction = instruction if isinstance(instruction, dict) else {}
    placement = _spec_placement(spec)
    asset_role = resolve_asset_role(placement, position, main_position)
    prompt = build_render_prompt(
        spec,
        instruction,
        asset_role=asset_role,
        context=RenderPromptContext.for_product(product),
        position=position,
    )
    overlay = _overlay_snapshot(
        spec,
        product_id=product.id,
        position=position,
        asset_role=asset_role,
    )
    # 合成 job:_store_render_asset 只读这些键,不碰 k_image_render_jobs 表,
    # 所以 MCP 提交不建 batch 行(零副作用)。id/batch_id 只作溯源字符串。
    job: dict[str, Any] = {
        "id": uuid4(),
        "batch_id": uuid4(),
        "position": position,
        "placement": placement,
        "asset_role": asset_role,
        "role_label": _role_label(spec, overlay),
        "mission": str(spec.get("mission") or "") or None,
        "overlay_text": _json_dumps(overlay) if overlay else None,
        "aspect_ratio": _resolve_aspect_ratio(spec, instruction, channel, placement),
        "seo_json": _json_dumps(_spec_seo(spec)),
    }
    clean_note = (note or "").strip()[:500] or None
    asset = _store_render_asset(
        db,
        product=product,
        job=job,
        contents=image_bytes,
        mime_type=f"image/{fmt}",
        width=width,
        height=height,
        content_sha256="",
        prompt_used=prompt,
        user=user,
        # plate_meta 最后合并进 metadata_json —— 借它打外部通道的标记。
        plate_meta={
            "submitted_via": EXTERNAL_SUBMISSION_TAG,
            "submitter": (submitter or SUBMITTER_DEFAULT).strip()[:60],
            "submitted_by_username": user.username,
            "submission_note": clean_note,
            "submitted_source_format": fmt,
            "submitted_source_size": [width, height],
        },
    )
    audit_enqueued = False
    if product.marketing_copy_json:
        # 和 _maybe_finalize_batch / save_render_assets 同条件:有文案才审。
        _, created = enqueue_generation_jobs(
            db,
            product_ids=[product.id],
            job_type="brand_audit",
            user=user,
            scope_context=scope,
        )
        audit_enqueued = bool(created)
    meta = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    return {
        "asset_id": str(asset.id),
        "sku": product.sku,
        "position": position,
        "asset_role": asset_role,
        "placement": placement,
        "status": asset.status,
        "stored_mime_type": asset.mime_type,
        "stored_size": [asset.width, asset.height],
        "content_sha256": meta.get("content_sha256"),
        "audit_enqueued": audit_enqueued,
        "next": (
            "Staged. A human must save it in the console (K → product → 作图面板). "
            "Brand/geometry/physics review runs in the background; call "
            "k_get_submission_status in ~1-3 minutes and fix any finding for this position."
        ),
    }


# --- 查 -----------------------------------------------------------------------


def submission_status(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
) -> dict[str, Any]:
    """各位号的资产状态 + 审查发现(只挑图片类,带 category/finding)。"""
    positions, brief_error = _positions_view(db, product)
    assets = list_render_assets(db, product)
    rows = db.scalars(
        select(KProductKnowledgeMediaAsset).where(
            KProductKnowledgeMediaAsset.id.in_(
                [a["asset_id"] for a in assets] or ["00000000-0000-0000-0000-000000000000"]
            )
        )
    ).all()
    submitted_via = {
        str(row.id): (row.metadata_json or {}).get("submitted_via")
        if isinstance(row.metadata_json, dict)
        else None
        for row in rows
    }
    for asset in assets:
        asset["submitted_via"] = submitted_via.get(asset["asset_id"])
    audit = product.brand_audit_json if isinstance(product.brand_audit_json, dict) else {}
    ignored = set(_md_list(audit.get("ignored_findings")))
    findings: list[dict[str, Any]] = []
    for violation in audit.get("image_violations") or []:
        if not isinstance(violation, dict):
            continue
        fingerprint = f"image::{violation.get('position')}::{violation.get('category')}"
        findings.append(
            {
                "asset_id": violation.get("asset_id"),
                "position": violation.get("position"),
                "category": violation.get("category"),
                "finding": violation.get("finding"),
                "ignored_by_operator": fingerprint in ignored,
            }
        )
    pending = db.execute(
        text(
            """
            SELECT count(*) FROM k_generation_jobs
            WHERE product_id = :product_id AND job_type = 'brand_audit'
              AND status IN ('pending', 'running')
            """
        ),
        {"product_id": product.id},
    ).scalar()
    return {
        "sku": product.sku,
        "brief_error": brief_error,
        "positions": positions,
        "assets": assets,
        "audit": {
            "pending": int(pending or 0) > 0,
            "audited_at": audit.get("audited_at"),
            "clean": audit.get("clean"),
            "errors": audit.get("errors") or [],
            "image_findings": findings,
        },
        "note": (
            "Assets with status 'staged' are waiting for a human to save them in the console. "
            "Fix findings by re-submitting the same position."
        ),
    }


def asset_file_for_download(
    db: Session,
    *,
    asset_id: str,
    scope: KScopeContext | Sequence[KScopeContext],
) -> tuple[KProductKnowledgeMediaAsset, KProductKnowledgeProduct]:
    """参考图/成图字节面:资产必须属于该人某个作用域内的产品。"""
    asset = db.get(KProductKnowledgeMediaAsset, asset_id)
    if asset is None or asset.asset_type != "image":
        raise KMcpChannelError("ASSET_NOT_FOUND", "没有这张图。", status_code=404)
    product = None
    for candidate in _as_scopes(scope):
        product = db.scalars(
            apply_scope_filters(
                select(KProductKnowledgeProduct).where(
                    KProductKnowledgeProduct.id == asset.product_id
                ),
                KProductKnowledgeProduct,
                candidate,
            ).limit(1)
        ).first()
        if product is not None:
            break
    if product is None:
        raise KMcpChannelError("ASSET_NOT_FOUND", "没有这张图。", status_code=404)
    return asset, product


__all__ = [
    "ExternalActor",
    "KMcpChannelError",
    "MAX_SUBMISSION_BYTES",
    "asset_file_for_download",
    "build_external_brief",
    "get_product_by_sku",
    "list_products_awaiting_images",
    "reference_assets",
    "reference_summaries",
    "actor_for_user",
    "require_k_access",
    "scope_of_product",
    "scopes_for_user",
    "submission_status",
    "submit_rendered_image",
]
