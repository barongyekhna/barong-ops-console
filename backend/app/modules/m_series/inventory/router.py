"""M 系列 · 制造库存的 HTTP 端点。

门禁是角色硬门:owner 或制造公司自己的 super_admin,其他人一律 403——不看权限码,
管理员误授了 mfg.* 权限码也进不来。工厂组织由 service 显式定位,不依赖请求 org 上下文。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ....api.deps import get_current_user
from ....db.session import get_db
from ....models.user import User
from . import schemas as S
from . import service
from .service import FactoryContext

router = APIRouter(prefix="/mfg", tags=["mfg-inventory"])

PERMISSION_READ = "mfg.inventory.read"
PERMISSION_MANAGE = "mfg.inventory.manage"


def _mfg_access(db: Session, user: User, action: str) -> tuple[FactoryContext, User]:
    try:
        ctx = service.resolve_factory_context(db)
    except service.FactoryNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    if not service.user_may_access(user, ctx, db=db, action=action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "库存模块仅限 owner、制造公司超级管理员,或在权限页拿到库存权限的制造公司成员"
                if action == "read"
                else "这个账号只能查看库存,没有「管理制造库存」权限"
            ),
        )
    return ctx, user


def _require_mfg_access(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> tuple[FactoryContext, User]:
    return _mfg_access(db, user, "read")


def _require_mfg_manage(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> tuple[FactoryContext, User]:
    return _mfg_access(db, user, "manage")


Access = Annotated[tuple[FactoryContext, User], Depends(_require_mfg_access)]
Manage = Annotated[tuple[FactoryContext, User], Depends(_require_mfg_manage)]


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.InsufficientStock as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "shortages": [row.model_dump(mode="json") for row in exc.shortages],
            },
        ) from exc
    except service.MfgNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.MfgError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


# ---------------------------------------------------------------- 上下文


@router.get("/context", response_model=S.FactoryContextRead)
def read_context(access: Access) -> S.FactoryContextRead:
    ctx, _ = access
    return S.FactoryContextRead(
        factory_org_id=ctx.factory_org_id,
        org_name=ctx.org_name,
        suggested_units=list(S.SUGGESTED_UNITS),
    )


# ---------------------------------------------------------------- 编码组 / 自动编码


@router.get("/code-groups", response_model=S.CodeGroupListResponse)
def list_code_groups(
    access: Access,
    db: Session = Depends(get_db),
    kind: S.Kind | None = Query(default=None),
    include_archived: bool = Query(default=False),
) -> S.CodeGroupListResponse:
    ctx, _ = access
    rows = service.list_code_groups(db, ctx, kind=kind, include_archived=include_archived)
    return S.CodeGroupListResponse(items=rows, total=len(rows))


@router.post(
    "/code-groups", response_model=S.CodeGroupRead, status_code=status.HTTP_201_CREATED
)
def create_code_group(
    payload: S.CodeGroupCreate, access: Manage, db: Session = Depends(get_db)
) -> S.CodeGroupRead:
    ctx, _ = access
    return S.CodeGroupRead.model_validate(_run(service.create_code_group, db, ctx, payload))


@router.get("/code-groups/suggest", response_model=S.CodeSuggestion)
def suggest_group_code(
    access: Access,
    db: Session = Depends(get_db),
    name: str = Query(min_length=1, max_length=255),
) -> S.CodeSuggestion:
    ctx, _ = access
    return service.suggest_group_code(db, ctx, name)


@router.get("/code-groups/{group_id}/next-code", response_model=S.NextCodePreview)
def preview_next_code(
    group_id: UUID, access: Access, db: Session = Depends(get_db)
) -> S.NextCodePreview:
    ctx, _ = access
    return _run(service.preview_next_code, db, ctx, group_id)


# ---------------------------------------------------------------- 主档/库存


@router.get("/items", response_model=S.ItemListResponse)
def list_items(
    access: Access,
    db: Session = Depends(get_db),
    kind: S.Kind | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    include_archived: bool = Query(default=False),
) -> S.ItemListResponse:
    ctx, _ = access
    items = service.list_items(db, ctx, kind=kind, q=q, include_archived=include_archived)
    return S.ItemListResponse(
        items=[S.ItemRead.model_validate(i) for i in items], total=len(items)
    )


@router.post("/items", response_model=S.ItemRead, status_code=status.HTTP_201_CREATED)
def create_item(
    payload: S.ItemCreate, access: Manage, db: Session = Depends(get_db)
) -> S.ItemRead:
    ctx, _ = access
    return S.ItemRead.model_validate(_run(service.create_item, db, ctx, payload))


@router.patch("/items/{item_id}", response_model=S.ItemRead)
def patch_item(
    item_id: UUID, payload: S.ItemPatch, access: Manage, db: Session = Depends(get_db)
) -> S.ItemRead:
    ctx, _ = access
    return S.ItemRead.model_validate(_run(service.patch_item, db, ctx, item_id, payload))


@router.get("/items/{item_id}/movements", response_model=S.MovementListResponse)
def item_movements(
    item_id: UUID,
    access: Access,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> S.MovementListResponse:
    ctx, _ = access
    items, total = _run(service.item_movements, db, ctx, item_id, limit=limit, offset=offset)
    return S.MovementListResponse(items=items, total=total)


@router.get("/stock", response_model=S.StockListResponse)
def stock(
    access: Access,
    db: Session = Depends(get_db),
    kind: S.Kind | None = Query(default=None),
    include_archived: bool = Query(default=False),
) -> S.StockListResponse:
    ctx, _ = access
    rows = service.stock_rows(db, ctx, kind=kind, include_archived=include_archived)
    return S.StockListResponse(items=rows, total=len(rows))


# ---------------------------------------------------------------- BOM


@router.get("/items/{item_id}/bom", response_model=S.BomRead)
def get_bom(item_id: UUID, access: Access, db: Session = Depends(get_db)) -> S.BomRead:
    ctx, _ = access
    return _run(service.get_bom, db, ctx, item_id)


@router.put("/items/{item_id}/bom", response_model=S.BomRead)
def put_bom(
    item_id: UUID, payload: S.BomReplace, access: Manage, db: Session = Depends(get_db)
) -> S.BomRead:
    ctx, _ = access
    return _run(service.replace_bom, db, ctx, item_id, payload)


# ---------------------------------------------------------------- 生产预演


@router.get("/production/preview", response_model=S.ProductionPreview)
def production_preview(
    access: Access,
    db: Session = Depends(get_db),
    product_id: UUID = Query(...),
    qty: Decimal = Query(..., gt=0),
) -> S.ProductionPreview:
    ctx, _ = access
    return _run(service.preview_production, db, ctx, product_id, qty)


# ---------------------------------------------------------------- 四个动作


@router.post(
    "/documents/receipt", response_model=S.DocumentRead, status_code=status.HTTP_201_CREATED
)
def create_receipt(
    payload: S.ReceiptCreate, access: Manage, db: Session = Depends(get_db)
) -> S.DocumentRead:
    ctx, user = access
    return S.DocumentRead.model_validate(
        _run(service.receipt, db, ctx, user=user, payload=payload)
    )


@router.post(
    "/documents/production", response_model=S.DocumentRead, status_code=status.HTTP_201_CREATED
)
def create_production(
    payload: S.ProductionCreate, access: Manage, db: Session = Depends(get_db)
) -> S.DocumentRead:
    ctx, user = access
    return S.DocumentRead.model_validate(
        _run(service.production, db, ctx, user=user, payload=payload)
    )


@router.post(
    "/documents/shipment", response_model=S.DocumentRead, status_code=status.HTTP_201_CREATED
)
def create_shipment(
    payload: S.ShipmentCreate, access: Manage, db: Session = Depends(get_db)
) -> S.DocumentRead:
    ctx, user = access
    return S.DocumentRead.model_validate(
        _run(service.shipment, db, ctx, user=user, payload=payload)
    )


@router.post(
    "/documents/adjustment", response_model=S.DocumentRead, status_code=status.HTTP_201_CREATED
)
def create_adjustment(
    payload: S.AdjustmentCreate, access: Manage, db: Session = Depends(get_db)
) -> S.DocumentRead:
    ctx, user = access
    return S.DocumentRead.model_validate(
        _run(service.adjustment, db, ctx, user=user, payload=payload)
    )


# ---------------------------------------------------------------- 查账


@router.get("/documents", response_model=S.DocumentListResponse)
def list_documents(
    access: Access,
    db: Session = Depends(get_db),
    doc_type: S.DocType | None = Query(default=None),
    item_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> S.DocumentListResponse:
    ctx, _ = access
    rows, total = service.list_documents(
        db, ctx, doc_type=doc_type, item_id=item_id, limit=limit, offset=offset
    )
    return S.DocumentListResponse(
        items=[S.DocumentRead.model_validate(r) for r in rows], total=total
    )


@router.get("/documents/{document_id}", response_model=S.DocumentDetail)
def get_document(
    document_id: UUID, access: Access, db: Session = Depends(get_db)
) -> S.DocumentDetail:
    ctx, _ = access
    doc, movements = _run(service.get_document, db, ctx, document_id)
    return S.DocumentDetail(
        **S.DocumentRead.model_validate(doc).model_dump(), movements=movements
    )
