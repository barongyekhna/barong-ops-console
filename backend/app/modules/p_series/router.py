"""P 系列上架控制面 API：取数 / 派单 / 回报。

- 派单 `POST /p/products/{id}/dispatch`：控制台点「上架」→ 建 job + 派给 n8n（前端调，会话鉴权）。
- 取数 `GET /p/products/{id}/upload-package?token=`：n8n 拿 job token 来取上架包。
- 回报 `POST /p/uploads/{job_id}/result`：n8n 上架完 POST 回来（X-Job-Token 鉴权）→ 写台账 + 回写 K + 落通知。
取数/回报走裸路径 + token（n8n server-to-server，绕过 /api/app 会话中间件）。
"""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...db.session import get_db
from ...models.user import User
from ..k_series.product_knowledge.models import KProductKnowledgeProduct
from ..notifications.service import create_notification
from .contract.upload_package import UploadPackage
from .upload.assemble import assemble_upload_package, gate_blockers
from .upload.jobs import create_dispatch_job, record_result
from .upload.models import PUploadJob

router = APIRouter(prefix="/p", tags=["p-upload"])


def _public_base() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://ops.barongyekhna.com").rstrip("/")


class DispatchResponse(BaseModel):
    job_id: str
    status: str
    dispatched: bool


class UploadResultRequest(BaseModel):
    status: str  # success | failed
    external_product_id: str | None = None
    external_url: str | None = None
    error: str | None = None


class UploadResultResponse(BaseModel):
    job_id: str
    status: str


def _load_product(db: Session, product_id: UUID) -> KProductKnowledgeProduct:
    product = db.get(KProductKnowledgeProduct, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在。")
    return product


@router.get("/products/{product_id}/upload-package", response_model=UploadPackage)
def p_upload_package(
    product_id: UUID,
    request: Request,
    channel: str = "woocommerce",
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> UploadPackage:
    del request
    if not token:
        raise HTTPException(status_code=401, detail="缺少 token。")
    job = db.scalar(
        select(PUploadJob).where(
            PUploadJob.token == token, PUploadJob.product_id == product_id
        )
    )
    if job is None:
        raise HTTPException(status_code=401, detail="token 无效。")
    product = _load_product(db, product_id)
    blockers = gate_blockers(db, product)
    if blockers:
        raise HTTPException(
            status_code=409, detail={"ready": False, "blockers": blockers}
        )
    return assemble_upload_package(
        db, product, channel=channel, base_url=_public_base(), job_id=job.job_id
    )


@router.post("/products/{product_id}/dispatch", response_model=DispatchResponse)
def p_dispatch(
    product_id: UUID,
    request: Request,
    channel: str = "woocommerce",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DispatchResponse:
    del request, user
    product = _load_product(db, product_id)
    blockers = gate_blockers(db, product)
    if blockers:
        raise HTTPException(
            status_code=409, detail={"ready": False, "blockers": blockers}
        )
    job = create_dispatch_job(
        db, product_id=product_id, channel=channel, public_base=_public_base()
    )
    db.commit()
    return DispatchResponse(
        job_id=job.job_id,
        status=job.status,
        dispatched=(job.status == "dispatched"),
    )


@router.post("/uploads/{job_id}/result", response_model=UploadResultResponse)
def p_upload_result(
    job_id: str,
    payload: UploadResultRequest,
    x_job_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> UploadResultResponse:
    try:
        job = record_result(
            db,
            job_id=job_id,
            token=x_job_token,
            status=payload.status,
            external_product_id=payload.external_product_id,
            external_url=payload.external_url,
            error=payload.error,
        )
    except PermissionError:
        raise HTTPException(status_code=401, detail="job token 无效。")
    if job is None:
        raise HTTPException(status_code=404, detail="job 不存在。")
    product = db.get(KProductKnowledgeProduct, job.product_id)
    if payload.status == "success":
        if product is not None:
            product.product_status = "exported"
        create_notification(
            db,
            event_type="p.upload.success",
            title="产品已上架 WooCommerce",
            body=payload.external_url,
            level="success",
            source="p.woocommerce",
            product_id=job.product_id,
            external_refs={
                "woo_product_id": payload.external_product_id,
                "url": payload.external_url,
            },
        )
    else:
        create_notification(
            db,
            event_type="p.upload.failed",
            title="产品上架失败",
            body=payload.error,
            level="error",
            source="p.woocommerce",
            product_id=job.product_id,
        )
    db.commit()
    return UploadResultResponse(job_id=job.job_id, status=job.status)
