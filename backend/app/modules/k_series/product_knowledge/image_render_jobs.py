"""One-shot product image rendering: K art-direction brief -> real images.

P 图片体系阶段 2+3. Endpoints enqueue one row per image of the product's
``image_instruction_json.images[]`` into ``k_image_render_jobs`` (the row
snapshots the final prompt, placement, SEO fields and aspect ratio, so a brief
regeneration cannot shift an in-flight render). The k-worker claims pending
rows (FOR UPDATE SKIP LOCKED) and renders each image through the I-series
gpt-image-2 *edit* path -- the product's real photo is the immutable reference,
AI only paints scene/background -- then stores the result as a K media asset
whose ``metadata_json`` carries placement/position/title/alt/caption/description
so the P upload stage can split gallery images from description-embedded images
and push the WordPress media SEO fields.

Reference photo resolution order (the original product photo is sacred; a
previously *rendered* image must never become the next render's reference):
1. ``product.reference_image_url`` (R->K 搬运带来的原图外链, downloaded
   server-side against a host whitelist);
2. the earliest available K image asset NOT produced by this pipeline.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ....db.session import SessionLocal
from ....models.user import User
from ....modules.notifications.service import create_notification
from ....services.media_store import ensure_image_derivative, write_media_file
from ...i_series.image_system.constants import SOURCE_EDIT
from ...i_series.image_system.service import IImageModelEngine
from .models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeVariant,
)
from .scope_shim import KScopeContext
from .workflow_engine import IMAGE_SOURCE_I_SYSTEM, _user_uuid

_TABLE = "k_image_render_jobs"
_LOGGER = logging.getLogger("k-image-render")

RENDER_PIPELINE_TAG = "k_auto_render"

PLACEMENT_GALLERY = "gallery"
PLACEMENT_DESCRIPTION = "description"

ASSET_ROLE_MAIN = "main"
ASSET_ROLE_GALLERY = "gallery"
ASSET_ROLE_DESCRIPTION = "description"

# Barong Yekhna 视觉家规（代码层强制）：干净产品图（主图/画廊图）背景必须是
# 明亮暖白、背景比产品亮 2 档、左上柔光、接触阴影、产品是唯一变量——绝不发灰。
# 出图前对这两类角色的 prompt 无条件追加，作为 AI 作图指令跑偏时的兜底。
# 场景图（description）保留其环境镜头，不套此白底块。详见
# skills/product-image-art-direction/SKILL.md §0。
_HOUSE_STYLE_ROLES = (ASSET_ROLE_MAIN, ASSET_ROLE_GALLERY)
_HOUSE_STYLE_MARKER = "Barong Yekhna house rule"
HOUSE_STYLE_BLOCK = (
    "\n\nSTYLE BLOCK (Barong Yekhna house rule — clean product shot, "
    "non-negotiable): Premium e-commerce product photography. Single product "
    "centered on a seamless BRIGHT warm off-white studio background (near "
    "#F7F6F4), the background lit two stops brighter than the product so the "
    "ground is clean bright white, never grey. Soft, even, diffused light from "
    "the upper left; a soft subtle contact shadow directly beneath the product. "
    "Generous negative space, product centered at a consistent scale. Crisp "
    "focus, true-to-life vivid saturated product colour. Clean, airy, high-end "
    "catalog aesthetic. No props, no text, no clutter. CONSISTENCY: same "
    "product as the reference image — do not alter product shape, colour, or "
    "markings."
)

# R->K 参考图外链只可能来自这些图源 (Amazon CDN 现在, 1688/alicdn 之后).
REFERENCE_URL_HOST_SUFFIXES = (
    "media-amazon.com",
    "ssl-images-amazon.com",
    "images-amazon.com",
    "alicdn.com",
)
_REFERENCE_DOWNLOAD_TIMEOUT_SECONDS = 20.0
_REFERENCE_MAX_BYTES = 20 * 1024 * 1024

_RATIO_RE = re.compile(r"(\d{1,2})\s*:\s*(\d{1,2})")


class KImageRenderError(RuntimeError):
    """Enqueue-time validation failure (message is operator-facing Chinese)."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _render_concurrency(value: int | None = None) -> int:
    if value is None:
        value = int(os.getenv("K_IMAGE_RENDER_CONCURRENCY", "3"))
    return max(1, min(value, 8))


def _poll_seconds() -> float:
    return max(1.0, float(os.getenv("K_IMAGE_RENDER_POLL_SECONDS", "3")))


# --- brief parsing ----------------------------------------------------------

def _instruction_images(product: KProductKnowledgeProduct) -> list[dict[str, Any]]:
    instruction = product.image_instruction_json
    if not isinstance(instruction, dict):
        return []
    images = instruction.get("images")
    if not isinstance(images, list):
        return []
    return [item for item in images if isinstance(item, dict)]


def _spec_position(spec: dict[str, Any], fallback: int) -> int:
    try:
        return int(spec.get("position"))
    except (TypeError, ValueError):
        return fallback


def _spec_placement(spec: dict[str, Any]) -> str:
    placement = str(spec.get("placement") or "").strip().lower()
    return (
        PLACEMENT_DESCRIPTION
        if placement == PLACEMENT_DESCRIPTION
        else PLACEMENT_GALLERY
    )


def _resolve_aspect_ratio(
    spec: dict[str, Any],
    instruction: dict[str, Any],
    channel: str,
    placement: str,
) -> str:
    # 硬规则：主副图（gallery）一律 1:1 —— 存储时统一放大到 1800×1800。
    if placement == PLACEMENT_GALLERY:
        return "1:1"
    # 描述图：每图字段优先，退回全局说明里的横版比例，默认 16:9。
    for raw in (spec.get("aspect_ratio"), spec.get("ratio")):
        if isinstance(raw, str):
            match = _RATIO_RE.search(raw)
            if match:
                return f"{match.group(1)}:{match.group(2)}"
    global_raw = instruction.get("aspect_ratio")
    ratios = _RATIO_RE.findall(global_raw) if isinstance(global_raw, str) else []
    for width, height in ratios:
        if int(width) > int(height):
            return f"{width}:{height}"
    return "16:9"


