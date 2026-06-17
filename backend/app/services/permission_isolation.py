from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.org_membership import OrgMembershipRecord
from ..models.user import User
from ..schemas.module_binding import GLOBAL_MODULE_BOUND_ORG
from ..schemas.permission import (
    Permission,
    PermissionAction,
    PermissionDecision,
    PermissionRole,
)
from .module_binding_service import ModuleBindingNotFoundError, get_module_binding

ACTION_ORDER = (
    PermissionAction.READ,
    PermissionAction.WRITE,
    PermissionAction.DELETE,
    PermissionAction.EXECUTE,
    PermissionAction.ADMIN,
)

OWNER_ACTIONS = frozenset(ACTION_ORDER)
ADMIN_ACTIONS = frozenset(
    (
        PermissionAction.READ,
        PermissionAction.WRITE,
        PermissionAction.EXECUTE,
    )
)
MEMBER_ACTIONS = frozenset((PermissionAction.READ,))

MODULE_ACTION_RULES = {
    "K-series": frozenset(
        (
            PermissionAction.READ,
            PermissionAction.WRITE,
            PermissionAction.EXECUTE,
        )
    ),
    "C-series": frozenset((PermissionAction.ADMIN,)),
    "P-series": frozenset((PermissionAction.WRITE,)),
}
DEFAULT_MODULE_ACTIONS = frozenset(
    (
        PermissionAction.READ,
        PermissionAction.WRITE,
        PermissionAction.EXECUTE,
        PermissionAction.ADMIN,
    )
)


def _normalize_user_id(user_id: str | int) -> str:
    normalized = str(user_id).strip()
    if not normalized:
        return "[missing_user_id]"
    return normalized


def _normalize_org_id(org_id: str) -> str:
    normalized = org_id.strip()
    if not normalized:
        return "[missing_org_id]"
    return normalized


def _normalize_module_id(module_id: str) -> str:
    normalized = module_id.strip()
    if not normalized:
        return "[missing_module_id]"
    return normalized


def _normalize_action(action: PermissionAction | str) -> PermissionAction:
    if isinstance(action, PermissionAction):
        return action
    return PermissionAction(action.strip().lower())


def _sorted_actions(actions: Iterable[PermissionAction]) -> list[PermissionAction]:
    action_set = set(actions)
    return [action for action in ACTION_ORDER if action in action_set]


def _decision(
    *,
    user_id: str,
    org_id: str,
    module_id: str,
    action: PermissionAction,
    role: PermissionRole | None,
    allowed: bool,
    denial_code: str | None,
    reason: str,
    owner_override_applied: bool = False,
    permission: Permission | None = None,
    c18c_org_membership_checked: bool = False,
    c18d_module_binding_checked: bool = False,
) -> PermissionDecision:
    return PermissionDecision(
        user_id=user_id,
        org_id=org_id,
        module_id=module_id,
        action=action,
        role=role,
        allowed=allowed,
        denied=not allowed,
        denial_code=denial_code,
        reason=reason,
        owner_override_applied=owner_override_applied,
        permission=permission,
        c18c_org_membership_checked=c18c_org_membership_checked,
        c18d_module_binding_checked=c18d_module_binding_checked,
    )


def _deny(
    *,
    user_id: str,
    org_id: str,
    module_id: str,
    action: PermissionAction,
    denial_code: str,
    reason: str,
    role: PermissionRole | None = None,
    c18c_org_membership_checked: bool = False,
    c18d_module_binding_checked: bool = False,
) -> PermissionDecision:
    return _decision(
        user_id=user_id,
        org_id=org_id,
        module_id=module_id,
        action=action,
        role=role,
        allowed=False,
        denial_code=denial_code,
        reason=reason,
        c18c_org_membership_checked=c18c_org_membership_checked,
        c18d_module_binding_checked=c18d_module_binding_checked,
    )


def _allow(
    *,
    user_id: str,
    org_id: str,
    module_id: str,
    action: PermissionAction,
    role: PermissionRole,
    actions: Iterable[PermissionAction],
    reason: str,
    owner_override_applied: bool = False,
    c18c_org_membership_checked: bool = False,
    c18d_module_binding_checked: bool = False,
) -> PermissionDecision:
    permission = Permission(
        user_id=user_id,
        org_id=org_id,
        module_id=module_id,
        actions=_sorted_actions(actions),
        role=role,
    )
    return _decision(
        user_id=user_id,
        org_id=org_id,
        module_id=module_id,
        action=action,
        role=role,
        allowed=True,
        denial_code=None,
        reason=reason,
        owner_override_applied=owner_override_applied,
        permission=permission,
        c18c_org_membership_checked=c18c_org_membership_checked,
        c18d_module_binding_checked=c18d_module_binding_checked,
    )


def _get_user(db: Session, user_id: str) -> User | None:
    try:
        user_pk = int(user_id)
    except ValueError:
        return None
    return db.get(User, user_pk)


