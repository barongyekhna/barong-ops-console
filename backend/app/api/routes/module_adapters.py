from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.permissions import SCOPE_ORGANIZATION
from ...db.session import get_db
from ...middleware.org_context import get_org_context
from ...models.user import User
from ...schemas.execution_router import ExecutionRouterResponse
from ...schemas.module_adapter import (
    ModuleAdapterAccessListResponse,
    ModuleAdapterRead,
    ModuleAdapterRegistryResponse,
)
from ...services.module_adapter_registry import (
    get_adapter_contract,
    list_adapter_contracts,
    list_adapters_for_user,
    request_adapter_action_execution,
)
from ...services.unified_permission_engine import (
    UnifiedPermissionEngine,
    UnifiedPermissionRequest,
)
from ..deps import require_rbac

router = APIRouter(prefix="/module-adapters", tags=["module-adapters"])


@router.get("/registry", response_model=ModuleAdapterRegistryResponse)
def module_adapter_registry(
    user: User = Depends(require_rbac("C14", "admin")),
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
    user: User = Depends(require_rbac("C14", "admin")),
) -> ModuleAdapterAccessListResponse:
    permission_info, items = list_adapters_for_user(db, user)
    return ModuleAdapterAccessListResponse(
        user_id=user.id,
        role=user.role,
        is_owner_full_access=permission_info.is_owner_full_access,
        items=items,
        count=len(items),
    )


@router.post(
    "/{adapter_key}/actions/{action_key}/request",
    response_model=ExecutionRouterResponse,
)
def module_adapter_action_request(
    adapter_key: str,
    action_key: str,
    payload: dict[str, object],
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("C09", "execute")),
) -> ExecutionRouterResponse:
    adapter = get_adapter_contract(adapter_key)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="C08 adapter is not registered.",
        )
    action_contract = next(
        (
            contract
            for contract in adapter.action_contracts
            if contract.action_key == action_key
        ),
        None,
    )
    if action_contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="C08 adapter action is not registered.",
        )

    org_context = get_org_context(request)
    if org_context is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="C18H org context is required for execution routing.",
        )

    permission_engine = UnifiedPermissionEngine(db)
    c18f_decision = permission_engine.decide(
        UnifiedPermissionRequest(
            user_id=user.id,
            org_id=org_context.org_id,
            module_id=adapter.module_key,
            action="execute",
            role=org_context.role,
            scope_type=SCOPE_ORGANIZATION,
            scope_key=org_context.org_id,
            source="c08_adapter_execution_router_hook",
        )
    )
    c05_decision = permission_engine.decide(
        UnifiedPermissionRequest(
            user_id=user.id,
            org_id=org_context.org_id,
            module_id=adapter.module_key,
            action="execute",
            role=org_context.role,
            scope_type=SCOPE_ORGANIZATION,
            scope_key=org_context.org_id,
            permission_key=action_contract.required_permission,
            source="c08_adapter_execution_router_hook",
        )
    )

    return request_adapter_action_execution(
        org_id=org_context.org_id,
        module_id=adapter.module_key,
        action=action_key,
        payload=payload,
        context={
            "adapter_key": adapter.adapter_key,
            "org_context": org_context,
            "user_id": user.id,
            "role": org_context.role,
            "request_id": org_context.request_id,
            "c18h_context_applied": True,
            "c18f_permission_decision": c18f_decision,
            "c05_permission_result": c05_decision,
        },
    )
