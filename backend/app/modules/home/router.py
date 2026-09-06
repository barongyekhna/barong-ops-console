"""`/api/app/dashboard/home` — 主页引导、单卡刷新、SSE 流、流量区间。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.config import get_settings
from ...core.session_cookies import get_session_id_from_request
from ...db.session import get_db
from ...models.user import User
from ...services.data_isolation import (
    OrgDataIsolationUserContext,
    current_org_data_isolation_context,
    org_data_isolation_context,
)
from ..w_series.traffic import service as traffic_service
from .context import HomeAccess, resolve_home_access
from .factory_registry import cards_for, spec_for
from .registry import HomeCardSpec, allowed, load_cards
from .schemas import (
    HomeBootstrapRead,
    HomeCardRead,
    HomeTrafficRangeRead,
    HomeTrafficSummaryRead,
)
from .stream import home_card_stream

router = APIRouter(prefix="/dashboard/home", tags=["dashboard-home"])


def _access_or_403(db: Session, request: Request, user: User) -> HomeAccess:
    access = resolve_home_access(db, user=user, request=request)
    if access is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization context is required.",
        )
    return access


def _load_cards_isolated(
    db: Session,
    *,
    access: HomeAccess,
    user: User,
    specs: list[HomeCardSpec] | None = None,
) -> list[HomeCardRead]:
    """中间件在 /api/app 下已经放好隔离上下文；没有时（直接调用、测试）自己补一份，
    保证引导接口和流循环看到的是同一份数据、算出同一个 digest。"""
    kwargs = {"access": access, "user": user}
    if specs is not None:
        kwargs["specs"] = specs
    if current_org_data_isolation_context() is not None:
        return load_cards(db, **kwargs)
    isolation = OrgDataIsolationUserContext(
        org_id=access.workspace_key,
        user_id=str(user.id),
        role=str(user.role),
        source="home_router",
        strict=False,
    )
    with org_data_isolation_context(isolation):
        return load_cards(db, **kwargs)


def _store_or_403(access: HomeAccess) -> None:
    if not access.is_store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This home page is only available to store organizations.",
        )


def _home_org_or_403(access: HomeAccess) -> tuple[HomeCardSpec, ...]:
    """有皮的组织类型（store / factory）才有主页；返回这类组织的卡片集。"""
    specs = cards_for(access)
    if not specs:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This home page is not available for this organization type.",
        )
    return specs


@router.get("", response_model=HomeBootstrapRead)
def home_bootstrap(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HomeBootstrapRead:
    access = _access_or_403(db, request, user)
    specs = cards_for(access)
    cards = _load_cards_isolated(db, access=access, user=user, specs=list(specs)) if specs else []
    return HomeBootstrapRead(
        org_type=access.org_type,
        org_id=access.workspace_key,
        cards=cards,
        poll_seconds=float(get_settings().home_stream_poll_seconds),
    )


@router.get("/cards/{card_id}", response_model=HomeCardRead)
def home_card(
    card_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HomeCardRead:
    access = _access_or_403(db, request, user)
    _home_org_or_403(access)
    spec = spec_for(card_id, access)
    if spec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown card.")
    if not allowed(spec, access):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Card not available.")
    cards = _load_cards_isolated(db, access=access, user=user, specs=[spec])
    if not cards:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card unavailable.")
    return cards[0]


@router.get("/stream")
def home_stream(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    access = _access_or_403(db, request, user)
    specs = _home_org_or_403(access)
    settings = get_settings()
    session_id = get_session_id_from_request(request, settings=settings)
    if session_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    # 只用于 digest 基线；引导接口已经把这一份给过前端，流里不重复推。
    initial_cards = _load_cards_isolated(db, access=access, user=user, specs=list(specs))
    return StreamingResponse(
        home_card_stream(
            request=request,
            session_id=session_id,
            actor_user_id=int(user.id),
            org_id=access.workspace_key,
            initial_cards=initial_cards,
            specs=specs,
            expected_org_type=access.org_type,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _traffic_access(db: Session, request: Request, user: User) -> HomeAccess:
    access = _access_or_403(db, request, user)
    _store_or_403(access)
    if not access.is_target_org:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Traffic data belongs to the international-trade organization.",
        )
    return access


@router.get("/traffic", response_model=HomeTrafficSummaryRead)
def home_traffic(
    request: Request,
    days: int = Query(default=7, ge=1, le=traffic_service.MAX_RANGE_DAYS),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HomeTrafficSummaryRead:
    access = _traffic_access(db, request, user)
    report = traffic_service.summary(db, workspace_key=access.workspace_key, days=days)
    return HomeTrafficSummaryRead.model_validate(report)


@router.get("/traffic/range", response_model=HomeTrafficRangeRead)
def home_traffic_range(
    request: Request,
    day_from: date = Query(alias="from"),
    day_to: date = Query(alias="to"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HomeTrafficRangeRead:
    access = _traffic_access(db, request, user)
    if day_to < day_from:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="to precedes from.")
    if (day_to - day_from).days + 1 > traffic_service.MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Range exceeds {traffic_service.MAX_RANGE_DAYS} days.",
        )
    today = traffic_service.site_today()
    if day_to > today:
        day_to = today
    if day_to < day_from:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="from is in the future.")
    report = traffic_service.range_report(
        db, workspace_key=access.workspace_key, day_from=day_from, day_to=day_to
    )
    return HomeTrafficRangeRead.model_validate(report)
