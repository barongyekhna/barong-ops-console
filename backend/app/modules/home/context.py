"""主页访问上下文：这个人、在这个组织、能看哪些东西。

一次请求算一次；SSE 流里每轮重算（传 request=None 绕开按请求的权限缓存），
权限被收走、组织被停用、切了组织，3 秒内主页就跟着变。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.orm import Session

from ...core.roles import is_super_admin_role
from ...core.target_org_guard import (
    INTERNATIONAL_TRADE_ORG_NAME,
    resolve_caller_org,
    resolve_target_org,
)
from ...models.organization import OrganizationRecord
from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from ...services.permission_decision_engine import PermissionDecisionEngine
from ...services.permission_service import resolve_current_user_permission_info
from ...services.unified_permission_engine import UnifiedPermissionRequest

STORE_ORG_TYPE = "store"
FACTORY_ORG_TYPE = "factory"


@dataclass(frozen=True)
class HomeAccess:
    org: OrganizationRecord
    workspace_key: str
    is_store: bool
    is_factory: bool
    # F/W/H/B2B 的表没有 org 列，只能靠「调用者就是那个唯一目标组织」把门。
    is_target_org: bool
    permission_keys: frozenset[str]
    is_full_access: bool
    governance_read: bool

    @property
    def org_type(self) -> str:
        return str(self.org.org_type or "")


def resolve_home_access(
    db: Session,
    *,
    user: User,
    request: Request | None = None,
    org_id: str | None = None,
) -> HomeAccess | None:
    if org_id is None:
        org_id = resolve_caller_org(request, user) if request is not None else ""
        if not org_id:
            org_id = str(getattr(user, "organization_id", "") or "").strip()
    if not org_id:
        return None

    with without_org_data_isolation():
        org = db.get(OrganizationRecord, org_id)
    if org is None or org.status != "active":
        return None

    target = resolve_target_org(db, INTERNATIONAL_TRADE_ORG_NAME)
    is_target_org = target is not None and target.org_id == org.org_id

    info = resolve_current_user_permission_info(db, user, request=request)
    is_full_access = bool(info.is_owner_full_access) or is_super_admin_role(user.role)

    governance_read = is_full_access or _governance_read(
        db, request=request, user=user, org_id=org.org_id
    )

    return HomeAccess(
        org=org,
        workspace_key=org.org_id,
        is_store=str(org.org_type or "") == STORE_ORG_TYPE,
        is_factory=str(org.org_type or "") == FACTORY_ORG_TYPE,
        is_target_org=is_target_org,
        permission_keys=frozenset(info.permission_keys),
        is_full_access=is_full_access,
        governance_read=governance_read,
    )


def _governance_read(
    db: Session, *, request: Request | None, user: User, org_id: str
) -> bool:
    """与 `api/routes/dashboard.py::_can_read` 同一规则：审批卡沿用旧主页的门。"""
    try:
        decision = PermissionDecisionEngine(db, request=request).decide_platform_metadata(
            UnifiedPermissionRequest(
                user_id=user.id,
                org_id=org_id,
                module_id="GOVERNANCE",
                action="read",
                role=user.role,
                scope_type="global",
                scope_key="*",
                source="home_dashboard",
            )
        )
    except Exception:  # noqa: BLE001 - 判不出来就当没有，绝不因此炸整页
        return False
    return bool(decision.allowed)
