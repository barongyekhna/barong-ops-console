from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.module_control import ModuleControlStateRecord
from ..models.org_membership import OrgMembershipRecord
from ..models.organization import OrganizationRecord
from ..models.user import User
from .api_key_orchestration import (
    ApiKeyInjectionContext,
    ApiKeyIsolationError,
    ApiKeyOrchestrationError,
    resolve_module_api_key_for_injection,
)
from .data_isolation import current_org_data_isolation_context
from .event_collector import emit_event, set_current_event_context
from .module_registry import get_module_manifest

MODULE_DISABLED_CODE = "MODULE_DISABLED"
MODULE_CONTROL_MISSING_CODE = "MODULE_CONTROL_MISSING"
MODULE_NOT_REGISTERED_CODE = "MODULE_NOT_REGISTERED"
ORG_CONTEXT_REQUIRED_CODE = "ORG_CONTEXT_REQUIRED"
API_KEY_BINDING_MISSING_CODE = "API_KEY_BINDING_MISSING"
API_KEY_INJECTION_FAILED_CODE = "API_KEY_INJECTION_FAILED"

LEGACY_EXECUTION_MODULE_IDS = {
    "foundation_demo": "experimental.foundation_demo",
    "n8n_test_bridge": "integration.n8n_test_bridge",
}


@dataclass(frozen=True)
class ModuleExecutionKey:
    step_name: str
    key_alias: str
    key_id: str
    name: str
    url: str
    header_name: str
    header_value: str

    def redacted(self) -> dict[str, str]:
        return {
            "step_name": self.step_name,
            "key_alias": self.key_alias,
            "key_id": self.key_id,
            "name": self.name,
            "url": self.url,
            "header_name": self.header_name,
            "header_value": "***",
        }


@dataclass(frozen=True)
class ModuleExecutionContext:
    org_id: str
    requested_module_id: str
    control_module_id: str
    keys: Mapping[str, ModuleExecutionKey]

    def key_for_step(self, step_name: str) -> ModuleExecutionKey:
        return self.keys[step_name]

    def redacted_key_map(self) -> dict[str, dict[str, str]]:
        return {step: key.redacted() for step, key in self.keys.items()}


