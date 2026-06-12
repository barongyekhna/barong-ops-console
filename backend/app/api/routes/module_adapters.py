from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.module_adapter import (
    ModuleAdapterAccessListResponse,
    ModuleAdapterRead,
    ModuleAdapterRegistryResponse,
)
from ...services.module_adapter_registry import (
    list_adapter_contracts,
    list_adapters_for_user,
)
from ..deps import get_current_user

router = APIRouter(prefix="/module-adapters", tags=["module-adapters"])


@router.get("/registry", response_model=ModuleAdapterRegistryResponse)
def module_adapter_registry(
    user: User = Depends(get_current_user),
) -> ModuleAdapterRegistryResponse:
    del user
    adapters = list_adapter_contracts()
    items = [
        ModuleAdapterRead.model_validate(adapter.model_dump())
        for adapter in adapters
    ]
    return ModuleAdapterRegistryResponse(items=items, count=len(items))


@router.get("/me", response_model=ModuleAdapterAccessListResponse)
def module_adapters_me(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ModuleAdapterAccessListResponse:
    permission_info, items = list_adapters_for_user(db, user)
    return ModuleAdapterAccessListResponse(
        user_id=user.id,
        role=user.role,
        is_owner_full_access=permission_info.is_owner_full_access,
        items=items,
        count=len(items),
    )
