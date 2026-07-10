"""P 系列上架控制面 API。

这一批：**取数**（K 产品 → 完整上架包，含门禁）。派单 / 回报 + 台账随后
（派单要等用户 n8n 工作流的 webhook 地址）。
"""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...db.session import get_db
from ...models.user import User
from ..k_series.product_knowledge.models import KProductKnowledgeProduct
from .contract.upload_package import UploadPackage
from .upload.assemble import assemble_upload_package, gate_blockers

router = APIRouter(prefix="/p", tags=["p-upload"])


def _public_base() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://ops.barongyekhna.com").rstrip("/")


@router.get(
    "/products/{product_id}/upload-package",
    response_model=UploadPackage,
)
def p_upload_package(
    product_id: UUID,
    request: Request,
    channel: str = "woocommerce",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UploadPackage:
    """取数：把一个 K 产品组装成 WooCommerce 上架包。门禁没过 → 409 + 缺什么。"""
    del request, user
    product = db.get(KProductKnowledgeProduct, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在。")
    blockers = gate_blockers(db, product)
    if blockers:
        raise HTTPException(
            status_code=409,
            detail={"ready": False, "blockers": blockers},
        )
    return assemble_upload_package(
        db, product, channel=channel, base_url=_public_base()
    )
