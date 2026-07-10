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
    # Per-image field wins (newer briefs carry it); older briefs only have a
    # prose global like "4:5 for product gallery; 16:9 for description".
    for raw in (spec.get("aspect_ratio"), spec.get("ratio")):
        if isinstance(raw, str):
            match = _RATIO_RE.search(raw)
            if match:
                return f"{match.group(1)}:{match.group(2)}"
    global_raw = instruction.get("aspect_ratio")
    ratios = _RATIO_RE.findall(global_raw) if isinstance(global_raw, str) else []
    if placement == PLACEMENT_DESCRIPTION:
        for width, height in ratios:
            if int(width) > int(height):
                return f"{width}:{height}"
        return "16:9"
    if channel == "amazon":
        return "1:1"
    for width, height in ratios:
        if int(width) <= int(height):
            return f"{width}:{height}"
    return "4:5"


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
                   workspace_key, business_context, scope_mode
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


def _archive_previous_render(
    db: Session,
    *,
    product_id: UUID,
    position: int,
    keep_asset_id: UUID,
) -> None:
    db.execute(
        text(
            """
            UPDATE k_product_knowledge_media_assets
            SET status = 'removed', updated_at = now()
            WHERE product_id = :product_id
              AND status = 'available'
              AND id != :keep_asset_id
              AND metadata_json->>'render_pipeline' = :tag
              AND (metadata_json->>'position')::int = :position
            """
        ),
        {
            "product_id": product_id,
            "keep_asset_id": keep_asset_id,
            "tag": RENDER_PIPELINE_TAG,
            "position": position,
        },
    )


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
    variant = _first_variant(db, product)
    product_part = product.product_key or str(product.id)
    variant_part = variant.variant_sku if variant is not None else "default"
    extension = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
    }.get(mime_type, "img")
    filename = f"{uuid4()}-render-p{int(job['position']):02d}.{extension}"
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
        status="available",
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
    _archive_previous_render(
        db,
        product_id=product.id,
        position=int(job["position"]),
        keep_asset_id=row.id,
    )
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

        main_row = next(
            (row for row in completed if row["asset_role"] == ASSET_ROLE_MAIN),
            None,
        )
        username = rows[0]["requested_by_username"]
        user = (
            db.query(User).filter(User.username == username).first()
            if username
            else None
        )
        if main_row is not None and main_row["asset_id"] is not None:
            asset = db.get(KProductKnowledgeMediaAsset, main_row["asset_id"])
            if asset is not None:
                _bind_rendered_main(db, product=product, asset=asset)
        if completed and user is not None:
            try:
                from .router import _store_image_review_snapshot

                _store_image_review_snapshot(db, product=product, user=user)
            except Exception:  # noqa: BLE001 - <5 images etc.; not fatal
                pass

        level = "info" if not failed else ("warning" if completed else "error")
        title = (
            f"一次性作图完成：{product.sku or product.product_key or product.id} "
            f"{len(completed)}/{len(rows)} 张"
        )
        body = None
        if failed:
            body = (
                "失败的图位："
                + ", ".join(str(row["position"]) for row in failed)
                + " —— 可在 K 产品页对失败图重试。"
            )
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

        # 品牌硬门闭环：成品图有更新 -> 自动入队一次品牌审查（k_generation_jobs）。
        if completed and product.marketing_copy_json:
            try:
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
                        "username": rows[0]["requested_by_username"],
                        "workspace_key": rows[0]["workspace_key"],
                        "business_context": rows[0]["business_context"],
                        "scope_mode": rows[0]["scope_mode"],
                    },
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("brand audit enqueue failed for %s", batch_id)
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
