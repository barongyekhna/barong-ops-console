"""K 的接口层基建：权限依赖、作用域上下文、执行门禁与 provider 调用的错误翻译。

从 `router.py` 剥出来的第 1 桶（2026-09-03）。剥的顺序是「跨切面的先走」——
这十个函数被 router 里几十个路由共用，留在 6763 行的文件里等于把地基埋在阁楼。

**保持行为一字不变**：函数体原样搬运，没有改写。router 尾部有 re-export
兼容层，22 个存量测试文件一行不用改（兼容面由
`tests/backend/test_k_router_route_inventory.py::test_router_still_exports_everything_tests_import`
逐个符号钉住）。

⚠️ `_execute_provider_json` 里那个独立的 `SessionLocal()` **不能改成复用请求
session** —— 它是为了在出网前释放请求事务，防 idle-in-transaction。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .....api.deps import get_current_user
from .....core.roles import is_super_admin_role
from .....db.session import SessionLocal, get_db
from .....models.user import User
from .....services.ai_provider_router import AIExecutionRouter, AIProviderExecutionError
from .....services.module_execution_gate import (
    API_KEY_BINDING_MISSING_CODE,
    API_KEY_INJECTION_FAILED_CODE,
    MODULE_DISABLED_CODE,
    MODULE_NOT_REGISTERED_CODE,
    ModuleExecutionContext,
    ModuleExecutionGateError,
    ORG_CONTEXT_REQUIRED_CODE,
    require_module_execution_ready,
)
from .....services.permission_service import resolve_current_user_permission_info
from ..constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_WORKSPACE_KEY,
    MODULE_KEY,
    PERMISSION_PRODUCTS_READ,
    PERMISSION_READ,
    TARGET_ORGANIZATION_NAME,
)
from ..scope_shim import KScopeContext
from ..workflow_engine import KWorkflowExecutionError

logger = logging.getLogger(__name__)


def _require_k_permission(permission_key: str):
    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(db, user, request=request)
        allowed_permission_keys = {permission_key}
        if permission_key == PERMISSION_READ:
            allowed_permission_keys.add(PERMISSION_PRODUCTS_READ)
        if (
            permissions.is_owner_full_access
            or is_super_admin_role(user.role)
            or allowed_permission_keys.intersection(permissions.permission_keys)
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission_key}",
        )

    return dependency


def _scope_context(request: Request | None) -> KScopeContext:
    org_id = None
    if request is not None:
        org_id = getattr(request.state, "org_id", None)
        if org_id is None:
            org_context = getattr(request.state, "org_context", None)
            org_id = getattr(org_context, "org_id", None)
    workspace_key = str(org_id).strip() if org_id else DEFAULT_WORKSPACE_KEY
    return KScopeContext(
        workspace_key=workspace_key,
        business_context=DEFAULT_BUSINESS_CONTEXT,
        scope_mode="production",
    )


def _is_execution_configuration_error(code: str | None) -> bool:
    return code in {
        API_KEY_BINDING_MISSING_CODE,
        API_KEY_INJECTION_FAILED_CODE,
        MODULE_DISABLED_CODE,
        MODULE_NOT_REGISTERED_CODE,
        ORG_CONTEXT_REQUIRED_CODE,
    }


def _execution_configuration_message() -> str:
    return (
        "K module execution is not fully configured. The current user permission "
        "is valid, but the module requires an active organization context and "
        "usable API key binding."
    )


def _execution_error_reason(code: str | None) -> str:
    if code == API_KEY_BINDING_MISSING_CODE:
        return "missing_key"
    if code == API_KEY_INJECTION_FAILED_CODE:
        return "key_resolution_failed"
    if code == ORG_CONTEXT_REQUIRED_CODE:
        return "missing_context"
    if code == MODULE_DISABLED_CODE:
        return "module_disabled"
    if code == MODULE_NOT_REGISTERED_CODE:
        return "module_not_registered"
    return "execution_error"


def _structured_execution_error_detail(
    *,
    reason: str,
    message: str,
    code: str | None = None,
    module_id: str | None = None,
    org_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "status": "failed",
        "reason": reason,
        "message": message,
    }
    if code is not None:
        detail["code"] = code
    if module_id is not None:
        detail["module_id"] = module_id
    if org_id is not None:
        detail["org_id"] = org_id
    if extra:
        detail.update(extra)
    return detail


def _gate_error(exc: ModuleExecutionGateError) -> HTTPException:
    is_configuration_error = _is_execution_configuration_error(exc.code)
    status_code = status.HTTP_400_BAD_REQUEST if exc.code == ORG_CONTEXT_REQUIRED_CODE else (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if is_configuration_error
        else exc.status_code
    )
    message = (
        _execution_configuration_message()
        if is_configuration_error
        else str(exc)
    )
    return HTTPException(
        status_code=status_code,
        detail=_structured_execution_error_detail(
            reason=_execution_error_reason(exc.code),
            code=exc.code,
            message=message,
            module_id=exc.module_id,
            org_id=exc.org_id,
        ),
    )


def _workflow_error(exc: KWorkflowExecutionError) -> HTTPException:
    code = exc.error_report.get("code") if isinstance(exc.error_report, dict) else None
    if _is_execution_configuration_error(code if isinstance(code, str) else None):
        detail = dict(exc.error_report)
        detail.setdefault("status", "failed")
        detail.setdefault("reason", _execution_error_reason(code if isinstance(code, str) else None))
        detail["message"] = _execution_configuration_message()
        return HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
                if code == ORG_CONTEXT_REQUIRED_CODE
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=detail,
        )
    return HTTPException(status_code=exc.status_code, detail=exc.error_report)


def _execution_context(
    db: Session,
    *,
    request: Request,
    user: User,
    key_requirements: dict[str, str],
):
    try:
        return require_module_execution_ready(
            db,
            module_id=MODULE_KEY,
            user=user,
            request=request,
            key_requirements=key_requirements,
        )
    except ModuleExecutionGateError as exc:
        raise _gate_error(exc) from exc


def _execute_provider_json(
    db: Session,
    *,
    context: ModuleExecutionContext,
    provider: str,
    task_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    del db
    provider_db = SessionLocal()
    try:
        return AIExecutionRouter(provider_db).execute(
            provider=provider,
            task_type=task_type,  # type: ignore[arg-type]
            payload=payload,
            org=TARGET_ORGANIZATION_NAME,
            module_id=MODULE_KEY,
            execution_context=context,
        )
    except AIProviderExecutionError as exc:
        provider_detail = exc.structured_error()
        extra = provider_detail if isinstance(provider_detail, dict) else None
        raise HTTPException(
            status_code=exc.status_code,
            detail=_structured_execution_error_detail(
                reason="provider_error",
                code=exc.code,
                message=str(exc),
                module_id=MODULE_KEY,
                org_id=context.org_id,
                extra={"provider_error": extra} if extra else None,
            ),
        ) from exc
    except Exception as exc:
        logger.exception("K provider execution failed provider=%s", provider)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_structured_execution_error_detail(
                reason="provider_error",
                code="PROVIDER_EXECUTION_FAILED",
                message="Provider execution failed.",
                module_id=MODULE_KEY,
                org_id=context.org_id,
                extra={"provider": provider},
            ),
        ) from exc
    finally:
        provider_db.close()
