"""P 系列上架控制面 API：取数 / 派单 / 回报。

- 派单 `POST /p/products/{id}/dispatch`：控制台点「上架」→ 建 job + 派给 n8n（前端调，会话鉴权）。
- 取数 `GET /p/products/{id}/upload-package?token=`：n8n 拿 job token 来取上架包。
- 回报 `POST /p/uploads/{job_id}/result`：n8n 上架完 POST 回来（X-Job-Token 鉴权）→ 写台账 + 回写 K + 落通知。
取数/回报走裸路径 + token（n8n server-to-server，绕过 /api/app 会话中间件）。
"""

from __future__ import annotations

import logging
import os
from urllib.error import HTTPError
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.config import get_settings
from ...core.roles import is_super_admin_role
from ...db.session import get_db
from ...models.user import User
from ...services.permission_service import resolve_current_user_permission_info
from ..k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
)
from ..notifications.service import create_notification
from .contract.upload_package import UploadPackage
from .upload.assemble import assemble_upload_package, gate_blockers
from .upload.faq_publication_audit import audit_published_faq
from .upload.jobs import (
    create_dispatch_job,
    enqueue_dispatch_job,
    kick_queue,
    record_result,
)
from .upload.models import PUploadJob

router = APIRouter(prefix="/p", tags=["p-upload"])
logger = logging.getLogger(__name__)

MODULE_KEY = "p.upload"
PERMISSION_READ = "p.upload.read"
PERMISSION_EXECUTE = "p.upload.execute"


def _require_p_permission(permission_key: str):
    """人用端点鉴权：owner / super_admin 放行，否则需持有对应 p.upload.* 权限。

    execute 隐含 read。机器端点（取数/取图/回报）走 job-token，不经过这里。
    """

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(db, user, request=request)
        allowed_keys = {permission_key}
        if permission_key == PERMISSION_READ:
            # 能派单的人自然能看板；execute 隐含 read。
            allowed_keys.add(PERMISSION_EXECUTE)
        if (
            permissions.is_owner_full_access
            or is_super_admin_role(user.role)
            or allowed_keys.intersection(permissions.permission_keys)
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission_key}",
        )

    return dependency


def _public_base() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://ops.barongyekhna.com").rstrip("/")


def _callback_base() -> str:
    """n8n 侧访问控制台用的 base（内网直连优先，与派单/回调同源）。"""
    return (os.getenv("P_CALLBACK_BASE") or _public_base()).rstrip("/")


class DispatchResponse(BaseModel):
    job_id: str
    status: str
    dispatched: bool


class FaqRecheckResponse(BaseModel):
    # passed | mismatch | deferred_unpublished | no_upload | audit_failed
    status: str
    ok: bool | None = None
    page_url: str | None = None
    schema_faq_count: int | None = None
    visible_faq_present: bool | None = None
    missing_from_visible: list | None = None
    message: str


class UploadResultRequest(BaseModel):
    status: str  # success | failed
    external_product_id: str | None = None
    external_url: str | None = None
    error: str | None = None


class UploadResultResponse(BaseModel):
    job_id: str
    status: str


