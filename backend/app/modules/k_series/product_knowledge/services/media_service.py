"""媒体资产：本地文件定位、读取、尺寸与快照。

从 router 剥出来的第 4 桶（2026-09-03）。

⚠️ `_path_within_root` 是**越界防护** —— 它挡住 `../` 这类路径穿越，把媒体
读取限制在存储根目录内。搬运时一字未改；改它之前先想清楚。

`MediaAssetRead` 本来内联在 router 里。一度想用 `TYPE_CHECKING` 前向引用蒙混
过去 —— 错了：`_media_asset_read` 在函数体里**真的 construct 它**，不只是写在
标注里。静态检查看不出这个区别（标注在 `from __future__ import annotations`
下确实是惰性的），是 e2e 集成测试报 NameError 才暴露的。

同一处还追着踩了第二脚：搬过来之后 pydantic 报「`MediaAssetRead` is not fully
defined; you should define `datetime`」—— 字段标注里用了 `datetime`，而
`from __future__ import annotations` 把标注变成字符串，pydantic 建模时要**真的
解析**它。静态检查同样看不见这层。所以下面那个 `datetime` import 是必需的，
不是没用的残留。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime  # noqa: F401 - MediaAssetRead 的字段标注要它
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from ..models import KProductKnowledgeMediaAsset
from .common import _stable_payload_digest

logger = logging.getLogger(__name__)


class MediaAssetRead(BaseModel):
    id: str
    product_id: str
    variant_sku: str | None
    asset_type: str
    asset_role: str
    status: str
    review_status: str
    object_key: str | None
    file_url_placeholder: str | None
    file_url: str | None
    thumbnail_url: str | None
    preview_url: str | None
    mime_type: str | None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    source: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


def _media_storage_root() -> Path:
    return Path(os.getenv("K_PRODUCT_MEDIA_STORAGE_DIR", "/var/lib/barong/k-media"))


SUPPORTED_IMAGE_MIME_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}

RESERVED_MEDIA_METADATA_KEYS = {
    "content_sha256",
    "db_content_base64",
    "direct_binary_upload",
    "preview_path",
    "storage_path",
    "storage_provider",
    "storage_relative_path",
    "thumbnail_path",
}


def _image_dimensions(contents: bytes) -> tuple[int | None, int | None]:
    """Best-effort pixel dimensions. Metadata only — never fails an upload.

    画廊/描述分流按纵横比走(画廊只放方形),所以手动上传也必须记下真实
    像素尺寸,否则组包时无从判断该图是横版/竖版还是方形。
    """
    from io import BytesIO

    try:
        from PIL import Image

        with Image.open(BytesIO(contents)) as img:
            return int(img.width), int(img.height)
    except Exception:  # noqa: BLE001 - dimensions are metadata, not a gate
        logger.exception("Failed to read uploaded image dimensions")
        return None, None


def _public_media_metadata(metadata: Any) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    redacted = {
        key: value
        for key, value in metadata.items()
        if key not in {"db_content_base64", "storage_path", "thumbnail_path", "preview_path"}
    }
    return redacted


def _path_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _media_asset_local_path(row: KProductKnowledgeMediaAsset) -> Path | None:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    root = _media_storage_root().resolve(strict=False)
    candidates: list[Path] = []
    storage_path_value = metadata.get("storage_path")
    if (
        row.storage_provider == "local_filesystem"
        or metadata.get("storage_provider") == "local_filesystem"
    ) and storage_path_value:
        candidates.append(Path(str(storage_path_value)))
    if row.object_key:
        candidates.append(root / row.object_key)

    for candidate in candidates:
        path = candidate if candidate.is_absolute() else root / candidate
        resolved = path.resolve(strict=False)
        if _path_within_root(resolved, root):
            return resolved
    return None


def _media_asset_requires_local_file(row: KProductKnowledgeMediaAsset) -> bool:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    return (
        row.storage_provider == "local_filesystem"
        or metadata.get("storage_provider") == "local_filesystem"
        or metadata.get("direct_binary_upload") is True
    )


def _media_asset_file_info(row: KProductKnowledgeMediaAsset) -> dict[str, Any]:
    path = _media_asset_local_path(row)
    if path is None:
        return {"file_available": False, "file_size": None}
    try:
        stat = path.stat()
    except OSError:
        return {"file_available": False, "file_size": None}
    return {
        "file_available": path.is_file(),
        "file_size": stat.st_size if path.is_file() else None,
    }


def _media_asset_read(
    row: KProductKnowledgeMediaAsset,
    *,
    product_ref: str | None = None,
    include_metadata: bool = False,
) -> MediaAssetRead:
    file_url = (
        row.file_url_placeholder
        if row.file_url_placeholder and not row.object_key
        else f"/k/media/{row.id}/file"
    )
    thumbnail_url = (
        row.file_url_placeholder
        if row.file_url_placeholder and not row.object_key
        else f"/k/media/{row.id}/thumbnail"
    )
    preview_url = (
        row.file_url_placeholder
        if row.file_url_placeholder and not row.object_key
        else f"/k/media/{row.id}/preview"
    )
    return MediaAssetRead(
        id=str(row.id),
        product_id=product_ref or str(row.product_id),
        variant_sku=row.variant_sku,
        asset_type=row.asset_type,
        asset_role=row.asset_role,
        status=row.status,
        review_status=row.review_status,
        object_key=row.object_key,
        file_url_placeholder=row.file_url_placeholder,
        file_url=file_url,
        thumbnail_url=thumbnail_url,
        preview_url=preview_url,
        mime_type=row.mime_type,
        width=row.width,
        height=row.height,
        file_size=row.file_size,
        source=row.source,
        metadata=_public_media_metadata(row.metadata_json) if include_metadata else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _active_media_snapshot(
    db: Session,
    product: KProductKnowledgeProduct,
) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(KProductKnowledgeMediaAsset)
            .where(
                KProductKnowledgeMediaAsset.product_id == product.id,
                KProductKnowledgeMediaAsset.status != "removed",
            )
            .order_by(
                KProductKnowledgeMediaAsset.variant_sku.asc(),
                KProductKnowledgeMediaAsset.object_key.asc(),
                KProductKnowledgeMediaAsset.id.asc(),
            )
        )
    )
    items = []
    usable_count = 0
    for row in rows:
        file_info = _media_asset_file_info(row)
        requires_local_file = _media_asset_requires_local_file(row)
        file_available = (
            file_info["file_available"]
            if requires_local_file
            else bool(row.file_url_placeholder or row.object_key)
        )
        if file_available:
            usable_count += 1
        items.append(
            {
                "asset_role": row.asset_role,
                "asset_type": row.asset_type,
                "file_available": file_available,
                "file_size": file_info["file_size"] or row.file_size,
                "id": str(row.id),
                "object_key": row.object_key,
                "review_status": row.review_status,
                "source": row.source,
                "status": row.status,
                "storage_provider": row.storage_provider,
                "variant_sku": row.variant_sku,
            }
        )
    payload = {"active_count": len(items), "count": usable_count, "items": items}
    return {**payload, "digest": _stable_payload_digest(payload)}


def _image_asset_for_product(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    asset_id: UUID,
) -> KProductKnowledgeMediaAsset:
    asset = (
        db.query(KProductKnowledgeMediaAsset)
        .filter(
            KProductKnowledgeMediaAsset.id == asset_id,
            KProductKnowledgeMediaAsset.product_id == product.id,
        )
        .one_or_none()
    )
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image asset not found for this product.",
        )
    return asset