def _active_membership(
    db: Session,
    *,
    user_id: str,
    org_id: str,
) -> OrgMembershipRecord | None:
    return db.scalar(
        select(OrgMembershipRecord).where(
            OrgMembershipRecord.user_id == user_id,
            OrgMembershipRecord.org_id == org_id,
            OrgMembershipRecord.status == "active",
        )
    )


def _role_from_membership(membership: OrgMembershipRecord) -> PermissionRole:
    return PermissionRole(membership.role)


def _role_actions(role: PermissionRole) -> frozenset[PermissionAction]:
    if role == PermissionRole.OWNER:
        return OWNER_ACTIONS
    if role == PermissionRole.ADMIN:
        return ADMIN_ACTIONS
    return MEMBER_ACTIONS


def _module_actions(module_id: str) -> frozenset[PermissionAction]:
    return MODULE_ACTION_RULES.get(module_id, DEFAULT_MODULE_ACTIONS)


def _module_bound_to_org_in_db(
    db: Session,
    *,
    module_id: str,
    org_id: str,
) -> bool:
    try:
        binding = get_module_binding(module_id, db=db)
    except ModuleBindingNotFoundError:
        return False
    if not binding.enabled:
        return False
    return (
        binding.mode == "global"
        or GLOBAL_MODULE_BOUND_ORG in binding.bound_orgs
        or org_id in binding.bound_orgs
    )


def check_permission(
    db: Session,
    user_id: str | int,
    org_id: str,
    module_id: str,
    action: PermissionAction | str,
) -> PermissionDecision:
    scoped_user_id = _normalize_user_id(user_id)
    scoped_org_id = _normalize_org_id(org_id)
    scoped_module_id = _normalize_module_id(module_id)

    try:
        requested_action = _normalize_action(action)
    except ValueError:
        requested_action = PermissionAction.READ
        return _deny(
            user_id=scoped_user_id,
            org_id=scoped_org_id,
            module_id=scoped_module_id,
            action=requested_action,
            denial_code="c18f_invalid_action",
            reason="Permission action must be read, write, delete, execute, or admin.",
        )

    user = _get_user(db, scoped_user_id)
    if user is None:
        return _deny(
            user_id=scoped_user_id,
            org_id=scoped_org_id,
            module_id=scoped_module_id,
            action=requested_action,
            denial_code="c18f_user_not_found",
            reason="User was not found for permission evaluation.",
        )
    if not user.is_active:
        return _deny(
            user_id=scoped_user_id,
            org_id=scoped_org_id,
            module_id=scoped_module_id,
            action=requested_action,
            denial_code="c18f_user_inactive",
            reason="Inactive users cannot execute org/module permissions.",
        )

    membership = _active_membership(db, user_id=scoped_user_id, org_id=scoped_org_id)
    if membership is None:
        return _deny(
            user_id=scoped_user_id,
            org_id=scoped_org_id,
            module_id=scoped_module_id,
            action=requested_action,
            denial_code="c18f_user_not_in_org",
            reason="Active C18C organization membership is required.",
            c18c_org_membership_checked=True,
        )

    role = _role_from_membership(membership)
    if not _module_bound_to_org_in_db(
        db,
        module_id=scoped_module_id,
        org_id=scoped_org_id,
    ):
        return _deny(
            user_id=scoped_user_id,
            org_id=scoped_org_id,
            module_id=scoped_module_id,
            action=requested_action,
            role=role,
            denial_code="c18f_module_not_bound_to_org",
            reason="C18D module binding is required for the target organization.",
            c18c_org_membership_checked=True,
            c18d_module_binding_checked=True,
        )

    role_actions = _role_actions(role)
    if requested_action not in role_actions:
        return _deny(
            user_id=scoped_user_id,
            org_id=scoped_org_id,
            module_id=scoped_module_id,
            action=requested_action,
            role=role,
            denial_code="c18f_role_action_denied",
            reason="Membership role does not allow the requested action.",
            c18c_org_membership_checked=True,
            c18d_module_binding_checked=True,
        )

    module_actions = _module_actions(scoped_module_id)
    if requested_action not in module_actions:
        return _deny(
            user_id=scoped_user_id,
            org_id=scoped_org_id,
            module_id=scoped_module_id,
            action=requested_action,
            role=role,
            denial_code="c18f_module_action_denied",
            reason="Module-level C18F action policy denies the requested action.",
            c18c_org_membership_checked=True,
            c18d_module_binding_checked=True,
        )

    return _allow(
        user_id=scoped_user_id,
        org_id=scoped_org_id,
        module_id=scoped_module_id,
        action=requested_action,
        role=role,
        actions=role_actions.intersection(module_actions),
        reason="C18C membership, C18D binding, and role/module actions allow access.",
        c18c_org_membership_checked=True,
        c18d_module_binding_checked=True,
    )