def _audit_published_faq_after_success(
    db: Session,
    *,
    product_id: UUID,
    external_product_id: str | None,
    external_url: str | None,
) -> dict[str, object]:
    """Best-effort FAQ/schema audit; alert without changing upload success."""

    try:
        if not external_url:
            raise ValueError("successful upload callback did not include a page URL")
        audit = audit_published_faq(
            external_url,
            allowed_base_url=get_settings().wp_base_url,
        )
    except Exception as exc:  # noqa: BLE001 - publication is never rolled back
        # 产品先上架成 Woo 草稿，公开页此刻还是 404/403 —— 要等用户在 WP 手动发布，
        # 这不是 FAQ 出错，只是页面还没公开。记 deferred、不发刺眼的错误通知（否则
        # 每次上架都虚惊一次，还会把真正的 FAQ 不一致淹没）。真正的对账留到发布后
        # 由「复检 FAQ」触发。其它异常（超时 / 5xx / 解析失败）才是真问题，照旧告警。
        if isinstance(exc, HTTPError) and exc.code in (401, 403, 404, 410):
            logger.info(
                "FAQ audit deferred (page not public yet) product_id=%s url=%s code=%s",
                product_id,
                external_url,
                exc.code,
            )
            return {
                "status": "deferred_unpublished",
                "ok": None,
                "page_url": external_url,
                "http_code": exc.code,
            }
        audit = {
            "status": "audit_failed",
            "ok": False,
            "page_url": external_url,
            "error_class": exc.__class__.__name__,
            "error": str(exc),
        }
        logger.error(
            "Published FAQ/schema audit failed product_id=%s url=%s error=%s",
            product_id,
            external_url,
            exc.__class__.__name__,
            exc_info=True,
        )
        create_notification(
            db,
            event_type="p.upload.faq_audit_failed",
            title="上架页 FAQ 同步校验失败",
            body="无法完成 FAQPage schema 与页面可见 FAQ 的自动对账，请人工复查。",
            level="error",
            source="p.woocommerce",
            product_id=product_id,
            external_refs={
                "woo_product_id": external_product_id,
                "url": external_url,
            },
            payload=audit,
        )
        return audit

    if audit.get("ok") is not True:
        logger.error(
            "Published FAQ/schema mismatch product_id=%s url=%s audit=%s",
            product_id,
            external_url,
            audit,
        )
        create_notification(
            db,
            event_type="p.upload.faq_sync_mismatch",
            title="上架页 FAQ 与结构化数据不一致",
            body="FAQPage schema 含有页面不可见的问答；上架未回滚，请立即复查。",
            level="error",
            source="p.woocommerce",
            product_id=product_id,
            external_refs={
                "woo_product_id": external_product_id,
                "url": external_url,
            },
            payload=audit,
        )
    return audit


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
    previous_external_product_id = db.scalar(
        select(PUploadJob.external_product_id)
        .where(
            PUploadJob.product_id == product_id,
            PUploadJob.channel == channel,
            PUploadJob.status == "success",
            PUploadJob.external_product_id.is_not(None),
            PUploadJob.job_id != job.job_id,
        )
        .order_by(PUploadJob.finished_at.desc(), PUploadJob.created_at.desc())
        .limit(1)
    )
    product = _load_product(db, product_id)
    blockers = gate_blockers(db, product)
    if blockers:
        raise HTTPException(
            status_code=409, detail={"ready": False, "blockers": blockers}
        )
    return assemble_upload_package(
        db,
        product,
        channel=channel,
        base_url=_callback_base(),
        job_id=job.job_id,
        job_token=job.token,
        woo_existing_product_id=previous_external_product_id,
    )


class UploadJobItem(BaseModel):
    job_id: str
    product_id: str
    product_name: str | None = None
    sku: str | None = None
    channel: str
    status: str
    external_product_id: str | None = None
    external_url: str | None = None
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None


class UploadJobListResponse(BaseModel):
    jobs: list[UploadJobItem]
    summary: dict[str, int]


@router.get("/uploads", response_model=UploadJobListResponse)
def p_upload_jobs_list(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(_require_p_permission(PERMISSION_READ)),
) -> UploadJobListResponse:
    """上架台账：驾驶舱页面的数据源（会话鉴权）。

    顺带踢一次队列 —— 这是 in-flight 超时收尸的惰性触发点（页面在轮询）。
    """
    del request, user
    try:
        kick_queue(db, public_base=_callback_base())
        db.commit()
    except Exception:  # noqa: BLE001 - 踢队失败不影响读台账
        db.rollback()
    rows = db.execute(
        select(PUploadJob, KProductKnowledgeProduct.product_name_en, KProductKnowledgeProduct.sku)
        .join(
            KProductKnowledgeProduct,
            KProductKnowledgeProduct.id == PUploadJob.product_id,
            isouter=True,
        )
        .order_by(PUploadJob.created_at.desc())
        .limit(limit)
    ).all()
    jobs = [
        UploadJobItem(
            job_id=job.job_id,
            product_id=str(job.product_id),
            product_name=product_name,
            sku=sku,
            channel=job.channel,
            status=job.status,
            external_product_id=job.external_product_id,
            external_url=job.external_url,
            error=job.error,
            created_at=job.created_at.isoformat() if job.created_at else None,
            finished_at=job.finished_at.isoformat() if job.finished_at else None,
        )
        for job, product_name, sku in rows
    ]
    summary = {"total": len(jobs), "success": 0, "failed": 0, "in_flight": 0}
    for job in jobs:
        if job.status == "success":
            summary["success"] += 1
        elif job.status == "failed":
            summary["failed"] += 1
        else:
            summary["in_flight"] += 1
    return UploadJobListResponse(jobs=jobs, summary=summary)


