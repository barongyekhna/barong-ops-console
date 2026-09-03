"""图片：上传校验、MIME 探测、base64 解码、审阅快照。

从 router 剥出来的第 6 桶（2026-09-03）。

⚠️ `_validate_uploaded_image` / `_detect_image_mime` 是**上传入口的守门人** ——
它们决定什么字节能进媒体库。搬运时一字未改。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

import base64

from datetime import UTC, datetime
from fastapi import HTTPException, status
from sqlalchemy import select
from uuid import UUID
from ..constants import MODULE_KEY
from ..models import KProductKnowledgeProduct, KProductKnowledgeVariant
from ..services.api_support import _structured_execution_error_detail
from ..services.common import _product_ai_warnings
from ..services.media_service import _active_media_snapshot
from ..services.product_repo import (
    ProductSectionState,
    _active_keyword_snapshot,
    _product_readiness,
)
from ..workflow_engine import _user_uuid

class KeywordEntry(BaseModel):
    id: str
    product_id: str
    keyword: str
    source: str
    status: str
    created_at: datetime
    updated_at: datetime


class RiskTermEntry(BaseModel):
    id: str
    product_id: str
    term: str
    risk_level: str
    category: str
    source: str
    status: str
    created_at: datetime
    updated_at: datetime


def _product_variants_by_product_ids(
    db: Session,
    product_ids: Sequence[UUID],
) -> dict[UUID, list[KProductKnowledgeVariant]]:
    if not product_ids:
        return {}

    grouped: dict[UUID, list[KProductKnowledgeVariant]] = {
        product_id: [] for product_id in product_ids
    }
    variants = db.scalars(
        select(KProductKnowledgeVariant)
        .where(KProductKnowledgeVariant.product_id.in_(product_ids))
        .order_by(
            KProductKnowledgeVariant.product_id.asc(),
            KProductKnowledgeVariant.created_at.asc(),
        )
    )
    for variant in variants:
        grouped.setdefault(variant.product_id, []).append(variant)
    return grouped


def _variant_by_id(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    variant_id: UUID,
) -> KProductKnowledgeVariant:
    variant = db.get(KProductKnowledgeVariant, variant_id)
    if variant is None or variant.product_id != product.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant was not found for this product.",
        )
    return variant


def _product_public_ref(product: KProductKnowledgeProduct) -> str:
    return product.product_key or str(product.id)


def _k19_status_from_model(status_value: str) -> str:
    mapping = {
        "approved": "active",
        "candidate": "suggested",
        "removed": "archived",
        "rejected": "archived",
    }
    return mapping.get(status_value, "suggested")


def _keyword_entry(
    db: Session,
    keyword: KProductKnowledgeKeyword,
) -> KeywordEntry:
    product = db.get(KProductKnowledgeProduct, keyword.product_id)
    return KeywordEntry(
        id=str(keyword.id),
        product_id=_product_public_ref(product) if product else str(keyword.product_id),
        keyword=keyword.keyword_text,
        source=keyword.source,
        status=_k19_status_from_model(keyword.status),
        created_at=keyword.created_at,
        updated_at=keyword.updated_at,
    )


def _k20_status_from_model(status_value: str) -> str:
    mapping = {
        "candidate": "active",
        "confirmed": "resolved",
        "false_positive": "ignored",
        "removed": "ignored",
    }
    return mapping.get(status_value, "active")


def _risk_entry(db: Session, risk: KProductKnowledgeRiskTerm) -> RiskTermEntry:
    product = db.get(KProductKnowledgeProduct, risk.product_id)
    risk_parts = (risk.risk_type or "marketing").split(":", 1)
    risk_level = risk_parts[0] if len(risk_parts) == 2 else "low"
    category = risk_parts[1] if len(risk_parts) == 2 else risk_parts[0]
    return RiskTermEntry(
        id=str(risk.id),
        product_id=_product_public_ref(product) if product else str(risk.product_id),
        term=risk.term_en,
        risk_level=risk_level,
        category=category,
        source=risk.source,
        status=_k20_status_from_model(risk.status),
        created_at=risk.created_at,
        updated_at=risk.updated_at,
    )


def _detect_image_mime(contents: bytes) -> str | None:
    if contents.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contents.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if (
        len(contents) >= 12
        and contents[0:4] == b"RIFF"
        and contents[8:12] == b"WEBP"
    ):
        return "image/webp"
    return None


def _validate_uploaded_image(contents: bytes, declared_mime: str | None) -> str:
    detected_mime = _detect_image_mime(contents)
    if detected_mime is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is not a supported image.",
        )
    normalized_declared = (declared_mime or "").split(";", 1)[0].strip().lower()
    if normalized_declared and normalized_declared not in {
        detected_mime,
        "application/octet-stream",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image MIME type does not match the file contents.",
        )
    return detected_mime


def _decode_image_base64(value: str) -> bytes:
    raw = value.strip()
    if raw.startswith("data:"):
        _, _, raw = raw.partition(",")
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image payload is not valid base64.",
        ) from exc


def _db_image_bytes_from_metadata(row: KProductKnowledgeMediaAsset) -> bytes | None:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    encoded = metadata.get("db_content_base64")
    if not isinstance(encoded, str) or not encoded.strip():
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(UTC)


def _store_keyword_review_snapshot(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    execution: Any | None = None,
    user: User | None = None,
) -> ProductSectionState:
    snapshot = _active_keyword_snapshot(db, product)
    if int(snapshot.get("count") or 0) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_structured_execution_error_detail(
                reason="invalid_state",
                code="KEYWORD_SECTION_INCOMPLETE",
                message="At least one active non-risk keyword is required before submitting keywords.",
                module_id=MODULE_KEY,
            ),
        )
    reviewed_at = _now().isoformat()
    marker = {
        "status": "submitted",
        "submitted_at": reviewed_at,
        "keyword_digest": snapshot["digest"],
        "keyword_count": snapshot["count"],
        "submitted_by_user_id": (
            str(_user_uuid(user)) if user is not None and _user_uuid(user) else None
        ),
    }
    if execution is not None:
        marker["execution_id"] = str(execution.id)
    product.ai_warnings_json = {**_product_ai_warnings(product), "keyword_review": marker}
    if execution is not None and isinstance(execution.risk_approval_log_json, dict):
        execution.risk_approval_log_json = {
            **execution.risk_approval_log_json,
            "keyword_digest": snapshot["digest"],
            "keyword_count": snapshot["count"],
        }
        db.add_all([product, execution])
    else:
        db.add(product)
    db.flush()
    return _product_readiness(db, product).keywords


def _store_image_review_snapshot(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    user: User,
) -> ProductSectionState:
    snapshot = _active_media_snapshot(db, product)
    if int(snapshot.get("count") or 0) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_structured_execution_error_detail(
                reason="missing_context",
                code="IMAGE_SECTION_INCOMPLETE",
                message="At least 5 active images are required before submitting images.",
                module_id=MODULE_KEY,
            ),
        )
    submitted_at = _now().isoformat()
    product.ai_warnings_json = {
        **_product_ai_warnings(product),
        "image_review": {
            "status": "submitted",
            "submitted_at": submitted_at,
            "submitted_by_user_id": str(_user_uuid(user)) if _user_uuid(user) else None,
            "media_digest": snapshot["digest"],
            "media_count": snapshot["count"],
        },
    }
    db.add(product)
    db.flush()
    return _product_readiness(db, product).images