def _compose_prompt(spec: dict[str, Any], instruction: dict[str, Any]) -> str:
    prompt = str(spec.get("prompt") or "").strip()
    style_block = str(instruction.get("style_block") or "").strip()
    if style_block and "STYLE BLOCK" not in prompt.upper():
        prompt = f"{prompt}\n\n{style_block}" if prompt else style_block
    overlay = str(spec.get("overlay_text") or "").strip()
    if overlay and overlay.lower() not in prompt.lower():
        prompt += (
            "\n\nOVERLAY TEXT (render this exact text on the image, correctly "
            f'spelled, clean typography): "{overlay}"'
        )
    return prompt


def _spec_seo(spec: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(spec.get(key) or "").strip()
        for key in ("title", "alt", "caption", "description")
    }


# --- reference photo --------------------------------------------------------

def reference_url_host_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in REFERENCE_URL_HOST_SUFFIXES
    )


def download_reference_image(url: str) -> tuple[str, bytes, str]:
    """Download the external reference photo. Returns (filename, bytes, mime)."""
    if not reference_url_host_allowed(url):
        raise KImageRenderError(
            "REFERENCE_URL_NOT_ALLOWED",
            "参考图外链域名不在白名单内，无法安全下载。",
            status_code=422,
        )
    with httpx.Client(
        timeout=_REFERENCE_DOWNLOAD_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        contents = response.content
    if not contents or len(contents) > _REFERENCE_MAX_BYTES:
        raise KImageRenderError(
            "REFERENCE_DOWNLOAD_INVALID",
            "参考图下载为空或超过大小上限。",
            status_code=422,
        )
    mime = _detect_image_mime(contents)
    if mime is None:
        raise KImageRenderError(
            "REFERENCE_NOT_IMAGE",
            "参考图外链返回的不是图片。",
            status_code=422,
        )
    filename = os.path.basename(urlparse(url).path) or "reference"
    return filename, contents, mime


def _detect_image_mime(contents: bytes) -> str | None:
    if contents.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contents.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(contents) >= 12 and contents[0:4] == b"RIFF" and contents[8:12] == b"WEBP":
        return "image/webp"
    return None


def _media_storage_root_path() -> Path:
    return Path(os.getenv("K_PRODUCT_MEDIA_STORAGE_DIR", "/var/lib/barong/k-media"))


def _original_photo_assets(
    db: Session,
    product: KProductKnowledgeProduct,
) -> list[KProductKnowledgeMediaAsset]:
    rows = db.scalars(
        select(KProductKnowledgeMediaAsset)
        .where(
            KProductKnowledgeMediaAsset.product_id == product.id,
            KProductKnowledgeMediaAsset.asset_type == "image",
            KProductKnowledgeMediaAsset.status == "available",
        )
        .order_by(KProductKnowledgeMediaAsset.created_at.asc())
    ).all()
    originals = []
    for row in rows:
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if metadata.get("render_pipeline") == RENDER_PIPELINE_TAG:
            continue
        originals.append(row)
    # Prefer the bound/main photo as the canonical reference.
    originals.sort(key=lambda row: 0 if row.asset_role == ASSET_ROLE_MAIN else 1)
    return originals


def _asset_file_bytes(row: KProductKnowledgeMediaAsset) -> tuple[str, bytes, str] | None:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    root = _media_storage_root_path()
    if row.object_key:
        path = root / row.object_key
        if path.is_file():
            contents = path.read_bytes()
            mime = _detect_image_mime(contents) or row.mime_type or "image/png"
            return path.name, contents, mime
    encoded = metadata.get("db_content_base64")
    if isinstance(encoded, str) and encoded.strip():
        try:
            contents = base64.b64decode(encoded, validate=True)
        except Exception:  # noqa: BLE001
            return None
        mime = _detect_image_mime(contents) or row.mime_type or "image/png"
        return f"asset-{row.id}", contents, mime
    return None


def _resolve_reference_image(
    db: Session,
    product: KProductKnowledgeProduct,
) -> tuple[str, bytes, str]:
    if product.reference_image_url:
        reference_url = product.reference_image_url
        # Release the read transaction before the slow external download so the
        # DB doesn't kill the connection on idle-in-transaction timeout.
        db.commit()
        try:
            return download_reference_image(reference_url)
        except Exception as exc:  # noqa: BLE001 - fall through to stored assets
            _LOGGER.warning(
                "reference url download failed for product %s: %s",
                product.id,
                exc,
            )
    for row in _original_photo_assets(db, product):
        resolved = _asset_file_bytes(row)
        if resolved is not None:
            return resolved
    raise KImageRenderError(
        "REFERENCE_IMAGE_MISSING",
        "产品没有可用的作图参考图：请先上传/绑定产品原图，或从 R 搬运带参考图。",
        status_code=409,
    )


def reference_available(db: Session, product: KProductKnowledgeProduct) -> bool:
    if product.reference_image_url and reference_url_host_allowed(
        product.reference_image_url
    ):
        return True
    return bool(_original_photo_assets(db, product))


# --- enqueue + status (request path) ----------------------------------------

def enqueue_image_render_jobs(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    user: User | None,
    scope_context: KScopeContext,
    positions: Sequence[int] | None = None,
    brand_removal_hints: dict[int, str] | None = None,
) -> tuple[UUID, list[dict[str, Any]]]:
    instruction = product.image_instruction_json
    images = _instruction_images(product)
    if not images:
        raise KImageRenderError(
            "IMAGE_BRIEF_REQUIRED",
            "请先生成作图指令（image_instruction），再一次性作图。",
        )
    if not reference_available(db, product):
        raise KImageRenderError(
            "REFERENCE_IMAGE_MISSING",
            "产品没有可用的作图参考图：请先上传/绑定产品原图，或从 R 搬运带参考图。",
        )
    in_flight = db.execute(
        text(
            f"""
            SELECT count(*) FROM {_TABLE}
            WHERE product_id = :product_id AND status IN ('pending', 'running')
            """
        ),
        {"product_id": product.id},
    ).scalar()
    if int(in_flight or 0) > 0:
        raise KImageRenderError(
            "RENDER_IN_PROGRESS",
            "这个产品已有作图任务在跑，等它完成或失败后再试。",
        )

    specs: list[tuple[int, dict[str, Any]]] = []
    for index, spec in enumerate(images, start=1):
        specs.append((_spec_position(spec, index), spec))
    known_positions = {position for position, _ in specs}
    wanted: set[int] | None = None
    if positions:
        wanted = {int(p) for p in positions}
        unknown = wanted - known_positions
        if unknown:
            raise KImageRenderError(
                "UNKNOWN_POSITIONS",
                f"作图指令里没有这些图的位置：{sorted(unknown)}",
                status_code=422,
            )

    gallery_positions = [
        position
        for position, spec in specs
        if _spec_placement(spec) == PLACEMENT_GALLERY
    ]
    main_position = min(gallery_positions) if gallery_positions else None
    channel = (product.channel or "dtc").strip().lower()

    # 品牌红线：每张图都带移除指令；已知品牌词/审查检出位置追加强化提示
    from .brand_guard import BRAND_REMOVAL_PROMPT_BLOCK, normalized_brand_terms

    brand_terms = normalized_brand_terms(product)
    batch_id = uuid4()
    created: list[dict[str, Any]] = []
    for position, spec in sorted(specs, key=lambda item: item[0]):
        if wanted is not None and position not in wanted:
            continue
        prompt = _compose_prompt(spec, instruction if isinstance(instruction, dict) else {})
        if not prompt:
            raise KImageRenderError(
                "IMAGE_PROMPT_MISSING",
                f"第 {position} 张图缺 prompt，请重新生成作图指令。",
                status_code=422,
            )
        prompt += BRAND_REMOVAL_PROMPT_BLOCK
        if brand_terms:
            prompt += (
                " Known brand marks that may appear on the reference product "
                f"and MUST be removed: {', '.join(brand_terms)}."
            )
        hint = (brand_removal_hints or {}).get(position)
        if hint:
            prompt += (
                f" A previous render of this image FAILED brand review: {hint}"
                " — make absolutely sure that mark is gone this time."
            )
        placement = _spec_placement(spec)
        if placement == PLACEMENT_DESCRIPTION:
            asset_role = ASSET_ROLE_DESCRIPTION
        elif position == main_position:
            asset_role = ASSET_ROLE_MAIN
        else:
            asset_role = ASSET_ROLE_GALLERY
        # 视觉家规兜底：干净产品图（主图/画廊图）无条件套明亮暖白家规块，
        # 保证全线出图统一、绝不发灰——即便 AI 作图指令漂移到别的风格。
        if asset_role in _HOUSE_STYLE_ROLES and _HOUSE_STYLE_MARKER not in prompt:
            prompt += HOUSE_STYLE_BLOCK
        job_id = uuid4()
        db.execute(
            text(
                f"""
                INSERT INTO {_TABLE}
                    (id, product_id, batch_id, position, placement, role_label,
                     asset_role, mission, prompt, overlay_text, aspect_ratio,
                     seo_json, status, requested_by_username,
                     workspace_key, business_context, scope_mode)
                VALUES
                    (:id, :product_id, :batch_id, :position, :placement, :role_label,
                     :asset_role, :mission, :prompt, :overlay_text, :aspect_ratio,
                     CAST(:seo_json AS jsonb), 'pending', :username,
                     :workspace_key, :business_context, :scope_mode)
                """
            ),
            {
                "id": job_id,
                "product_id": product.id,
                "batch_id": batch_id,
                "position": position,
                "placement": placement,
                "role_label": str(spec.get("role") or "")[:128] or None,
                "asset_role": asset_role,
                "mission": str(spec.get("mission") or "") or None,
                "prompt": prompt,
                "overlay_text": str(spec.get("overlay_text") or "") or None,
                "aspect_ratio": _resolve_aspect_ratio(
                    spec,
                    instruction if isinstance(instruction, dict) else {},
                    channel,
                    placement,
                ),
                "seo_json": _json_dumps(_spec_seo(spec)),
                "username": user.username if user is not None else None,
                "workspace_key": scope_context.workspace_key,
                "business_context": scope_context.business_context,
                "scope_mode": scope_context.scope_mode,
            },
        )
        created.append(_job_dict(job_id, batch_id, position, placement, asset_role))
    if not created:
        raise KImageRenderError(
            "NO_IMAGES_SELECTED",
            "没有选中任何要渲染的图。",
            status_code=422,
        )
    return batch_id, created


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _job_dict(
    job_id: UUID,
    batch_id: UUID,
    position: int,
    placement: str,
    asset_role: str,
) -> dict[str, Any]:
    return {
        "job_id": str(job_id),
        "batch_id": str(batch_id),
        "position": position,
        "placement": placement,
        "asset_role": asset_role,
        "status": "pending",
        "error": None,
        "asset_id": None,
    }


def render_jobs_status(
    db: Session,
    *,
    product_id: UUID,
    batch_id: UUID | None = None,
) -> dict[str, Any]:
    # 惰性清理：staged 超 24h 未保存的挂载图（页面在轮询，这里是天然触发点）
    try:
        cleanup_stale_staged(db, product_id)
    except Exception:  # noqa: BLE001
        pass
    if batch_id is None:
        batch_id = db.execute(
            text(
                f"""
                SELECT batch_id FROM {_TABLE}
                WHERE product_id = :product_id
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"product_id": product_id},
        ).scalar()
    if batch_id is None:
        return {"batch_id": None, "jobs": [], "summary": _summary([])}
    rows = db.execute(
        text(
            f"""
            SELECT id, batch_id, position, placement, role_label, asset_role,
                   status, error, asset_id, started_at, finished_at
            FROM {_TABLE}
            WHERE product_id = :product_id AND batch_id = :batch_id
            ORDER BY position ASC
            """
        ),
        {"product_id": product_id, "batch_id": batch_id},
    ).mappings().all()
    jobs = [
        {
            "job_id": str(row["id"]),
            "batch_id": str(row["batch_id"]),
            "position": row["position"],
            "placement": row["placement"],
            "role_label": row["role_label"],
            "asset_role": row["asset_role"],
            "status": row["status"],
            "error": row["error"],
            "asset_id": str(row["asset_id"]) if row["asset_id"] else None,
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "finished_at": (
                row["finished_at"].isoformat() if row["finished_at"] else None
            ),
        }
        for row in rows
    ]
    return {"batch_id": str(batch_id), "jobs": jobs, "summary": _summary(jobs)}


def _summary(jobs: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(jobs), "pending": 0, "running": 0, "completed": 0, "failed": 0}
    for job in jobs:
        status = job["status"]
        if status in summary:
            summary[status] += 1
    return summary


def retry_failed_render_jobs(
    db: Session,
    *,
    product_id: UUID,
    batch_id: UUID,
) -> int:
    result = db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'pending', error = NULL, finalized = false,
                started_at = NULL, finished_at = NULL, updated_at = now()
            WHERE product_id = :product_id AND batch_id = :batch_id
              AND status = 'failed'
            """
        ),
        {"product_id": product_id, "batch_id": batch_id},
    )
    if result.rowcount:
        # Reset the batch's finalize marker so the retried run re-finalizes.
        db.execute(
            text(
                f"""
                UPDATE {_TABLE}
                SET finalized = false, updated_at = now()
                WHERE batch_id = :batch_id
                """
            ),
            {"batch_id": batch_id},
        )
    return result.rowcount or 0


# --- worker side -------------------------------------------------------------

def _claim_pending_jobs(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT id, product_id, batch_id, position, placement, role_label,
                   asset_role, mission, prompt, overlay_text, aspect_ratio,
                   seo_json, requested_by_username,
                   workspace_key, business_context, scope_mode,
                   reference_asset_id
            FROM {_TABLE}
            WHERE status = 'pending'
            ORDER BY created_at ASC, position ASC
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"limit": limit},
    ).mappings().all()
    if not rows:
        return []
    ids = [row["id"] for row in rows]
    db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'running', started_at = now(), attempts = attempts + 1,
                updated_at = now()
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": ids},
    )
    db.commit()
    return [dict(row) for row in rows]


