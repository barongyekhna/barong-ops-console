"""FastAPI endpoints for B2B customer prospecting."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....db.session import get_db
from ....models.user import User
from ..wholesale.router import (
    PERMISSION_MANAGE,
    PERMISSION_READ,
    _require_b2b_permission,
)
from . import service
from .seed import seed_prospect_config
from .models import B2BProspectQuery, B2BTargetCity
from .schemas import (
    ScreenRequest,
    ScreenResult,
    ProspectListResponse,
    ProspectQueryCreate,
    ProspectQueryRead,
    ProspectRead,
    ProspectReviewRequest,
    SweepRequest,
    SweepResult,
    TargetCityRead,
)

router = APIRouter(prefix="/b2b", tags=["b2b-prospects"])


@router.get("/prospects", response_model=ProspectListResponse)
def list_prospects(
    status_filter: str | None = Query(default=None, alias="status"),
    country: str | None = Query(default=None),
    store_type: str | None = Query(default=None),
    verdict: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> ProspectListResponse:
    del user
    rows, counts = service.list_prospects(
        db,
        status=status_filter,
        country=country,
        store_type=store_type,
        verdict=verdict,
        limit=limit,
        offset=offset,
    )
    hints = service.chain_hints(db, rows)
    items = []
    for row in rows:
        item = ProspectRead.model_validate(row)
        item.maps_url = service.maps_url_for(row)
        item.chain_hint = hints.get(row.id)
        item.screen_signals = row.screen_signals_json or None
        items.append(item)
    return ProspectListResponse(items=items, count=len(rows), **counts)


@router.patch("/prospects/{prospect_id}/review", response_model=ProspectRead)
def review_prospect(
    prospect_id: UUID,
    payload: ProspectReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> ProspectRead:
    del user
    try:
        row = service.review_prospect(
            db,
            prospect_id=prospect_id,
            approve=payload.approve,
            reject_reason=payload.reject_reason,
            notes=payload.notes,
        )
    except service.ProspectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProspectRead.model_validate(row)


@router.get("/prospect-queries", response_model=list[ProspectQueryRead])
def list_queries(
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> list[ProspectQueryRead]:
    del user
    rows = db.scalars(
        select(B2BProspectQuery).order_by(
            B2BProspectQuery.store_type, B2BProspectQuery.country
        )
    )
    return [ProspectQueryRead.model_validate(row) for row in rows]


@router.post("/prospect-queries", response_model=ProspectQueryRead, status_code=201)
def create_query(
    payload: ProspectQueryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> ProspectQueryRead:
    del user
    row = B2BProspectQuery(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return ProspectQueryRead.model_validate(row)


@router.get("/target-cities", response_model=list[TargetCityRead])
def list_cities(
    country: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> list[TargetCityRead]:
    del user
    stmt = select(B2BTargetCity)
    if country:
        stmt = stmt.where(B2BTargetCity.country == country)
    rows = db.scalars(
        stmt.order_by(
            B2BTargetCity.country,
            B2BTargetCity.priority.desc(),
            B2BTargetCity.population.desc().nullslast(),
        ).limit(limit)
    )
    return [TargetCityRead.model_validate(row) for row in rows]


@router.get("/prospect-quota", response_model=SweepResult)
def get_quota(
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> SweepResult:
    del user
    return SweepResult(**service.quota_status(db))


@router.post("/prospect-sweep", response_model=SweepResult)
def run_sweep(
    payload: SweepRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> SweepResult:
    del user
    try:
        result = service.run_sweep(
            db,
            max_queries=payload.max_queries,
            country=payload.country,
            store_type=payload.store_type,
        )
    except service.ProspectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SweepResult(**result)


@router.post("/prospect-config/seed")
def seed_config(
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> dict[str, int]:
    """灌入默认查询模板和城市清单(幂等,已存在的跳过)。"""
    del user
    return seed_prospect_config(db)


@router.post("/prospect-screen", response_model=ScreenResult)
def screen_prospects(
    payload: ScreenRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> ScreenResult:
    """机器读官网,给每家店判个结论 + 一句人话。

    用户不用再点地图链接逐家看——他只读结论。
    """
    try:
        result = service.screen_prospects(
            db,
            limit=payload.limit,
            store_type=payload.store_type,
            user=user,
        )
    except service.ProspectError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    return ScreenResult(**result)
