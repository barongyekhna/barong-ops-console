from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.execution_provider import (
    ExecutionProviderAccessListResponse,
    ExecutionProviderRead,
    ExecutionProviderRegistryResponse,
)
from ...services.execution_provider_registry import (
    list_execution_provider_contracts,
    list_execution_providers_for_user,
)
from ..deps import get_current_user

router = APIRouter(prefix="/execution-providers", tags=["execution-providers"])


@router.get("/registry", response_model=ExecutionProviderRegistryResponse)
def execution_provider_registry(
    user: User = Depends(get_current_user),
) -> ExecutionProviderRegistryResponse:
    del user
    providers = list_execution_provider_contracts()
    items = [
        ExecutionProviderRead.model_validate(provider.model_dump())
        for provider in providers
    ]
    return ExecutionProviderRegistryResponse(items=items, count=len(items))


@router.get("/me", response_model=ExecutionProviderAccessListResponse)
def execution_providers_me(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExecutionProviderAccessListResponse:
    permission_info, items = list_execution_providers_for_user(db, user)
    return ExecutionProviderAccessListResponse(
        user_id=user.id,
        role=user.role,
        is_owner_full_access=permission_info.is_owner_full_access,
        items=items,
        count=len(items),
    )