@router.get("/jobs/{job_id}/media/{asset_id}/file")
def p_job_media_file(
    job_id: str,
    asset_id: UUID,
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> FileResponse:
    """n8n 图片中转的取图口：一单一钥 token 鉴权，只放行该 job 产品自己的图。"""
    if not token:
        raise HTTPException(status_code=401, detail="缺少 token。")
    job = db.scalar(
        select(PUploadJob).where(
            PUploadJob.job_id == job_id, PUploadJob.token == token
        )
    )
    if job is None:
        raise HTTPException(status_code=401, detail="token 无效。")
    asset = db.get(KProductKnowledgeMediaAsset, asset_id)
    if (
        asset is None
        or asset.status == "removed"
        or str(asset.product_id) != str(job.product_id)
    ):
        raise HTTPException(status_code=404, detail="图片不存在。")
    from ..k_series.product_knowledge.router import _ensure_media_asset_file

    try:
        path = _ensure_media_asset_file(asset)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="图片文件不可读。") from exc
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    filename = str(metadata.get("filename") or "") or f"{asset_id}.png"
    return FileResponse(
        path=path,
        media_type=asset.mime_type or "image/png",
        filename=filename,
        content_disposition_type="inline",
    )


@router.post("/products/{product_id}/dispatch", response_model=DispatchResponse)
def p_dispatch(
    product_id: UUID,
    request: Request,
    channel: str = "woocommerce",
    db: Session = Depends(get_db),
    user: User = Depends(_require_p_permission(PERMISSION_EXECUTE)),
) -> DispatchResponse:
    del request, user
    try:
        product = _load_product(db, product_id)
        blockers = gate_blockers(db, product)
    except HTTPException:
        logger.exception(
            "P dispatch preflight raised an HTTP error product_id=%s channel=%s",
            product_id,
            channel,
        )
        raise
    except Exception:  # noqa: BLE001 - preserve the original route failure
        logger.exception(
            "P dispatch preflight failed product_id=%s channel=%s",
            product_id,
            channel,
        )
        raise
    if blockers:
        logger.warning(
            "P dispatch blocked by canonical gate product_id=%s channel=%s blockers=%s",
            product_id,
            channel,
            blockers,
        )
        raise HTTPException(
            status_code=409, detail={"ready": False, "blockers": blockers}
        )
    try:
        job = create_dispatch_job(
            db, product_id=product_id, channel=channel, public_base=_public_base()
        )
    except Exception:  # noqa: BLE001 - do not remap dispatch failures to 409
        logger.exception(
            "P dispatch job creation failed product_id=%s channel=%s",
            product_id,
            channel,
        )
        db.rollback()
        raise
    try:
        db.commit()
    except Exception:  # noqa: BLE001 - original exception stays visible and propagates
        logger.exception(
            "P dispatch commit failed product_id=%s channel=%s job_id=%s",
            product_id,
            channel,
            job.job_id,
        )
        db.rollback()
        raise
    return DispatchResponse(
        job_id=job.job_id,
        status=job.status,
        dispatched=(job.status == "dispatched"),
    )


@router.post("/products/{product_id}/faq-recheck", response_model=FaqRecheckResponse)
def p_faq_recheck(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_p_permission(PERMISSION_READ)),
) -> FaqRecheckResponse:
    """发布后手动复检：抓真实上架页，核对 FAQPage 结构化数据与页面可见 FAQ 是否
    一致。只有真不一致才告警；页面还是草稿（404/403）时如实返回「待发布」。"""

    del request, user
    job = db.scalars(
        select(PUploadJob)
        .where(
            PUploadJob.product_id == product_id,
            PUploadJob.status == "success",
            PUploadJob.external_url.is_not(None),
        )
        .order_by(PUploadJob.finished_at.desc(), PUploadJob.created_at.desc())
    ).first()
    if job is None or not job.external_url:
        return FaqRecheckResponse(
            status="no_upload",
            ok=None,
            message="该产品还没有成功上架记录，无法复检。",
        )
    try:
        audit = audit_published_faq(
            job.external_url,
            allowed_base_url=get_settings().wp_base_url,
        )
    except HTTPError as exc:
        if exc.code in (401, 403, 404, 410):
            return FaqRecheckResponse(
                status="deferred_unpublished",
                ok=None,
                page_url=job.external_url,
                message="页面还没发布（Woo 草稿），发布后再点复检。",
            )
        return FaqRecheckResponse(
            status="audit_failed",
            ok=False,
            page_url=job.external_url,
            message=f"抓取上架页失败：HTTP {exc.code}。",
        )
    except Exception as exc:  # noqa: BLE001 - recheck never rolls anything back
        logger.exception("FAQ recheck failed product_id=%s", product_id)
        return FaqRecheckResponse(
            status="audit_failed",
            ok=False,
            page_url=job.external_url,
            message=f"复检失败：{exc.__class__.__name__}。",
        )

    ok = audit.get("ok") is True
    if not ok:
        create_notification(
            db,
            event_type="p.upload.faq_sync_mismatch",
            title="上架页 FAQ 与结构化数据不一致",
            body="FAQPage schema 含有页面不可见的问答；请立即复查。",
            level="error",
            source="p.woocommerce",
            product_id=product_id,
            external_refs={
                "woo_product_id": job.external_product_id,
                "url": job.external_url,
            },
            payload=audit,
        )
        db.commit()
    return FaqRecheckResponse(
        status=str(audit.get("status") or ("passed" if ok else "mismatch")),
        ok=ok,
        page_url=job.external_url,
        schema_faq_count=audit.get("schema_faq_count"),
        visible_faq_present=audit.get("visible_faq_present"),
        missing_from_visible=audit.get("missing_from_visible"),
        message=(
            "FAQ 与结构化数据一致 ✅"
            if ok
            else "发现结构化数据里有页面不可见的问答，请复查。"
        ),
    )