class ModuleExecutionGateError(PermissionError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 403,
        org_id: str | None = None,
        module_id: str | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.org_id = org_id
        self.module_id = module_id
        super().__init__(message)


def control_module_id_for_execution(module_id: str) -> str:
    normalized = module_id.strip()
    return LEGACY_EXECUTION_MODULE_IDS.get(normalized, normalized)


def _request_state_value(request: Request | None, *names: str) -> str | None:
    if request is None:
        return None
    for name in names:
        value = getattr(request.state, name, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    org_context = getattr(request.state, "org_context", None)
    value = getattr(org_context, "org_id", None)
    if value is not None and str(value).strip():
        return str(value).strip()
    return None


def _single_active_membership_org(db: Session, *, user_id: str) -> str | None:
    rows = list(
        db.scalars(
            select(OrgMembershipRecord)
            .where(
                OrgMembershipRecord.user_id == user_id,
                OrgMembershipRecord.status == "active",
            )
            .order_by(OrgMembershipRecord.joined_at, OrgMembershipRecord.org_id)
            .limit(2)
        )
    )
    if len(rows) == 1:
        return rows[0].org_id
    return None


def _owner_org(db: Session, *, user_id: str) -> str | None:
    row = db.scalar(
        select(OrganizationRecord.org_id)
        .where(
            OrganizationRecord.owner_user_id == user_id,
            OrganizationRecord.status == "active",
        )
        .order_by(OrganizationRecord.created_at, OrganizationRecord.org_id)
        .limit(1)
    )
    return row


def _organization_is_active(db: Session, *, org_id: str) -> bool:
    """该组织存在且未被停用。

    与 HTTP 路径的 `_resolve_org` 对齐：那边用 `user.organization_id` 兜底时
    也会先确认 `organization.status == "active"`，否则继续往下找。
    """
    return (
        db.scalar(
            select(OrganizationRecord.org_id).where(
                OrganizationRecord.org_id == org_id,
                OrganizationRecord.status == "active",
            )
        )
        is not None
    )

def resolve_execution_org_id(
    db: Session,
    *,
    user: User | None = None,
    request: Request | None = None,
    explicit_org_id: str | None = None,
) -> str:
    # 显式指定 / 请求态 / 隔离上下文：这三个是「当前这次调用明确说了是哪个组织」，
    # 优先级最高，没有歧义。
    for candidate in (
        explicit_org_id,
        _request_state_value(request, "org_id", "active_org_id", "session_org_id"),
        getattr(current_org_data_isolation_context(), "org_id", None),
    ):
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()

    if user is not None:
        user_id = str(user.id)
        # **membership 必须排在 user.organization_id 前面。**
        # 2026-08-31 体检：这里原本先读 `user.organization_id`（一列裸字符串，
        # 无外键约束、不保证与 org_memberships 同步），而 HTTP 路径
        # （middleware/org_context.py 的 _resolve_org）先看唯一 active membership。
        # 同一个用户前台算出一个组织、后台任务算出另一个 —— 而 GEO/SEO/P 的发布
        # 全靠 worker 跑（worker 场景 request=None，正好落到这一段），
        # 算错组织就是内容发到错的站。这里的顺序与 HTTP 路径保持一致。
        membership_org_id = _single_active_membership_org(db, user_id=user_id)
        if membership_org_id is not None:
            return membership_org_id

        # 兼容位：只有在拿不到 membership 时才用它，且该组织必须是 active 的
        # （HTTP 路径同样会校验 organization.status == "active"）。
        legacy_org_id = getattr(user, "organization_id", None)
        if legacy_org_id is not None and str(legacy_org_id).strip():
            candidate = str(legacy_org_id).strip()
            if _organization_is_active(db, org_id=candidate):
                return candidate

        owner_org_id = _owner_org(db, user_id=user_id)
        if owner_org_id is not None:
            return owner_org_id

    raise ModuleExecutionGateError(
        ORG_CONTEXT_REQUIRED_CODE,
        "Module execution requires an organization context.",
        status_code=403,
    )


def _ensure_control_state(
    db: Session,
    *,
    org_id: str,
    module_id: str,
) -> ModuleControlStateRecord:
    record = db.scalar(
        select(ModuleControlStateRecord).where(
            ModuleControlStateRecord.org_id == org_id,
            ModuleControlStateRecord.module_id == module_id,
        )
    )
    if record is not None:
        return record
    if get_module_manifest(module_id) is None:
        raise ModuleExecutionGateError(
            MODULE_NOT_REGISTERED_CODE,
            "Module is not registered.",
            status_code=404,
            org_id=org_id,
            module_id=module_id,
        )
    record = ModuleControlStateRecord(
        org_id=org_id,
        module_id=module_id,
        enabled=True,
        runtime_status="active",
        metadata_json={"source": "auto_registered_from_execution_gate"},
    )
    db.add(record)
    db.flush()
    return record


def _emit_gate_event(
    *,
    org_id: str,
    module_id: str,
    status: str,
    action: str,
    user: User | None,
    payload: Mapping[str, object],
) -> None:
    set_current_event_context(org_id=org_id, user_id=str(user.id) if user else None)
    emit_event(
        event_type="module.execution_gate",
        module="system",
        action=action,
        source="backend",
        status=status,  # type: ignore[arg-type]
        user_id=str(user.id) if user else None,
        org_id=org_id,
        payload={
            "module_id": module_id,
            **dict(payload),
        },
    )


def _raise_disabled(
    *,
    org_id: str,
    module_id: str,
    user: User | None,
) -> None:
    _emit_gate_event(
        org_id=org_id,
        module_id=module_id,
        status="failed",
        action="module.execution.blocked",
        user=user,
        payload={"code": MODULE_DISABLED_CODE},
    )
    raise ModuleExecutionGateError(
        MODULE_DISABLED_CODE,
        "Module is disabled.",
        status_code=403,
        org_id=org_id,
        module_id=module_id,
    )


def _resolve_key(
    db: Session,
    *,
    org_id: str,
    module_id: str,
    step_name: str,
    key_alias: str,
) -> ModuleExecutionKey:
    try:
        context = resolve_module_api_key_for_injection(
            db,
            org_id=org_id,
            module_id=module_id,
            key_alias=key_alias,
        )
    except ApiKeyIsolationError as exc:
        raise ModuleExecutionGateError(
            API_KEY_BINDING_MISSING_CODE,
            "Required API key binding is missing or not usable.",
            status_code=403,
            org_id=org_id,
            module_id=module_id,
        ) from exc
    except ApiKeyOrchestrationError as exc:
        raise ModuleExecutionGateError(
            API_KEY_INJECTION_FAILED_CODE,
            "Required API key could not be resolved.",
            status_code=403,
            org_id=org_id,
            module_id=module_id,
        ) from exc
    return ModuleExecutionKey(
        step_name=step_name,
        key_alias=context.key_alias,
        key_id=context.key_id,
        name=context.name,
        url=context.url,
        header_name=context.header_name,
        header_value=context.header_value,
    )


def require_module_execution_ready(
    db: Session,
    *,
    module_id: str,
    user: User | None = None,
    request: Request | None = None,
    explicit_org_id: str | None = None,
    key_requirements: Mapping[str, str] | None = None,
) -> ModuleExecutionContext:
    org_id = resolve_execution_org_id(
        db,
        user=user,
        request=request,
        explicit_org_id=explicit_org_id,
    )
    control_module_id = control_module_id_for_execution(module_id)
    record = _ensure_control_state(
        db,
        org_id=org_id,
        module_id=control_module_id,
    )
    if not record.enabled or record.runtime_status == "disabled":
        _raise_disabled(org_id=org_id, module_id=control_module_id, user=user)

    resolved_keys = {
        step_name: _resolve_key(
            db,
            org_id=org_id,
            module_id=control_module_id,
            step_name=step_name,
            key_alias=key_alias,
        )
        for step_name, key_alias in (key_requirements or {}).items()
    }
    _emit_gate_event(
        org_id=org_id,
        module_id=control_module_id,
        status="success",
        action="module.execution.allowed",
        user=user,
        payload={
            "requested_module_id": module_id,
            "resolved_steps": sorted(resolved_keys),
        },
    )
    return ModuleExecutionContext(
        org_id=org_id,
        requested_module_id=module_id,
        control_module_id=control_module_id,
        keys=resolved_keys,
    )
