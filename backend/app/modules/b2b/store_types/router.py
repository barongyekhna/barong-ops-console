"""FastAPI endpoints for the B2B store-type layer."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ....db.session import get_db
from ....models.user import User
from ..wholesale.router import (
    PERMISSION_MANAGE,
    PERMISSION_READ,
    _require_b2b_permission,
)
from ..wholesale.schemas import CATEGORY_PROSPECTING_MIN_READY_ITEMS
from . import service
from .schemas import (
    StoreTypeCategoryWrite,
    StoreTypeCreate,
    StoreTypeListResponse,
    StoreTypePatch,
    StoreTypeRead,
)

router = APIRouter(prefix="/b2b", tags=["b2b-store-types"])


def _bad_request(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=str(error),
    )


@router.get("/store-types", response_model=StoreTypeListResponse)
def list_store_types(
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> StoreTypeListResponse:
    rows = service.list_store_types(db)
    return StoreTypeListResponse(
        store_types=rows,
        min_ready_items=CATEGORY_PROSPECTING_MIN_READY_ITEMS,
        max_active=service.max_active_store_types(),
        active_keys=[
            row.key for row in rows if row.outreach_status == "active"
        ],
    )


@router.post(
    "/store-types",
    response_model=StoreTypeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_store_type(
    payload: StoreTypeCreate,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> StoreTypeRead:
    try:
        service.create_store_type(db, payload=payload)
    except service.StoreTypeError as error:
        raise _bad_request(error) from error
    return _one(db, payload.key)


@router.patch("/store-types/{key}", response_model=StoreTypeRead)
def patch_store_type(
    key: str,
    payload: StoreTypePatch,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> StoreTypeRead:
    try:
        service.patch_store_type(db, key=key, patch=payload)
    except (service.StoreTypeError, ValueError) as error:
        raise _bad_request(error) from error
    return _one(db, key)


@router.delete(
    "/store-types/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_store_type(
    key: str,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> Response:
    try:
        service.delete_store_type(db, key=key)
    except service.StoreTypeError as error:
        raise _bad_request(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/store-types/{key}/categories", response_model=StoreTypeRead)
def add_category(
    key: str,
    payload: StoreTypeCategoryWrite,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> StoreTypeRead:
    try:
        service.add_category(db, key=key, category_prefix=payload.category_prefix)
    except service.StoreTypeError as error:
        raise _bad_request(error) from error
    return _one(db, key)


@router.delete(
    "/store-types/{key}/categories/{category_id}",
    response_model=StoreTypeRead,
)
def remove_category(
    key: str,
    category_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> StoreTypeRead:
    try:
        service.remove_category(db, key=key, category_id=category_id)
    except service.StoreTypeError as error:
        raise _bad_request(error) from error
    return _one(db, key)


def _one(db: Session, key: str) -> StoreTypeRead:
    for row in service.list_store_types(db):
        if row.key == key:
            return row
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"没有这个店型：{key}",
    )