class DispatchBatchRequest(BaseModel):
    product_ids: list[UUID]


class DispatchBatchResponse(BaseModel):
    queued: list[str]
    blocked: list[dict[str, object]]


@router.post("/dispatch/batch", response_model=DispatchBatchResponse)
def p_dispatch_batch(
    payload: DispatchBatchRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_p_permission(PERMISSION_EXECUTE)),
) -> DispatchBatchResponse:
    """批量上架：全部入队，由串行队列一单一单发 n8n（防 Woo 429）。"""
    del request, user
    queued: list[str] = []
    blocked: list[dict[str, object]] = []
    for product_id in payload.product_ids:
        product = db.get(KProductKnowledgeProduct, product_id)
        if product is None:
            blocked.append({"product_id": str(product_id), "blockers": ["产品不存在"]})
            continue
        blockers = gate_blockers(db, product)
        if blockers:
            blocked.append({"product_id": str(product_id), "blockers": blockers})
            continue
        job = enqueue_dispatch_job(
            db, product_id=product_id, channel="woocommerce"
        )
        queued.append(job.job_id)
    kick_queue(db, public_base=_callback_base())
    db.commit()
    return DispatchBatchResponse(queued=queued, blocked=blocked)


class BoardProduct(BaseModel):
    product_id: str
    product_name: str | None = None
    sku: str | None = None
    price: str | None = None
    gate_ready: bool
    blockers: list[str]
    exported: bool
    last_job_status: str | None = None
    last_external_url: str | None = None


class BoardResponse(BaseModel):
    pending: list[BoardProduct]
    uploaded: list[BoardProduct]


@router.get("/products/board", response_model=BoardResponse)
def p_products_board(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_p_permission(PERMISSION_READ)),
) -> BoardResponse:
    """待上传 / 已上传分组：K 链路走完（有文案）的产品全景。"""
    del request, user
    products = db.scalars(
        select(KProductKnowledgeProduct)
        .where(KProductKnowledgeProduct.marketing_copy_json.isnot(None))
        .order_by(KProductKnowledgeProduct.updated_at.desc())
        .limit(100)
    ).all()
    latest_jobs: dict[str, PUploadJob] = {}
    for job in db.scalars(
        select(PUploadJob).order_by(PUploadJob.created_at.asc())
    ).all():
        latest_jobs[str(job.product_id)] = job

    pending: list[BoardProduct] = []
    uploaded: list[BoardProduct] = []
    for product in products:
        blockers = gate_blockers(db, product)
        job = latest_jobs.get(str(product.id))
        exported = (product.product_status == "exported") or bool(
            job and job.status == "success"
        )
        entry = BoardProduct(
            product_id=str(product.id),
            product_name=product.product_name_en,
            sku=product.sku,
            price=(
                f"{product.regular_price} {(product.price_currency or 'USD')[:3]}"
                if product.regular_price is not None
                else None
            ),
            gate_ready=not blockers,
            blockers=blockers,
            exported=exported,
            last_job_status=job.status if job else None,
            last_external_url=job.external_url if job else None,
        )
        (uploaded if exported else pending).append(entry)
    return BoardResponse(pending=pending, uploaded=uploaded)


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
            # 串行队列：本单落地后自动放行下一单
            public_base=_callback_base(),
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
    # Persist the upload outcome before the network audit.  A stale cache,
    # unavailable page, or FAQ mismatch must alert, never roll back Woo success.
    db.commit()
    if payload.status == "success":
        try:
            _audit_published_faq_after_success(
                db,
                product_id=job.product_id,
                external_product_id=payload.external_product_id,
                external_url=payload.external_url,
            )
            db.commit()
        except Exception:  # noqa: BLE001 - even alert persistence is fail-safe
            db.rollback()
            logger.error(
                "Failed to persist published FAQ/schema audit product_id=%s",
                job.product_id,
                exc_info=True,
            )
    return UploadResultResponse(job_id=job.job_id, status=job.status)
