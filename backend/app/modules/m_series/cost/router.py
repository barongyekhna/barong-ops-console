"""M 系列 · 出货成本明细的 HTTP 端点。

路径刻意留在 ``/mfg`` 前缀下(``/api/app/mfg/cost/...``):``main.py`` 的错误消毒只
豁免 ``/api/app/mfg/``,中文业务错误才透得到前台;前端代理白名单也只需在
``isAllowedMfgPath`` 里加一个 ``cost`` 分支,不必新写一套。

门禁认的是 ``mfg.cost.*``,**不是** ``mfg.inventory.*``:会数箱子的人不该自动看见
每一家供应商的报价和每个产品的毛利。
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
from ...c19 import conversation_schemas, conversation_service
from ...c19 import message_schemas, message_service
from ...c19.record_store_provider import get_chat_record_store
from ...c19.storage import ChatRecordStore
from ..inventory.service import (
    FactoryContext,
    FactoryNotConfigured,
    MfgError,
    MfgNotFound,
    resolve_factory_context,
)
from . import schemas as S
from . import share
from . import service

router = APIRouter(prefix="/mfg/cost", tags=["mfg-cost"])


def _cost_access(db: Session, user: User, action: str) -> tuple[FactoryContext, User]:
    try:
        ctx = resolve_factory_context(db)
    except FactoryNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    if not service.user_may_access(user, ctx, db=db, action=action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "出货成本明细仅限 owner、制造公司超级管理员,"
                "或在权限页拿到「查看出货成本明细」的制造公司成员"
                if action == "read"
                else "这个账号只能查看成本,没有「定出厂价与工价」权限"
            ),
        )
    return ctx, user


def _require_cost_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> tuple[FactoryContext, User]:
    return _cost_access(db, user, "read")


def _require_cost_price(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> tuple[FactoryContext, User]:
    return _cost_access(db, user, "price")


CostRead = Annotated[tuple[FactoryContext, User], Depends(_require_cost_read)]
CostPrice = Annotated[tuple[FactoryContext, User], Depends(_require_cost_price)]


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except MfgNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except MfgError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


# ---------------------------------------------------------------- 工序库


@router.get("/processes", response_model=S.LaborProcessListResponse)
def list_processes(
    access: CostRead,
    db: Session = Depends(get_db),
    include_archived: bool = Query(default=False),
) -> S.LaborProcessListResponse:
    ctx, _ = access
    return _run(
        service.list_processes, db, ctx, include_archived=include_archived
    )


@router.post(
    "/processes",
    response_model=S.LaborProcessRead,
    status_code=status.HTTP_201_CREATED,
)
def create_process(
    payload: S.LaborProcessCreate,
    access: CostPrice,
    db: Session = Depends(get_db),
) -> S.LaborProcessRead:
    ctx, user = access
    process = _run(service.create_process, db, ctx, user=user, payload=payload)
    return S.LaborProcessRead(
        id=process.id,
        name=process.name,
        note=process.note,
        position=process.position,
        is_archived=process.is_archived,
        rate=payload.rate,
        rate_effective_date=payload.effective_date,
    )


@router.patch("/processes/{process_id}", response_model=S.LaborProcessRead)
def patch_process(
    process_id: UUID,
    payload: S.LaborProcessPatch,
    access: CostPrice,
    db: Session = Depends(get_db),
) -> S.LaborProcessRead:
    ctx, _ = access
    process = _run(service.patch_process, db, ctx, process_id, payload)
    return S.LaborProcessRead(
        id=process.id,
        name=process.name,
        note=process.note,
        position=process.position,
        is_archived=process.is_archived,
    )


@router.post(
    "/processes/{process_id}/rates",
    response_model=S.LaborRateRead,
    status_code=status.HTTP_201_CREATED,
)
def add_labor_rate(
    process_id: UUID,
    payload: S.LaborRateCreate,
    access: CostPrice,
    db: Session = Depends(get_db),
) -> S.LaborRateRead:
    ctx, user = access
    row = _run(
        service.add_labor_rate, db, ctx, process_id, user=user, payload=payload
    )
    return S.LaborRateRead.model_validate(row)


@router.get("/processes/{process_id}/rates", response_model=list[S.LaborRateRead])
def list_labor_rates(
    process_id: UUID,
    access: CostRead,
    db: Session = Depends(get_db),
) -> list[S.LaborRateRead]:
    ctx, _ = access
    rows = _run(service.list_labor_rates, db, ctx, process_id)
    return [S.LaborRateRead.model_validate(row) for row in rows]


# ---------------------------------------------------------------- 产品挂接工序


@router.get("/products/{product_id}/labor", response_model=S.ProductLaborRead)
def get_product_labor(
    product_id: UUID,
    access: CostRead,
    db: Session = Depends(get_db),
) -> S.ProductLaborRead:
    ctx, _ = access
    return _run(service.get_product_labor, db, ctx, product_id)


@router.put("/products/{product_id}/labor", response_model=S.ProductLaborRead)
def replace_product_labor(
    product_id: UUID,
    payload: S.LaborReplace,
    access: CostPrice,
    db: Session = Depends(get_db),
) -> S.ProductLaborRead:
    ctx, _ = access
    return _run(service.replace_product_labor, db, ctx, product_id, payload)


# ---------------------------------------------------------------- 价格事件


@router.post(
    "/products/{product_id}/sale-price",
    response_model=S.SalePriceRead,
    status_code=status.HTTP_201_CREATED,
)
def set_sale_price(
    product_id: UUID,
    payload: S.SalePriceCreate,
    access: CostPrice,
    db: Session = Depends(get_db),
) -> S.SalePriceRead:
    ctx, user = access
    row = _run(
        service.set_sale_price, db, ctx, product_id, user=user, payload=payload
    )
    return S.SalePriceRead.model_validate(row)


@router.get(
    "/products/{product_id}/sale-prices", response_model=S.SalePriceListResponse
)
def list_sale_prices(
    product_id: UUID,
    access: CostRead,
    db: Session = Depends(get_db),
) -> S.SalePriceListResponse:
    ctx, _ = access
    rows = _run(service.list_sale_prices, db, ctx, product_id)
    return S.SalePriceListResponse(
        items=[S.SalePriceRead.model_validate(row) for row in rows],
        total=len(rows),
    )


@router.post(
    "/items/{item_id}/reference-price",
    response_model=S.ReferencePriceRead,
    status_code=status.HTTP_201_CREATED,
)
def set_reference_price(
    item_id: UUID,
    payload: S.ReferencePriceCreate,
    access: CostPrice,
    db: Session = Depends(get_db),
) -> S.ReferencePriceRead:
    ctx, user = access
    row = _run(
        service.set_reference_price, db, ctx, item_id, user=user, payload=payload
    )
    return S.ReferencePriceRead.model_validate(row)


# ---------------------------------------------------------------- 成本表


@router.get("/products", response_model=S.ProductCostListResponse)
def list_product_costs(
    access: CostRead,
    db: Session = Depends(get_db),
    include_archived: bool = Query(default=False),
) -> S.ProductCostListResponse:
    ctx, _ = access
    return _run(
        service.list_product_costs, db, ctx, include_archived=include_archived
    )


@router.get("/products/{product_id}/sheet", response_model=S.CostSheetPreview)
def preview_sheet(
    product_id: UUID,
    access: CostRead,
    db: Session = Depends(get_db),
    qty: Decimal = Query(default=Decimal("1"), gt=0),
) -> S.CostSheetPreview:
    ctx, _ = access
    return _run(service.preview_sheet, db, ctx, product_id=product_id, batch_qty=qty)


@router.post(
    "/sheets", response_model=S.CostSheetRead, status_code=status.HTTP_201_CREATED
)
def create_sheet(
    payload: S.CostSheetCreate,
    access: CostPrice,
    db: Session = Depends(get_db),
) -> S.CostSheetRead:
    ctx, user = access
    sheet = _run(service.create_sheet, db, ctx, user=user, payload=payload)
    return S.CostSheetRead.model_validate(sheet)


@router.get("/sheets", response_model=S.CostSheetListResponse)
def list_sheets(
    access: CostRead,
    db: Session = Depends(get_db),
    product_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> S.CostSheetListResponse:
    ctx, _ = access
    return _run(service.list_sheets, db, ctx, product_id=product_id, limit=limit)


@router.get("/sheets/{sheet_id}", response_model=S.CostSheetDetail)
def get_sheet(
    sheet_id: UUID,
    access: CostRead,
    db: Session = Depends(get_db),
) -> S.CostSheetDetail:
    ctx, _ = access
    return _run(service.get_sheet, db, ctx, sheet_id)


# ---------------------------------------------------------------- 分享


@router.post("/sheets/{sheet_id}/share", response_model=S.CostShareResult)
async def share_sheet(
    sheet_id: UUID,
    payload: S.CostShareRequest,
    access: CostPrice,
    db: Session = Depends(get_db),
    store: ChatRecordStore = Depends(get_chat_record_store),
) -> S.CostShareResult:
    """把快照通过 C19 发出去。

    ``delivered`` 里的每一行都是**回读确认过**的:在对方会话里真的看见了那条消息。
    发送接口返回 200 但回读没找到,会落进 ``failed`` 而不是台账。
    """
    ctx, user = access
    try:
        return await share.share_sheet(
            db,
            ctx,
            sheet_id,
            user=user,
            payload=payload,
            store=store,
            conversation_service=conversation_service,
            message_service=message_service,
            conversation_schemas=conversation_schemas,
            message_schemas=message_schemas,
        )
    except MfgNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except MfgError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
