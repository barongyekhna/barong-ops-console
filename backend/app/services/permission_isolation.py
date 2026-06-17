from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.permissions import SCOPE_ORGANIZATION
from ..schemas.permission import PermissionAction, PermissionDecision
from .unified_permission_engine import (
    UnifiedPermissionEngine,
    UnifiedPermissionRequest,
)


def check_permission(
    db: Session,
    user_id: str | int,
    org_id: str,
    module_id: str,
    action: PermissionAction | str,
) -> PermissionDecision:
    decision = UnifiedPermissionEngine(db).decide(
        UnifiedPermissionRequest(
            user_id=user_id,
            org_id=org_id,
            module_id=module_id,
            action=action,
            role=None,
            scope_type=SCOPE_ORGANIZATION,
            scope_key=org_id,
            source="c18f_permission_isolation_wrapper",
        )
    )
    return decision.to_permission_decision()
