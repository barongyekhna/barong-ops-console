"""版式渲染（缺口单第一条道）：像素级排版，不碰 AI。

K 的成品图是方图，Pinterest 要 2:3、Instagram 要 4:5。硬裁会裁掉产品，所以把
方图放在家规暖白底（#F7F6F4）上补成竖图，顶部叠一行 ≤8 词的标题，底部一行
品牌字。纯字卡（导购没场景图时）同一套画布。

产物存成 K 媒体资产 ``asset_role="social_layout"``，血统标记
``metadata.render_pipeline = "sm_layout"``，挂在源产品下，用 K 现成的
``/k/media/{id}/preview`` 出图；每平台每源图最多 3 个变体（近重复降权）。
"""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...services.media_store import ensure_image_derivative, storage_path, write_media_file
from ..k_series.product_knowledge.info_overlay import _font, _wrapped_text
from ..k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeVariant,
)
from ..k_series.product_knowledge.services.media_service import _media_storage_root
from .constants import (
    ASSET_ROLE_SOCIAL_LAYOUT,
    LAYOUT_PIPELINE_TAG,
    MAX_LAYOUT_VARIANTS_PER_SOURCE,
)

try:  # Pillow 在 backend 镜像里有；单测环境可能没有
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]

HOUSE_BACKGROUND = (247, 246, 244)  # K 视觉家规的明亮暖白
HOUSE_INK = (27, 26, 24)
HOUSE_MUTED = (122, 132, 129)
BRAND_WORDMARK = "BARONG YEKHNA"
CANVAS: dict[str, tuple[int, int]] = {"2:3": (1000, 1500), "4:5": (1080, 1350), "1:1": (1080, 1080)}
_WEBP_QUALITY = 82
MAX_HEADLINE_WORDS = 8


class LayoutError(RuntimeError):
    pass


def _require_pillow() -> None:
    if Image is None:
        raise LayoutError("Pillow 不可用，版式渲染无法执行。")


def clamp_headline(text: str) -> str:
    words = [w for w in str(text or "").split() if w]
    return " ".join(words[:MAX_HEADLINE_WORDS])


def _draw_headline(draw: Any, canvas_w: int, y: int, text: str, *, max_height: int) -> int:
    """顶部标题：字号从大到小试，直到面积 ≤ 允许高度。返回占用高度。"""
    if not text:
        return 0
    pad = int(canvas_w * 0.08)
    for size in range(int(canvas_w * 0.075), 28, -4):
        font = _font(size)
        wrapped = _wrapped_text(draw, text, font, canvas_w - pad * 2)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=int(size * 0.25))
        height = bbox[3] - bbox[1]
        if height <= max_height:
            draw.multiline_text(
                (pad, y), wrapped, font=font, fill=HOUSE_INK, spacing=int(size * 0.25), align="left"
            )
            return height
    font = _font(28)
    wrapped = _wrapped_text(draw, text, font, canvas_w - pad * 2)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=7)
    draw.multiline_text((pad, y), wrapped, font=font, fill=HOUSE_INK, spacing=7)
    return bbox[3] - bbox[1]


def _draw_wordmark(draw: Any, canvas_w: int, canvas_h: int) -> int:
    size = max(20, int(canvas_w * 0.022))
    font = _font(size)
    text = "  ".join(BRAND_WORDMARK)  # 字距
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    y = canvas_h - int(canvas_h * 0.045) - height
    draw.text(((canvas_w - width) / 2, y), text, font=font, fill=HOUSE_MUTED)
    return canvas_h - y


def render_card(
    source: bytes | None,
    *,
    ratio: str,
    headline: str = "",
    lines: list[str] | None = None,
) -> bytes:
    """方图 → 竖图卡；source 为 None 时是纯字卡。返回 WebP 字节。"""
    _require_pillow()
    canvas_w, canvas_h = CANVAS.get(ratio, CANVAS["2:3"])
    canvas = Image.new("RGB", (canvas_w, canvas_h), HOUSE_BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    top_pad = int(canvas_h * 0.06)
    headline = clamp_headline(headline)
    # 叠字面积 ≤ 30%：标题最多占画布高度 22%，其余留给图和品牌字。
    used = _draw_headline(draw, canvas_w, top_pad, headline, max_height=int(canvas_h * 0.22))
    wordmark_h = _draw_wordmark(draw, canvas_w, canvas_h)
    body_top = top_pad + used + int(canvas_h * 0.03)
    body_bottom = canvas_h - wordmark_h - int(canvas_h * 0.03)
    if source is not None:
        image = Image.open(io.BytesIO(source)).convert("RGB")
        box_w = canvas_w - int(canvas_w * 0.10)
        box_h = max(64, body_bottom - body_top)
        scale = min(box_w / image.width, box_h / image.height)
        new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
        x = (canvas_w - new_size[0]) // 2
        y = body_top + (box_h - new_size[1]) // 2
        canvas.paste(image, (x, y))
    elif lines:
        # 纯字卡：要点逐行
        pad = int(canvas_w * 0.08)
        size = max(28, int(canvas_w * 0.04))
        font = _font(size)
        y = body_top
        for line in lines[:6]:
            wrapped = _wrapped_text(draw, f"• {line}", font, canvas_w - pad * 2)
            draw.multiline_text((pad, y), wrapped, font=font, fill=HOUSE_INK, spacing=int(size * 0.3))
            bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=int(size * 0.3))
            y += (bbox[3] - bbox[1]) + int(size * 0.8)
            if y > body_bottom:
                break
    out = io.BytesIO()
    canvas.save(out, format="WEBP", quality=_WEBP_QUALITY, method=6)
    return out.getvalue()