def _set_job_status(
    job_id: UUID,
    status: str,
    *,
    error: str | None = None,
    asset_id: UUID | None = None,
) -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                f"""
                UPDATE {_TABLE}
                SET status = :status, error = :error, asset_id = :asset_id,
                    finished_at = now(), updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "status": status, "error": error, "asset_id": asset_id},
        )
        db.commit()


def _error_text(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message.strip():
            return message[:1000]
        return str(detail)[:1000]
    if isinstance(detail, str) and detail.strip():
        return detail[:1000]
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message.strip():
        return message[:1000]
    return str(exc)[:1000]


def _first_variant(
    db: Session,
    product: KProductKnowledgeProduct,
) -> KProductKnowledgeVariant | None:
    return db.scalars(
        select(KProductKnowledgeVariant)
        .where(KProductKnowledgeVariant.product_id == product.id)
        .order_by(KProductKnowledgeVariant.created_at.asc())
        .limit(1)
    ).first()


# 主副图硬规格：1800×1800；所有成品图硬规格：webp。
GALLERY_TARGET_SIDE = 1800
_WEBP_QUALITY = 92


def _postprocess_rendered_image(
    contents: bytes,
    placement: str,
) -> tuple[bytes, str, int, int]:
    """渲染成品统一后处理：gallery 放大到 1800×1800，全部转 webp。"""
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(contents)) as img:
        img = img.convert("RGB")
        if placement == PLACEMENT_GALLERY:
            img = img.resize(
                (GALLERY_TARGET_SIDE, GALLERY_TARGET_SIDE),
                Image.LANCZOS,
            )
        buffer = BytesIO()
        img.save(buffer, format="WEBP", quality=_WEBP_QUALITY, method=6)
        return buffer.getvalue(), "image/webp", img.width, img.height


def _store_render_asset(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    job: dict[str, Any],
    contents: bytes,
    mime_type: str,
    width: int | None,
    height: int | None,
    content_sha256: str,
    prompt_used: str,
    user: User | None,
) -> KProductKnowledgeMediaAsset:
    del mime_type, width, height  # superseded by the mandatory post-process
    contents, mime_type, width, height = _postprocess_rendered_image(
        contents, str(job["placement"])
    )
    content_sha256 = hashlib.sha256(contents).hexdigest()
    variant = _first_variant(db, product)
    product_part = product.product_key or str(product.id)
    variant_part = variant.variant_sku if variant is not None else "default"
    filename = f"{uuid4()}-render-p{int(job['position']):02d}.webp"
    object_key = f"images/{product_part}/{variant_part}/k-render/{filename}"
    root = _media_storage_root_path()
    storage_file = write_media_file(root, object_key, contents)
    thumbnail_path, thumbnail_object_key, _ = ensure_image_derivative(
        root=root,
        object_key=object_key,
        kind="thumbnail",
        max_side=320,
        contents=contents,
    )
    preview_path, preview_object_key, _ = ensure_image_derivative(
        root=root,
        object_key=object_key,
        kind="preview",
        max_side=1280,
        contents=contents,
    )

    seo_raw = job.get("seo_json")
    if isinstance(seo_raw, str):
        try:
            seo = json.loads(seo_raw)
        except ValueError:
            seo = {}
    elif isinstance(seo_raw, dict):
        seo = seo_raw
    else:
        seo = {}
    if not isinstance(seo, dict):
        seo = {}

    user_id = _user_uuid(user) if user is not None else None
    row = KProductKnowledgeMediaAsset(
        id=uuid4(),
        product_id=product.id,
        variant_id=variant.id if variant is not None else None,
        variant_sku=variant.variant_sku if variant is not None else None,
        asset_type="image",
        asset_role=str(job["asset_role"]),
        # 暂存态：用户点「保存」才转 available（入硬门/审查/上架包）；
        # 24 小时未保存自动清除。
        status="staged",
        review_status="i_system_managed",
        storage_provider="local_filesystem",
        object_key=object_key,
        file_url_placeholder=None,
        file_size=len(contents),
        mime_type=mime_type,
        width=width,
        height=height,
        source=IMAGE_SOURCE_I_SYSTEM,
        metadata_json={
            # P 上架分流 + WordPress media SEO 字段 (flat, 阶段4 直接读).
            "placement": job["placement"],
            "position": int(job["position"]),
            "title": str(seo.get("title") or ""),
            "alt": str(seo.get("alt") or ""),
            "caption": str(seo.get("caption") or ""),
            "description": str(seo.get("description") or ""),
            "overlay_text": job.get("overlay_text") or "",
            "mission": job.get("mission") or "",
            "role_label": job.get("role_label") or "",
            # provenance
            "render_pipeline": RENDER_PIPELINE_TAG,
            "render_job_id": str(job["id"]),
            "render_batch_id": str(job["batch_id"]),
            "staged_at": datetime.now(UTC).isoformat(),
            "aspect_ratio": job.get("aspect_ratio"),
            "image_prompt_enhanced": prompt_used,
            "source_type": IMAGE_SOURCE_I_SYSTEM,
            "content_sha256": content_sha256,
            "filename": filename,
            "product_key": product.product_key,
            "product_id": str(product.id),
            "variant_id": str(variant.id) if variant is not None else None,
            "variant_sku": variant.variant_sku if variant is not None else None,
            "sku": product.sku,
            "k_image_ai_generation_allowed": False,
            "k_image_review_allowed": False,
            "storage_provider": "local_filesystem",
            "storage_relative_path": object_key,
            "storage_path": str(storage_file),
            "preview_object_key": preview_object_key,
            "preview_path": str(preview_path),
            "thumbnail_object_key": thumbnail_object_key,
            "thumbnail_path": str(thumbnail_path),
        },
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )
    db.add(row)
    db.flush()
    # 注意：同 position 旧图的归档发生在「保存」时（save_render_assets），
    # 暂存阶段新旧并存，用户看图后决定保存哪张。
    return row


def _process_render_job(job: dict[str, Any]) -> None:
    job_id = job["id"]
    asset_id: UUID | None = None
    try:
        with SessionLocal() as db:
            username = job.get("requested_by_username")
            user = (
                db.query(User).filter(User.username == username).first()
                if username
                else None
            )
            product = db.get(KProductKnowledgeProduct, job["product_id"])
            if product is None:
                raise KImageRenderError("PRODUCT_NOT_FOUND", "产品不存在或已删除。")
            # 单张重做可指定“以某张已生成图为参考”（在其基础上修改）
            reference = None
            if job.get("reference_asset_id"):
                ref_asset = db.get(
                    KProductKnowledgeMediaAsset, job["reference_asset_id"]
                )
                if ref_asset is not None:
                    reference = _asset_file_bytes(ref_asset)
            if reference is None:
                reference = _resolve_reference_image(db, product)
            prompt = str(job["prompt"])
            engine = IImageModelEngine(db)
            # request=None: key resolution goes through the module execution
            # gate with the explicit I-series org (same as the K worker's
            # request=None generate calls).
            candidates = engine.generate_candidates(
                event_id=job_id,
                source_type=SOURCE_EDIT,
                image_prompt_enhanced=prompt,
                aspect_ratio=str(job["aspect_ratio"] or "1:1"),
                generation_count=1,
                request=None,  # type: ignore[arg-type]
                user=user,  # type: ignore[arg-type]
                reference_image_count=1,
                reference_images=[reference],
            )
            if not candidates:
                raise KImageRenderError(
                    "RENDER_EMPTY_RESULT",
                    "图片模型没有返回任何图片。",
                )
            candidate = candidates[0]
            contents = base64.b64decode(candidate.image_base64)
            asset = _store_render_asset(
                db,
                product=product,
                job=job,
                contents=contents,
                mime_type=candidate.mime_type or "image/png",
                width=candidate.width,
                height=candidate.height,
                content_sha256=(
                    candidate.content_sha256
                    or hashlib.sha256(contents).hexdigest()
                ),
                prompt_used=prompt,
                user=user,
            )
            asset_id = asset.id
            db.commit()
        _set_job_status(job_id, "completed", asset_id=asset_id)
    except Exception as exc:  # noqa: BLE001 - isolate one image's failure
        _LOGGER.warning("render job %s failed: %s", job_id, exc)
        _set_job_status(job_id, "failed", error=_error_text(exc))
    finally:
        try:
            _maybe_finalize_batch(job["batch_id"])
        except Exception:  # noqa: BLE001
            _LOGGER.exception("batch finalize failed for %s", job["batch_id"])


def _maybe_finalize_batch(batch_id: UUID) -> None:
    """When every job in the batch is terminal, bind the main image, submit the
    K image section, and drop a console notification. FOR UPDATE on the batch
    rows serializes competing finishers; the `finalized` flag makes it one-shot.
    """
    with SessionLocal() as db:
        rows = db.execute(
            text(
                f"""
                SELECT id, product_id, position, placement, asset_role, status,
                       asset_id, finalized, requested_by_username,
                       workspace_key, business_context, scope_mode
                FROM {_TABLE}
                WHERE batch_id = :batch_id
                ORDER BY position ASC
                FOR UPDATE
                """
            ),
            {"batch_id": batch_id},
        ).mappings().all()
        if not rows:
            return
        if any(row["status"] in {"pending", "running"} for row in rows):
            return
        if all(row["finalized"] for row in rows):
            return
        db.execute(
            text(
                f"""
                UPDATE {_TABLE}
                SET finalized = true, updated_at = now()
                WHERE batch_id = :batch_id
                """
            ),
            {"batch_id": batch_id},
        )

        product = db.get(KProductKnowledgeProduct, rows[0]["product_id"])
        if product is None:
            db.commit()
            return
        completed = [row for row in rows if row["status"] == "completed"]
        failed = [row for row in rows if row["status"] == "failed"]

        # 成品先进「暂存区」：绑定主图 / 归档旧图 / 品牌审查全部推迟到
        # 用户点「保存」（save_render_assets）—— 没保存的图对系统不存在。

        level = "info" if not failed else ("warning" if completed else "error")
        title = (
            f"一次性作图完成：{product.sku or product.product_key or product.id} "
            f"{len(completed)}/{len(rows)} 张待保存"
        )
        body = None
        if failed:
            body = (
                "失败的图位："
                + ", ".join(str(row["position"]) for row in failed)
                + " —— 可在 K 产品页对失败图重试。"
            )
        elif completed:
            body = "去 K 产品页预览，满意的图点「保存」才会正式入库（24 小时未保存自动清除）。"
        try:
            create_notification(
                db,
                event_type="k.image_render.finished",
                title=title,
                body=body,
                level=level,
                source="k.image_render",
                product_id=product.id,
                payload={
                    "batch_id": str(batch_id),
                    "completed": len(completed),
                    "failed_positions": [row["position"] for row in failed],
                    "total": len(rows),
                },
            )
        except Exception:  # noqa: BLE001 - notification must not sink the batch
            _LOGGER.exception("render notification failed for %s", batch_id)
        db.commit()


def _bind_rendered_main(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    asset: KProductKnowledgeMediaAsset,
) -> None:
    product.selected_image_path = asset.object_key
    product.image_asset_status = "bound"
    product.media_notes_json = {
        **(product.media_notes_json or {}),
        "bound_asset_id": str(asset.id),
        "image_source_type": IMAGE_SOURCE_I_SYSTEM,
        "variant_id": str(asset.variant_id) if asset.variant_id else None,
        "variant_sku": asset.variant_sku,
        "bound_at": datetime.now(UTC).isoformat(),
        "render_pipeline": RENDER_PIPELINE_TAG,
        "object_key": asset.object_key,
        "original_url": f"/k/media/{asset.id}/file",
        "preview_url": f"/k/media/{asset.id}/preview",
        "thumbnail_url": f"/k/media/{asset.id}/thumbnail",
    }
    db.add(product)


# --- 暂存 / 保存 / 单张重做 -------------------------------------------------

STAGED_TTL_HOURS = 24


def cleanup_stale_staged(db: Session, product_id: UUID | None = None) -> int:
    """惰性清理：staged 超过 24 小时未保存的成品图删除（防意外刷新丢失
    的挂载期结束）。在查询/入队等触发点顺手调用。"""
    clause = "AND product_id = :product_id" if product_id is not None else ""
    params: dict[str, Any] = {"tag": RENDER_PIPELINE_TAG}
    if product_id is not None:
        params["product_id"] = product_id
    result = db.execute(
        text(
            f"""
            UPDATE k_product_knowledge_media_assets
            SET status = 'removed', updated_at = now()
            WHERE status = 'staged'
              AND metadata_json->>'render_pipeline' = :tag
              AND (metadata_json->>'staged_at')::timestamptz
                  < now() - interval '{STAGED_TTL_HOURS} hours'
              {clause}
            """
        ),
        params,
    )
    return result.rowcount or 0


def list_render_assets(
    db: Session,
    product: KProductKnowledgeProduct,
) -> list[dict[str, Any]]:
    """渲染面板的资产视图：staged + available 并存（按 position）。"""
    rows = db.scalars(
        select(KProductKnowledgeMediaAsset)
        .where(
            KProductKnowledgeMediaAsset.product_id == product.id,
            KProductKnowledgeMediaAsset.asset_type == "image",
            KProductKnowledgeMediaAsset.status.in_(("staged", "available")),
        )
        .order_by(KProductKnowledgeMediaAsset.created_at.asc())
    ).all()
    out = []
    for row in rows:
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if meta.get("render_pipeline") != RENDER_PIPELINE_TAG:
            continue
        out.append(
            {
                "asset_id": str(row.id),
                "position": int(meta.get("position") or 0),
                "placement": meta.get("placement") or "gallery",
                "asset_role": row.asset_role,
                "status": row.status,
                "role_label": meta.get("role_label") or "",
                "staged_at": meta.get("staged_at"),
            }
        )
    out.sort(key=lambda item: (item["position"], item["status"]))
    return out


def mirror_saved_to_i_library(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    asset: KProductKnowledgeMediaAsset,
    user: User | None,
) -> None:
    """K 里保存的渲染图镜像进 I 系列媒体库——图本来就是 I 引擎生成的，
    资产归属上理应在 I 媒体库可见。字节复制到 I 存储（backend 同时挂
    k-media 和 i-media 两个卷），image_id 确定性（k-render-{K资产id}）
    保证幂等。仅在「保存」时调用——暂存图不进任何媒体库。"""
    from ...i_series.image_system.constants import (
        DEFAULT_BUSINESS_CONTEXT as I_BUSINESS_CONTEXT,
        DEFAULT_SCOPE_MODE as I_SCOPE_MODE,
        MEDIA_BUCKET_EDITED,
        ORIGIN_K_HANDOFF,
        SOURCE_EDIT as I_SOURCE_EDIT,
        TARGET_ORGANIZATION_NAME as I_ORGANIZATION_NAME,
    )
    from ...i_series.image_system.models import IImageAsset
    from ...i_series.image_system.service import (
        image_storage_root,
        target_organization,
        write_media_cache,
    )

    # I 媒体库列表按请求组织过滤（workspace_key=org_id）——镜像必须挂
    # I 的目标组织，否则在媒体库里不可见。
    i_workspace_key = target_organization(db).org_id

    image_id = f"k-render-{asset.id}"
    existing = db.scalar(
        select(IImageAsset).where(IImageAsset.image_id == image_id)
    )
    if existing is not None:
        if existing.status == "REMOVED":
            existing.status = "STORED"
            existing.removed_at = None
            db.add(existing)
        return

    loaded = _asset_file_bytes(asset)
    if loaded is None:
        _LOGGER.warning("I-library mirror skipped, file missing: %s", asset.id)
        return
    _filename, contents, mime = loaded
    meta = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    filename = str(meta.get("filename") or f"{image_id}.webp")
    object_key = (
        f"I_MEDIA_LIBRARY/{MEDIA_BUCKET_EDITED}/"
        f"{i_workspace_key}/{image_id}/{filename}"
    )
    write_media_cache(object_key, contents)
    ensure_image_derivative(
        root=image_storage_root(),
        object_key=object_key,
        kind="thumbnail",
        max_side=320,
        contents=contents,
    )
    ensure_image_derivative(
        root=image_storage_root(),
        object_key=object_key,
        kind="preview",
        max_side=1280,
        contents=contents,
    )
    db.add(
        IImageAsset(
            image_id=image_id,
            workspace_key=i_workspace_key,
            business_context=I_BUSINESS_CONTEXT,
            scope_mode=I_SCOPE_MODE,
            organization_name=I_ORGANIZATION_NAME,
            product_id=product.id,
            variant_id=asset.variant_id,
            source_type=I_SOURCE_EDIT,
            origin_context=ORIGIN_K_HANDOFF,
            status="STORED",
            media_bucket=MEDIA_BUCKET_EDITED,
            prompt_original=None,
            image_prompt_enhanced=str(
                meta.get("image_prompt_enhanced") or "K 一次性作图渲染成品"
            ),
            aspect_ratio=str(meta.get("aspect_ratio") or "") or None,
            filename=filename,
            object_key=object_key,
            storage_provider="local_filesystem",
            mime_type=mime,
            width=asset.width,
            height=asset.height,
            file_size=len(contents),
            content_sha256=hashlib.sha256(contents).hexdigest(),
            metadata_json={
                "k_render_mirror": True,
                "k_asset_id": str(asset.id),
                "k_product_id": str(product.id),
                "position": meta.get("position"),
                "placement": meta.get("placement"),
                "title": meta.get("title"),
                "alt": meta.get("alt"),
                "caption": meta.get("caption"),
                "description": meta.get("description"),
                "sku": product.sku,
            },
            created_by_user_id=_user_uuid(user) if user is not None else None,
        )
    )


def save_render_assets(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    user: User | None,
    scope_context: KScopeContext,
    asset_ids: Sequence[UUID] | None = None,
) -> dict[str, Any]:
    """把暂存图正式入库：staged→available、归档同 position 其它渲染图、
    绑定主图、入队品牌审查。asset_ids=None 表示全部保存。"""
    query = select(KProductKnowledgeMediaAsset).where(
        KProductKnowledgeMediaAsset.product_id == product.id,
        KProductKnowledgeMediaAsset.status == "staged",
    )
    if asset_ids:
        query = query.where(KProductKnowledgeMediaAsset.id.in_(list(asset_ids)))
    staged = [
        row
        for row in db.scalars(query).all()
        if isinstance(row.metadata_json, dict)
        and row.metadata_json.get("render_pipeline") == RENDER_PIPELINE_TAG
    ]
    if not staged:
        raise KImageRenderError(
            "NOTHING_TO_SAVE", "没有待保存的暂存图。", status_code=409
        )

    saved: list[dict[str, Any]] = []
    main_asset: KProductKnowledgeMediaAsset | None = None
    for row in staged:
        meta = dict(row.metadata_json)
        position = int(meta.get("position") or 0)
        row.status = "available"
        meta.pop("staged_at", None)
        row.metadata_json = meta
        db.add(row)
        db.flush()
        # 同 position 的其它渲染图（旧 available + 其它 staged 候选）归档
        replaced = db.execute(
            text(
                """
                UPDATE k_product_knowledge_media_assets
                SET status = 'removed', updated_at = now()
                WHERE product_id = :product_id
                  AND status IN ('available', 'staged')
                  AND id != :keep_id
                  AND metadata_json->>'render_pipeline' = :tag
                  AND (metadata_json->>'position')::int = :position
                RETURNING id
                """
            ),
            {
                "product_id": product.id,
                "keep_id": row.id,
                "tag": RENDER_PIPELINE_TAG,
                "position": position,
            },
        ).scalars().all()
        # 被替换旧图的 I 媒体库镜像同步下架
        if replaced:
            db.execute(
                text(
                    """
                    UPDATE i_image_system_assets
                    SET status = 'REMOVED', removed_at = now(), updated_at = now()
                    WHERE image_id = ANY(:image_ids)
                    """
                ),
                {"image_ids": [f"k-render-{rid}" for rid in replaced]},
            )
        if row.asset_role == ASSET_ROLE_MAIN:
            main_asset = row
        # 资产归属：图是 I 引擎生成的，保存时镜像进 I 媒体库
        try:
            mirror_saved_to_i_library(db, product=product, asset=row, user=user)
        except Exception:  # noqa: BLE001 - 镜像失败不阻塞保存主流程
            _LOGGER.exception("I-library mirror failed for %s", row.id)
        saved.append({"asset_id": str(row.id), "position": position})

    if main_asset is not None:
        _bind_rendered_main(db, product=product, asset=main_asset)
    if user is not None:
        try:
            from .router import _store_image_review_snapshot

            _store_image_review_snapshot(db, product=product, user=user)
        except Exception:  # noqa: BLE001 - <5 images etc.; not fatal
            pass

    # 内容正式变化 -> 品牌审查（老审查指纹随之失效）
    if product.marketing_copy_json:
        db.execute(
            text(
                """
                INSERT INTO k_generation_jobs
                    (id, product_id, job_type, status, batch_id,
                     requested_by_username, workspace_key,
                     business_context, scope_mode)
                VALUES
                    (:id, :product_id, 'brand_audit', 'pending', :batch_id,
                     :username, :workspace_key, :business_context, :scope_mode)
                """
            ),
            {
                "id": uuid4(),
                "product_id": product.id,
                "batch_id": uuid4(),
                "username": user.username if user is not None else None,
                "workspace_key": scope_context.workspace_key,
                "business_context": scope_context.business_context,
                "scope_mode": scope_context.scope_mode,
            },
        )
    return {"saved": saved, "audit_enqueued": bool(product.marketing_copy_json)}


def enqueue_rework_job(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    user: User | None,
    scope_context: KScopeContext,
    asset_id: UUID,
    extra_prompt: str,
    use_current_as_reference: bool,
) -> tuple[UUID, dict[str, Any]]:
    """单张图重做：原 prompt + 临时 REVISION 指令（冲突以新指令为准，不写回
    作图指令）。参考图二选一：这版图本身（在其基础上改）或产品原始参考图。"""
    asset = db.get(KProductKnowledgeMediaAsset, asset_id)
    if (
        asset is None
        or str(asset.product_id) != str(product.id)
        or asset.status not in ("staged", "available")
        or not isinstance(asset.metadata_json, dict)
        or asset.metadata_json.get("render_pipeline") != RENDER_PIPELINE_TAG
    ):
        raise KImageRenderError(
            "REWORK_ASSET_NOT_FOUND", "要重做的图不存在或不可重做。", status_code=404
        )
    extra = (extra_prompt or "").strip()
    if not extra:
        raise KImageRenderError(
            "REWORK_PROMPT_REQUIRED", "请填写这张图的修改要求。", status_code=422
        )
    meta = asset.metadata_json
    base_prompt = str(meta.get("image_prompt_enhanced") or "").strip()
    if not base_prompt:
        raise KImageRenderError(
            "REWORK_PROMPT_MISSING", "原图缺少 prompt 快照，无法重做。", status_code=409
        )
    prompt = base_prompt + (
        "\n\nREVISION (temporary instruction for THIS regeneration only; if it "
        "conflicts with anything above, THIS revision wins): "
        + extra
    )
    if use_current_as_reference:
        prompt += (
            "\nThe attached reference image IS the previous accepted version of "
            "this exact image — keep its composition, style, and content, and "
            "apply ONLY the revision above."
        )

    position = int(meta.get("position") or 0)
    seo = {
        key: str(meta.get(key) or "")
        for key in ("title", "alt", "caption", "description")
    }
    batch_id = uuid4()
    job_id = uuid4()
    db.execute(
        text(
            f"""
            INSERT INTO {_TABLE}
                (id, product_id, batch_id, position, placement, role_label,
                 asset_role, mission, prompt, overlay_text, aspect_ratio,
                 seo_json, status, requested_by_username,
                 workspace_key, business_context, scope_mode,
                 reference_asset_id)
            VALUES
                (:id, :product_id, :batch_id, :position, :placement, :role_label,
                 :asset_role, :mission, :prompt, :overlay_text, :aspect_ratio,
                 CAST(:seo_json AS jsonb), 'pending', :username,
                 :workspace_key, :business_context, :scope_mode,
                 :reference_asset_id)
            """
        ),
        {
            "id": job_id,
            "product_id": product.id,
            "batch_id": batch_id,
            "position": position,
            "placement": meta.get("placement") or PLACEMENT_GALLERY,
            "role_label": str(meta.get("role_label") or "")[:128] or None,
            "asset_role": asset.asset_role,
            "mission": str(meta.get("mission") or "") or None,
            "prompt": prompt,
            "overlay_text": str(meta.get("overlay_text") or "") or None,
            "aspect_ratio": str(meta.get("aspect_ratio") or "1:1"),
            "seo_json": _json_dumps(seo),
            "username": user.username if user is not None else None,
            "workspace_key": scope_context.workspace_key,
            "business_context": scope_context.business_context,
            "scope_mode": scope_context.scope_mode,
            "reference_asset_id": asset.id if use_current_as_reference else None,
        },
    )
    return batch_id, _job_dict(job_id, batch_id, position, str(meta.get("placement") or PLACEMENT_GALLERY), asset.asset_role)


class KImageRenderWorker:
    """Polls k_image_render_jobs and renders claimed images in a thread pool."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        concurrency: int | None = None,
        poll_seconds: float | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.concurrency = _render_concurrency(concurrency)
        self.poll_seconds = poll_seconds if poll_seconds is not None else _poll_seconds()

    def run_once(self, *, log: Callable[[str], None] | None = None) -> bool:
        with self.session_factory() as db:
            jobs = _claim_pending_jobs(db, self.concurrency)
        if not jobs:
            return False
        if log:
            log(
                f"K image render: claimed {len(jobs)} job(s), "
                f"concurrency={self.concurrency}"
            )
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = [executor.submit(_process_render_job, job) for job in jobs]
            for future in futures:
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001
                    if log:
                        log(f"K image render job crashed: {exc}")
        return True

    def run_forever(
        self,
        *,
        should_stop: Callable[[], bool],
        log: Callable[[str], None] | None = None,
    ) -> None:
        if log:
            log(
                f"K image render worker started concurrency={self.concurrency} "
                f"poll={self.poll_seconds:g}s"
            )
        while not should_stop():
            try:
                did_work = self.run_once(log=log)
            except Exception as exc:  # noqa: BLE001
                if log:
                    log(f"K image render worker loop error: {exc}")
                did_work = False
            if not did_work:
                time.sleep(self.poll_seconds)


def requeue_stale_render_jobs(db: Session, *, older_than_seconds: int = 1800) -> int:
    """Reset render jobs stuck in 'running' (e.g. after a worker restart)."""
    result = db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'pending', updated_at = now()
            WHERE status = 'running'
              AND started_at < now() - (:secs || ' seconds')::interval
            """
        ),
        {"secs": str(older_than_seconds)},
    )
    db.commit()
    return result.rowcount or 0
