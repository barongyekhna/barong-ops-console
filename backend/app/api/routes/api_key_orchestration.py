from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.api_key_orchestration import (
    ApiKeyBindingCreateRequest,
    ApiKeyBindingCreateResponse,
    ApiKeyBindingDeleteResponse,
    ApiKeyBindingListResponse,
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyDeleteResponse,
    ApiKeyListResponse,
    ApiKeyUpdateRequest,
    ApiKeyUpdateResponse,
)
from ...services.api_key_orchestration import (
    ApiKeyIsolationError,
    ApiKeyOrchestrationError,
    create_api_key,
    create_api_key_binding,
    delete_api_key,
    delete_api_key_binding,
    list_api_key_bindings,
    list_api_keys,
    update_api_key,
)
from ...services.data_isolation import without_org_data_isolation
from ..deps import require_owner

router = APIRouter(
    prefix="/api-key-orchestration",
    tags=["api-key-orchestration"],
)


def _raise_api_key_error(exc: ApiKeyOrchestrationError) -> None:
    code = str(exc)
    if code in {
        "api_key_not_found",
        "api_key_binding_not_found",
        "module_not_registered",
        "organization_not_found",
    }:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=code,
        ) from exc
    if isinstance(exc, ApiKeyIsolationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=code,
        ) from exc
    if code == "api_key_not_active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=code,
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=code,
    ) from exc


@router.get("/keys", response_model=ApiKeyListResponse)
def api_key_list(
    db: Session = Depends(get_db),
    user: User = Depends(require_owner),
) -> ApiKeyListResponse:
    del user
    with without_org_data_isolation():
        items = list_api_keys(db)
    return ApiKeyListResponse(items=items, count=len(items))


@router.post(
    "/organizations/{org_id}/keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def api_key_create(
    org_id: str,
    payload: ApiKeyCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_owner),
) -> ApiKeyCreateResponse:
    try:
        with without_org_data_isolation():
            item = create_api_key(
                db,
                org_id=org_id,
                payload=payload,
                actor_user_id=str(user.id),
            )
    except ApiKeyOrchestrationError as exc:
        _raise_api_key_error(exc)
    return ApiKeyCreateResponse(item=item)


@router.patch("/keys/{key_id}", response_model=ApiKeyUpdateResponse)
def api_key_update(
    key_id: str,
    payload: ApiKeyUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_owner),
) -> ApiKeyUpdateResponse:
    try:
        with without_org_data_isolation():
            item = update_api_key(
                db,
                key_id=key_id,
                payload=payload,
                actor_user_id=str(user.id),
            )
    except ApiKeyOrchestrationError as exc:
        _raise_api_key_error(exc)
    return ApiKeyUpdateResponse(item=item)


@router.delete("/keys/{key_id}", response_model=ApiKeyDeleteResponse)
def api_key_delete(
    key_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_owner),
) -> ApiKeyDeleteResponse:
    try:
        with without_org_data_isolation():
            delete_api_key(db, key_id=key_id, actor_user_id=str(user.id))
    except ApiKeyOrchestrationError as exc:
        _raise_api_key_error(exc)
    return ApiKeyDeleteResponse(key_id=key_id)


@router.get("/bindings", response_model=ApiKeyBindingListResponse)
def api_key_binding_list(
    db: Session = Depends(get_db),
    user: User = Depends(require_owner),
) -> ApiKeyBindingListResponse:
    del user
    with without_org_data_isolation():
        items = list_api_key_bindings(db)
    return ApiKeyBindingListResponse(items=items, count=len(items))


@router.post(
    "/organizations/{org_id}/bindings",
    response_model=ApiKeyBindingCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def api_key_binding_create(
    org_id: str,
    payload: ApiKeyBindingCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_owner),
) -> ApiKeyBindingCreateResponse:
    try:
        with without_org_data_isolation():
            item = create_api_key_binding(
                db,
                org_id=org_id,
                payload=payload,
                actor_user_id=str(user.id),
            )
    except ApiKeyOrchestrationError as exc:
        _raise_api_key_error(exc)
    return ApiKeyBindingCreateResponse(item=item)


@router.delete(
    "/bindings/{binding_id}",
    response_model=ApiKeyBindingDeleteResponse,
)
def api_key_binding_delete(
    binding_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_owner),
) -> ApiKeyBindingDeleteResponse:
    try:
        with without_org_data_isolation():
            delete_api_key_binding(
                db,
                binding_id=binding_id,
                actor_user_id=str(user.id),
            )
    except ApiKeyOrchestrationError as exc:
        _raise_api_key_error(exc)
    return ApiKeyBindingDeleteResponse(binding_id=binding_id)