# ---------------------------------------------------------------- 存取


def load_asset_bytes(asset: KProductKnowledgeMediaAsset) -> bytes:
    if not asset.object_key:
        raise LayoutError("源资产没有 object_key。")
    path = storage_path(_media_storage_root(), asset.object_key)
    if not path.is_file():
        raise LayoutError(f"源资产文件不存在：{asset.object_key}")
    return path.read_bytes()


def existing_variant_count(
    db: Session, *, source_asset_id: UUID | None, platform: str
) -> int:
    if source_asset_id is None:
        return 0
    rows = db.execute(
        select(KProductKnowledgeMediaAsset).where(
            KProductKnowledgeMediaAsset.asset_role == ASSET_ROLE_SOCIAL_LAYOUT,
            KProductKnowledgeMediaAsset.status != "removed",
        )
    ).scalars()
    count = 0
    for row in rows:
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if meta.get("source_asset_id") == str(source_asset_id) and meta.get("platform") == platform:
            count += 1
    return count


def store_layout_asset(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    contents: bytes,
    platform: str,
    pillar: str,
    ratio: str,
    headline: str,
    source_asset_id: UUID | None,
    kind: str,
    user_id: int | None = None,
) -> KProductKnowledgeMediaAsset:
    """把渲染结果落成 K 资产（available；不进 K 的渲染面板）。"""
    if existing_variant_count(db, source_asset_id=source_asset_id, platform=platform) >= MAX_LAYOUT_VARIANTS_PER_SOURCE:
        raise LayoutError("这张源图在该平台的版式变体已达上限（近重复会被降权）。")
    variant = db.scalars(
        select(KProductKnowledgeVariant)
        .where(KProductKnowledgeVariant.product_id == product.id)
        .order_by(KProductKnowledgeVariant.created_at.asc())
        .limit(1)
    ).first()
    variant_part = variant.variant_sku if variant is not None else "default"
    product_part = product.product_key or str(product.id)
    filename = f"{uuid4()}-sm-{platform}-{pillar.lower()}.webp"
    object_key = f"images/{product_part}/{variant_part}/sm-layout/{filename}"
    root: Path = _media_storage_root()
    storage_file = write_media_file(root, object_key, contents)
    _thumb_path, thumb_key, _ = ensure_image_derivative(
        root=root, object_key=object_key, kind="thumbnail", max_side=320, contents=contents
    )
    _preview_path, preview_key, _ = ensure_image_derivative(
        root=root, object_key=object_key, kind="preview", max_side=1280, contents=contents
    )
    width, height = CANVAS.get(ratio, CANVAS["2:3"])
    row = KProductKnowledgeMediaAsset(
        id=uuid4(),
        product_id=product.id,
        variant_id=variant.id if variant is not None else None,
        variant_sku=variant.variant_sku if variant is not None else None,
        asset_type="image",
        asset_role=ASSET_ROLE_SOCIAL_LAYOUT,
        status="available",
        review_status="not_applicable",
        storage_provider="local_filesystem",
        object_key=object_key,
        file_url_placeholder=None,
        file_size=len(contents),
        mime_type="image/webp",
        width=width,
        height=height,
        source=LAYOUT_PIPELINE_TAG,
        metadata_json={
            "render_pipeline": LAYOUT_PIPELINE_TAG,
            "kind": kind,  # card | text_card
            "platform": platform,
            "pillar": pillar,
            "ratio": ratio,
            "headline": headline,
            "source_asset_id": str(source_asset_id) if source_asset_id else None,
            "content_sha256": hashlib.sha256(contents).hexdigest(),
            "filename": filename,
            "storage_provider": "local_filesystem",
            "storage_relative_path": object_key,
            "storage_path": str(storage_file),
            "preview_object_key": preview_key,
            "thumbnail_object_key": thumb_key,
            "product_key": product.product_key,
            "product_id": str(product.id),
            "sku": product.sku,
            "k_image_ai_generation_allowed": False,
            "k_image_review_allowed": False,
            "created_at": datetime.now(UTC).isoformat(),
            "created_by_user_id": user_id,
        },
    )
    db.add(row)
    db.flush()
    return row


def render_from_asset(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    source_asset: KProductKnowledgeMediaAsset,
    platform: str,
    pillar: str,
    ratio: str,
    headline: str,
    user_id: int | None = None,
) -> KProductKnowledgeMediaAsset:
    contents = render_card(load_asset_bytes(source_asset), ratio=ratio, headline=headline)
    return store_layout_asset(
        db, product=product, contents=contents, platform=platform, pillar=pillar, ratio=ratio,
        headline=headline, source_asset_id=source_asset.id, kind="card", user_id=user_id,
    )


def render_text_card(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    platform: str,
    pillar: str,
    ratio: str,
    headline: str,
    lines: list[str],
    user_id: int | None = None,
) -> KProductKnowledgeMediaAsset:
    contents = render_card(None, ratio=ratio, headline=headline, lines=lines)
    return store_layout_asset(
        db, product=product, contents=contents, platform=platform, pillar=pillar, ratio=ratio,
        headline=headline, source_asset_id=None, kind="text_card", user_id=user_id,
    )


__all__ = [
    "CANVAS",
    "LayoutError",
    "clamp_headline",
    "render_card",
    "render_from_asset",
    "render_text_card",
    "store_layout_asset",
]
