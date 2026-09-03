from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.permissions import (
    SCOPE_GLOBAL,
    SCOPE_ORGANIZATION,
    validate_permission_key,
    validate_scope,
)
from ..core.rbac import (
    ACTION_INTERNAL,
    ACTION_ADMIN,
    ACTION_EXECUTE,
    ACTION_READ,
    ACTION_WRITE,
    ROLE_SYSTEM,
    RoleMetadata,
    get_role_metadata,
)
from ..core.roles import is_owner_role, is_super_admin_role, normalize_role
from ..models.org_membership import OrgMembershipRecord
from ..models.permission import PermissionRegistry, UserPermissionAssignment
from ..models.user import User
from ..repositories.permissions import (
    get_permission as get_permission_record,
    list_enabled_user_assignments,
    list_role_default_permissions,
)
from ..schemas.module_binding import GLOBAL_MODULE_BOUND_ORG
from ..schemas.permission import (
    Permission,
    PermissionAction,
    PermissionDecision,
    PermissionRole,
)
from .module_binding_service import ModuleBindingNotFoundError, get_module_binding

UnifiedDecisionState = Literal["allow", "deny", "partial"]

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
DEFAULT_MODULE_ACTIONS = frozenset(ACTION_ORDER)

OWNER_PLATFORM_PERMISSION_CATEGORIES = frozenset(("admin", "system"))

LEGACY_MODULE_ACTION_METADATA = MappingProxyType(
    {
        "AUTH": (ACTION_READ,),
        "CORE": (ACTION_READ,),
        "ADMIN": (ACTION_ADMIN,),
        "AUDIT": (ACTION_ADMIN,),
        "REGISTRY": (ACTION_ADMIN,),
        "GOVERNANCE": (ACTION_READ, ACTION_WRITE, ACTION_ADMIN),
        "OPERATIONS": (ACTION_READ, ACTION_WRITE, ACTION_EXECUTE),
        "C09": (ACTION_EXECUTE,),
        "C13": (ACTION_ADMIN,),
        "C14": (ACTION_ADMIN,),
        "C14X": (ACTION_ADMIN,),
        "C15": (ACTION_EXECUTE,),
        "C15A": (ACTION_EXECUTE,),
        "C15B": (ACTION_EXECUTE, ACTION_INTERNAL),
        "C15C": (ACTION_EXECUTE,),
        "C15D": (ACTION_EXECUTE, ACTION_INTERNAL),
        "C15E": (ACTION_EXECUTE,),
        "C15F": (ACTION_EXECUTE,),
        "C15H": (ACTION_EXECUTE,),
        "C16": (ACTION_ADMIN,),
        "K-series": (ACTION_WRITE, ACTION_EXECUTE),
        "P-series": (ACTION_WRITE, ACTION_EXECUTE),
        "SEO": (ACTION_EXECUTE,),
    }
)


@dataclass(frozen=True)
class LegacyPermissionMetadata:
    role: str
    normalized_role: str
    legacy_alias_of: str | None
    module: str
    action: str
    role_actions: frozenset[str]
    module_actions: tuple[str, ...]
    role_known: bool
    module_known: bool


@dataclass(frozen=True)
class UnifiedPermissionRequest:
    user_id: str | int | None
    org_id: str | None
    module_id: str
    action: str | PermissionAction
    role: str | None
    scope_type: str
    scope_key: str
    permission_key: str | None = None
    source: str = "unified_permission_engine"


@dataclass(frozen=True)
class UnifiedPermissionDecision:
    user_id: str
    org_id: str | None
    module_id: str
    action: str
    role: str | None
    scope_type: str
    scope_key: str
    decision: UnifiedDecisionState
    denial_code: str | None
    reason: str
    permission_key: str | None = None
    permission: PermissionRegistry | None = None
    allowed_actions: tuple[PermissionAction, ...] = ()
    legacy_rbac_metadata: LegacyPermissionMetadata | None = None
    c18c_org_membership_checked: bool = False
    c18d_module_binding_checked: bool = False
    c05_assignment_checked: bool = False
    c05_assignment_matched: bool = False
    c05_role_defaults_count: int = 0
    c18f_isolation_applied: bool = False
    owner_platform_role: bool = False

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    @property
    def denied(self) -> bool:
        return self.decision == "deny"

    @property
    def partial(self) -> bool:
        return self.decision == "partial"

    def to_permission_decision(self) -> PermissionDecision:
        action = _normalize_permission_action(self.action) or PermissionAction.READ
        role = _permission_role(self.role)
        permission = None
        if self.allowed and role is not None and self.allowed_actions:
            permission = Permission(
                user_id=self.user_id,
                org_id=self.org_id or "platform",
                module_id=self.module_id,
                actions=list(self.allowed_actions),
                role=role,
            )
        return PermissionDecision(
            user_id=self.user_id,
            org_id=self.org_id or "platform",
            module_id=self.module_id,
            action=action,
            role=role,
            allowed=self.allowed,
            denied=not self.allowed,
            denial_code=None if self.allowed else self.denial_code,
            reason=self.reason,
            owner_override_applied=False,
            permission=permission,
            c18c_org_membership_checked=self.c18c_org_membership_checked,
            c18d_module_binding_checked=self.c18d_module_binding_checked,
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_identity(value: str | int | None, missing: str) -> str:
    if value is None:
        return missing
    normalized = str(value).strip()
    return normalized or missing


def _normalize_module_id(module_id: str) -> str:
    normalized = module_id.strip()
    return normalized or "[missing_module_id]"


def _normalize_action(action: str | PermissionAction) -> str:
    if isinstance(action, PermissionAction):
        return action.value
    normalized = action.strip().lower()
    return normalized or "read"


def _normalize_permission_action(
    action: str | PermissionAction,
) -> PermissionAction | None:
    if isinstance(action, PermissionAction):
        return action
    try:
        return PermissionAction(action.strip().lower())
    except ValueError:
        return None


def _permission_role(role: str | None) -> PermissionRole | None:
    if role is None:
        return None
    try:
        return PermissionRole(normalize_role(role))
    except ValueError:
        return None


def _sorted_actions(
    actions: Iterable[PermissionAction],
) -> tuple[PermissionAction, ...]:
    action_set = set(actions)
    return tuple(action for action in ACTION_ORDER if action in action_set)


def _role_actions(role: str) -> frozenset[PermissionAction]:
    normalized = normalize_role(role)
    if normalized == PermissionRole.OWNER.value:
        return OWNER_ACTIONS
    if normalized == PermissionRole.ADMIN.value:
        return ADMIN_ACTIONS
    return MEMBER_ACTIONS


def _module_actions(module_id: str) -> frozenset[PermissionAction]:
    return MODULE_ACTION_RULES.get(module_id, DEFAULT_MODULE_ACTIONS)


def _legacy_metadata(
    role: str,
    module_id: str,
    action: str,
) -> LegacyPermissionMetadata:
    role_metadata: RoleMetadata = get_role_metadata(role)
    module_actions = LEGACY_MODULE_ACTION_METADATA.get(module_id, ())
    return LegacyPermissionMetadata(
        role=role_metadata.role,
        normalized_role=role_metadata.normalized_role,
        legacy_alias_of=role_metadata.legacy_alias_of,
        module=module_id,
        action=action,
        role_actions=role_metadata.role_actions,
        module_actions=tuple(module_actions),
        role_known=role_metadata.role_known,
        module_known=module_id in LEGACY_MODULE_ACTION_METADATA,
    )


def _assignment_matches_scope(
    assignment: UserPermissionAssignment,
    *,
    scope_type: str,
    scope_key: str,
) -> bool:
    if assignment.scope_type == SCOPE_GLOBAL and assignment.scope_key == "*":
        return True
    if scope_type == SCOPE_GLOBAL:
        return False
    if assignment.scope_type != scope_type:
        return False
    return assignment.scope_key in {scope_key, "*"}


class UnifiedPermissionEngine:
    def __init__(
        self,
        db: Session | None = None,
        *,
        resolution_cache: object | None = None,
    ) -> None:
        self.db = db
        self.resolution_cache = resolution_cache

    def decide(self, request: UnifiedPermissionRequest) -> UnifiedPermissionDecision:
        if request.permission_key is not None:
            return self.decide_permission_key(request)
        if request.org_id is not None:
            return self.decide_org_module(request)
        return self.decide_platform_metadata(request)

    def decide_org_module(
        self,
        request: UnifiedPermissionRequest,
    ) -> UnifiedPermissionDecision:
        db = self._require_db()
        user_id = _normalize_identity(request.user_id, "[missing_user_id]")
        org_id = _normalize_identity(request.org_id, "[missing_org_id]")
        module_id = _normalize_module_id(request.module_id)
        action = _normalize_permission_action(request.action)
        action_text = _normalize_action(request.action)
        if action is None:
            return self._deny(
                request,
                user_id=user_id,
                org_id=org_id,
                module_id=module_id,
                action=PermissionAction.READ.value,
                denial_code="c18f_invalid_action",
                reason="Permission action must be read, write, delete, execute, or admin.",
                c18f_isolation_applied=True,
            )

        user, membership = self._get_user_org_context(
            user_id=user_id,
            org_id=org_id,
        )
        if user is None:
            return self._deny(
                request,
                user_id=user_id,
                org_id=org_id,
                module_id=module_id,
                action=action.value,
                denial_code="c18f_user_not_found",
                reason="User was not found for permission evaluation.",
                c18f_isolation_applied=True,
            )
        if not user.is_active:
            return self._deny(
                request,
                user_id=user_id,
                org_id=org_id,
                module_id=module_id,
                action=action.value,
                denial_code="c18f_user_inactive",
                reason="Inactive users cannot execute org/module permissions.",
                c18f_isolation_applied=True,
            )

        if membership is None:
            return self._deny(
                request,
                user_id=user_id,
                org_id=org_id,
                module_id=module_id,
                action=action.value,
                denial_code="c18f_user_not_in_org",
                reason="Active C18H/C18C organization context is required.",
                c18c_org_membership_checked=True,
                c18f_isolation_applied=True,
                owner_platform_role=is_owner_role(user.role),
            )

        role = normalize_role(membership.role)
        rbac_metadata = _legacy_metadata(role, module_id, action_text)

        # 平台 owner 在模块绑定门之前放行。
        # 2026-08-31 体检：module_bindings 表是 0 行，而绑定查不到就返回 False，
        # 于是这道门对所有人一律拒绝；又因为它排在 owner 豁免之前，连 owner 都被挡，
        # 结果是 owner 打不开操作日志——审计能力对最该有审计能力的人关闭。
        # 引擎另一条路径 decide_permission_key 一直有 owner 分支，只有这条漏了。
        # 非 owner 仍然照常受绑定约束，这不是把门拆掉。
        if is_owner_role(user.role):
            module_actions = _module_actions(module_id)
            return self._allow(
                request,
                user_id=user_id,
                org_id=org_id,
                module_id=module_id,
                action=action.value,
                role=normalize_role(user.role),
                reason=(
                    "Platform owner has global access; module binding is not a "
                    "gate for the owner role."
                ),
                allowed_actions=_sorted_actions(module_actions),
                legacy_rbac_metadata=rbac_metadata,
                c18c_org_membership_checked=True,
                c18d_module_binding_checked=True,
                c18f_isolation_applied=True,
                owner_platform_role=True,
            )

        if not self._module_bound_to_org(module_id=module_id, org_id=org_id):
            return self._deny(
                request,
                user_id=user_id,
                org_id=org_id,
                module_id=module_id,
                action=action.value,
                role=role,
                denial_code="c18f_module_not_bound_to_org",
                reason="C18E module access and C18D module binding are required.",
                legacy_rbac_metadata=rbac_metadata,
                c18c_org_membership_checked=True,
                c18d_module_binding_checked=True,
                c18f_isolation_applied=True,
                owner_platform_role=is_owner_role(user.role),
            )

        if is_super_admin_role(user.role):
            role = normalize_role(user.role)
            rbac_metadata = _legacy_metadata(role, module_id, action_text)
            module_actions = _module_actions(module_id)
            if action not in module_actions:
                return self._deny(
                    request,
                    user_id=user_id,
                    org_id=org_id,
                    module_id=module_id,
                    action=action.value,
                    role=role,
                    denial_code="c18f_module_action_denied",
                    reason="C18F module action policy denies the requested action.",
                    legacy_rbac_metadata=rbac_metadata,
                    c18c_org_membership_checked=True,
                    c18d_module_binding_checked=True,
                    c18f_isolation_applied=True,
                    owner_platform_role=False,
                )

            return self._allow(
                request,
                user_id=user_id,
                org_id=org_id,
                module_id=module_id,
                action=action.value,
                role=role,
                reason=(
                    "Super admin role inherited all module actions within "
                    "the active organization scope."
                ),
                allowed_actions=_sorted_actions(module_actions),
                legacy_rbac_metadata=rbac_metadata,
                c18c_org_membership_checked=True,
                c18d_module_binding_checked=True,
                c18f_isolation_applied=True,
                owner_platform_role=False,
            )

        role_actions = _role_actions(role)
        if action not in role_actions:
            return self._deny(
                request,
                user_id=user_id,
                org_id=org_id,
                module_id=module_id,
                action=action.value,
                role=role,
                denial_code="c18f_role_action_denied",
                reason="Resolved organization role does not allow the requested action.",
                legacy_rbac_metadata=rbac_metadata,
                c18c_org_membership_checked=True,
                c18d_module_binding_checked=True,
                c18f_isolation_applied=True,
                owner_platform_role=is_owner_role(user.role),
            )

        module_actions = _module_actions(module_id)
        if action not in module_actions:
            return self._deny(
                request,
                user_id=user_id,
                org_id=org_id,
                module_id=module_id,
                action=action.value,
                role=role,
                denial_code="c18f_module_action_denied",
                reason="C18F module action policy denies the requested action.",
                legacy_rbac_metadata=rbac_metadata,
                c18c_org_membership_checked=True,
                c18d_module_binding_checked=True,
                c18f_isolation_applied=True,
                owner_platform_role=is_owner_role(user.role),
            )

        return self._allow(
            request,
            user_id=user_id,
            org_id=org_id,
            module_id=module_id,
            action=action.value,
            role=role,
            reason=(
                "UnifiedPermissionEngine allowed access after C18H org context, "
                "C18E module access, legacy RBAC metadata, and C18F isolation."
            ),
            allowed_actions=_sorted_actions(role_actions.intersection(module_actions)),
            legacy_rbac_metadata=rbac_metadata,
            c18c_org_membership_checked=True,
            c18d_module_binding_checked=True,
            c18f_isolation_applied=True,
            owner_platform_role=is_owner_role(user.role),
        )

    def decide_permission_key(
        self,
        request: UnifiedPermissionRequest,
    ) -> UnifiedPermissionDecision:
        db = self._require_db()
        user_id = _normalize_identity(request.user_id, "[missing_user_id]")
        module_id = _normalize_module_id(request.module_id)
        action = _normalize_action(request.action)
        try:
            permission_key = validate_permission_key(request.permission_key or "")
            scope_type, scope_key = validate_scope(request.scope_type, request.scope_key)
        except ValueError as exc:
            return self._deny(
                request,
                user_id=user_id,
                org_id=request.org_id,
                module_id=module_id,
                action=action,
                denial_code="c05_invalid_permission_request",
                reason=str(exc),
            )

        user = self._get_user(user_id)
        if user is None:
            return self._deny(
                request,
                user_id=user_id,
                org_id=request.org_id,
                module_id=module_id,
                action=action,
                denial_code="c05_user_not_found",
                reason="User was not found for permission evaluation.",
                permission_key=permission_key,
                c05_assignment_checked=True,
            )
        if not user.is_active:
            return self._deny(
                request,
                user_id=user_id,
                org_id=request.org_id,
                module_id=module_id,
                action=action,
                role=user.role,
                denial_code="c05_user_inactive",
                reason="Inactive users cannot use permissions.",
                permission_key=permission_key,
                c05_assignment_checked=True,
            )

        permission = self._get_permission(permission_key)
        if permission is None or not permission.is_enabled:
            return self._deny(
                request,
                user_id=user_id,
                org_id=request.org_id,
                module_id=module_id,
                action=action,
                role=user.role,
                denial_code="c05_permission_not_enabled",
                reason="Permission registry entry is missing or disabled.",
                permission_key=permission_key,
                c05_assignment_checked=True,
            )

        rbac_metadata = _legacy_metadata(
            user.role,
            permission.module_key,
            permission.action,
        )
        role_defaults_count = len(self._list_role_defaults(normalize_role(user.role)))
        if is_owner_role(user.role):
            if self._owner_permission_allowed(
                user_id=user_id,
                permission=permission,
                scope_type=scope_type,
                scope_key=scope_key,
            ):
                return self._allow(
                    request,
                    user_id=user_id,
                    org_id=request.org_id,
                    module_id=permission.module_key,
                    action=permission.action,
                    role=user.role,
                    reason=(
                        "Owner platform role allowed by UnifiedPermissionEngine "
                        "within platform-admin or active organization scope."
                    ),
                    permission_key=permission_key,
                    permission=permission,
                    legacy_rbac_metadata=rbac_metadata,
                    c05_assignment_checked=True,
                    c05_role_defaults_count=role_defaults_count,
                    owner_platform_role=True,
                )
            return self._deny(
                request,
                user_id=user_id,
                org_id=request.org_id,
                module_id=permission.module_key,
                action=permission.action,
                role=user.role,
                denial_code="upe_owner_scope_denied",
                reason=(
                    "Owner platform role is not a global bypass and does not "
                    "grant this scope automatically."
                ),
                permission_key=permission_key,
                permission=permission,
                legacy_rbac_metadata=rbac_metadata,
                c05_assignment_checked=True,
                c05_role_defaults_count=role_defaults_count,
                owner_platform_role=True,
            )

        if is_super_admin_role(user.role):
            return self._allow(
                request,
                user_id=user_id,
                org_id=request.org_id,
                module_id=permission.module_key,
                action=permission.action,
                role=user.role,
                reason=(
                    "Super admin role inherited all enabled permissions "
                    "within organization scope."
                ),
                permission_key=permission_key,
                permission=permission,
                legacy_rbac_metadata=rbac_metadata,
                c05_assignment_checked=True,
                c05_role_defaults_count=role_defaults_count,
                owner_platform_role=False,
            )

        matched, has_other_scope = self._assignment_state(
            user_id=user.id,
            permission_key=permission_key,
            scope_type=scope_type,
            scope_key=scope_key,
        )
        if matched:
            return self._allow(
                request,
                user_id=user_id,
                org_id=request.org_id,
                module_id=permission.module_key,
                action=permission.action,
                role=user.role,
                reason="Explicit C05 assignment matched after unified evaluation.",
                permission_key=permission_key,
                permission=permission,
                legacy_rbac_metadata=rbac_metadata,
                c05_assignment_checked=True,
                c05_assignment_matched=True,
                c05_role_defaults_count=role_defaults_count,
            )
        if has_other_scope:
            return UnifiedPermissionDecision(
                user_id=user_id,
                org_id=request.org_id,
                module_id=permission.module_key,
                action=permission.action,
                role=user.role,
                scope_type=scope_type,
                scope_key=scope_key,
                decision="partial",
                denial_code="c05_scope_not_matched",
                reason="User has the permission key only in a different scope.",
                permission_key=permission_key,
                permission=permission,
                legacy_rbac_metadata=rbac_metadata,
                c05_assignment_checked=True,
                c05_role_defaults_count=role_defaults_count,
            )
        return self._deny(
            request,
            user_id=user_id,
            org_id=request.org_id,
            module_id=permission.module_key,
            action=permission.action,
            role=user.role,
            denial_code="c05_assignment_missing",
            reason="No explicit C05 assignment matched the requested permission scope.",
            permission_key=permission_key,
            permission=permission,
            legacy_rbac_metadata=rbac_metadata,
            c05_assignment_checked=True,
            c05_role_defaults_count=role_defaults_count,
        )

    def decide_platform_metadata(
        self,
        request: UnifiedPermissionRequest,
    ) -> UnifiedPermissionDecision:
        user_id = _normalize_identity(request.user_id, "[platform_principal]")
        module_id = _normalize_module_id(request.module_id)
        action = _normalize_action(request.action)
        role = normalize_role(request.role or ROLE_SYSTEM)
        metadata = _legacy_metadata(role, module_id, action)
        owner_platform_role = is_owner_role(role)
        if not metadata.role_known:
            return self._deny(
                request,
                user_id=user_id,
                org_id=request.org_id,
                module_id=module_id,
                action=action,
                role=role,
                denial_code="upe_role_metadata_missing",
                reason="Legacy RBAC supplied no role metadata for this role.",
                legacy_rbac_metadata=metadata,
                owner_platform_role=owner_platform_role,
            )
        if not metadata.module_known:
            return self._deny(
                request,
                user_id=user_id,
                org_id=request.org_id,
                module_id=module_id,
                action=action,
                role=role,
                denial_code="upe_module_metadata_missing",
                reason="Legacy RBAC supplied no module metadata for this module.",
                legacy_rbac_metadata=metadata,
                owner_platform_role=owner_platform_role,
            )
        if action not in metadata.role_actions:
            return self._deny(
                request,
                user_id=user_id,
                org_id=request.org_id,
                module_id=module_id,
                action=action,
                role=role,
                denial_code="upe_role_action_denied",
                reason="UnifiedPermissionEngine denied the action from role metadata.",
                legacy_rbac_metadata=metadata,
                owner_platform_role=owner_platform_role,
            )
        if action not in metadata.module_actions:
            return self._deny(
                request,
                user_id=user_id,
                org_id=request.org_id,
                module_id=module_id,
                action=action,
                role=role,
                denial_code="upe_module_action_denied",
                reason="UnifiedPermissionEngine denied the action from module metadata.",
                legacy_rbac_metadata=metadata,
                owner_platform_role=owner_platform_role,
            )
        return self._allow(
            request,
            user_id=user_id,
            org_id=request.org_id,
            module_id=module_id,
            action=action,
            role=role,
            reason="UnifiedPermissionEngine allowed platform-scoped metadata access.",
            legacy_rbac_metadata=metadata,
            owner_platform_role=owner_platform_role,
        )

    def _require_db(self) -> Session:
        if self.db is None:
            raise RuntimeError("UnifiedPermissionEngine requires a database session.")
        return self.db

    def _get_user(self, user_id: str) -> User | None:
        if self.resolution_cache is not None:
            return self.resolution_cache.get_user(self._require_db(), user_id)
        try:
            user_pk = int(user_id)
        except ValueError:
            return None
        return self._require_db().get(User, user_pk)

    def _get_user_org_context(
        self,
        *,
        user_id: str,
        org_id: str,
    ) -> tuple[User | None, OrgMembershipRecord | None]:
        if self.resolution_cache is not None:
            context = self.resolution_cache.get_user_org_context(
                self._require_db(),
                user_id=user_id,
                org_id=org_id,
            )
            return context.user, context.membership
        try:
            user_pk = int(user_id)
        except ValueError:
            return None, None
        row = self._require_db().execute(
            select(User, OrgMembershipRecord)
            .select_from(User)
            .outerjoin(
                OrgMembershipRecord,
                (
                    (OrgMembershipRecord.user_id == user_id)
                    & (OrgMembershipRecord.org_id == org_id)
                    & (OrgMembershipRecord.status == "active")
                ),
            )
            .where(User.id == user_pk)
            .limit(1)
        ).one_or_none()
        if row is None:
            return None, None
        user, membership = row
        return user, membership

    def _active_membership(
        self,
        *,
        user_id: str,
        org_id: str,
    ) -> OrgMembershipRecord | None:
        if self.resolution_cache is not None:
            return self.resolution_cache.get_active_membership(
                self._require_db(),
                user_id=user_id,
                org_id=org_id,
            )
        return self._require_db().scalar(
            select(OrgMembershipRecord).where(
                OrgMembershipRecord.user_id == user_id,
                OrgMembershipRecord.org_id == org_id,
                OrgMembershipRecord.status == "active",
            )
        )

    def _module_bound_to_org(self, *, module_id: str, org_id: str) -> bool:
        if self.resolution_cache is not None:
            request_bound = self.resolution_cache.module_bound_to_org_from_request(
                module_id=module_id,
                org_id=org_id,
            )
            if request_bound is not None:
                return request_bound
            binding = self.resolution_cache.get_module_binding(
                self._require_db(),
                module_id,
            )
            if binding is None:
                return False
        else:
            try:
                binding = get_module_binding(module_id, db=self._require_db())
            except ModuleBindingNotFoundError:
                return False
        if not binding.enabled:
            return False
        return (
            binding.mode == "global"
            or GLOBAL_MODULE_BOUND_ORG in binding.bound_orgs
            or org_id in binding.bound_orgs
        )

    def _owner_permission_allowed(
        self,
        *,
        user_id: str,
        permission: PermissionRegistry,
        scope_type: str,
        scope_key: str,
    ) -> bool:
        if (
            scope_type == SCOPE_GLOBAL
            and scope_key == "*"
            and permission.category in OWNER_PLATFORM_PERMISSION_CATEGORIES
        ):
            return True
        if scope_type == SCOPE_ORGANIZATION:
            membership = self._active_membership(user_id=user_id, org_id=scope_key)
            return membership is not None
        return False

    def _get_permission(self, permission_key: str) -> PermissionRegistry | None:
        if self.resolution_cache is not None:
            return self.resolution_cache.get_permission(
                self._require_db(),
                permission_key,
            )
        return get_permission_record(self._require_db(), permission_key)

    def _list_role_defaults(self, role: str) -> list[object]:
        if self.resolution_cache is not None:
            return self.resolution_cache.list_role_defaults(self._require_db(), role)
        return list_role_default_permissions(self._require_db(), role)

    def _list_enabled_user_assignments(
        self,
        user_id: int,
    ) -> list[UserPermissionAssignment]:
        if self.resolution_cache is not None:
            return self.resolution_cache.list_user_assignments(
                self._require_db(),
                user_id=user_id,
                now=_utc_now(),
            )
        return list_enabled_user_assignments(
            self._require_db(),
            user_id,
            now=_utc_now(),
        )

    def _assignment_state(
        self,
        *,
        user_id: int,
        permission_key: str,
        scope_type: str,
        scope_key: str,
    ) -> tuple[bool, bool]:
        has_other_scope = False
        for assignment in self._list_enabled_user_assignments(user_id):
            if assignment.permission_key != permission_key:
                continue
            if _assignment_matches_scope(
                assignment,
                scope_type=scope_type,
                scope_key=scope_key,
            ):
                return True, True
            has_other_scope = True
        return False, has_other_scope

    def _allow(
        self,
        request: UnifiedPermissionRequest,
        *,
        user_id: str,
        org_id: str | None,
        module_id: str,
        action: str,
        role: str | None,
        reason: str,
        permission_key: str | None = None,
        permission: PermissionRegistry | None = None,
        allowed_actions: tuple[PermissionAction, ...] = (),
        legacy_rbac_metadata: LegacyPermissionMetadata | None = None,
        c18c_org_membership_checked: bool = False,
        c18d_module_binding_checked: bool = False,
        c05_assignment_checked: bool = False,
        c05_assignment_matched: bool = False,
        c05_role_defaults_count: int = 0,
        c18f_isolation_applied: bool = False,
        owner_platform_role: bool = False,
    ) -> UnifiedPermissionDecision:
        return UnifiedPermissionDecision(
            user_id=user_id,
            org_id=org_id,
            module_id=module_id,
            action=action,
            role=role,
            scope_type=request.scope_type,
            scope_key=request.scope_key,
            decision="allow",
            denial_code=None,
            reason=reason,
            permission_key=permission_key,
            permission=permission,
            allowed_actions=allowed_actions,
            legacy_rbac_metadata=legacy_rbac_metadata,
            c18c_org_membership_checked=c18c_org_membership_checked,
            c18d_module_binding_checked=c18d_module_binding_checked,
            c05_assignment_checked=c05_assignment_checked,
            c05_assignment_matched=c05_assignment_matched,
            c05_role_defaults_count=c05_role_defaults_count,
            c18f_isolation_applied=c18f_isolation_applied,
            owner_platform_role=owner_platform_role,
        )

    def _deny(
        self,
        request: UnifiedPermissionRequest,
        *,
        user_id: str,
        org_id: str | None,
        module_id: str,
        action: str,
        denial_code: str,
        reason: str,
        role: str | None = None,
        permission_key: str | None = None,
        permission: PermissionRegistry | None = None,
        legacy_rbac_metadata: LegacyPermissionMetadata | None = None,
        c18c_org_membership_checked: bool = False,
        c18d_module_binding_checked: bool = False,
        c05_assignment_checked: bool = False,
        c05_assignment_matched: bool = False,
        c05_role_defaults_count: int = 0,
        c18f_isolation_applied: bool = False,
        owner_platform_role: bool = False,
    ) -> UnifiedPermissionDecision:
        return UnifiedPermissionDecision(
            user_id=user_id,
            org_id=org_id,
            module_id=module_id,
            action=action,
            role=role,
            scope_type=request.scope_type,
            scope_key=request.scope_key,
            decision="deny",
            denial_code=denial_code,
            reason=reason,
            permission_key=permission_key,
            permission=permission,
            legacy_rbac_metadata=legacy_rbac_metadata,
            c18c_org_membership_checked=c18c_org_membership_checked,
            c18d_module_binding_checked=c18d_module_binding_checked,
            c05_assignment_checked=c05_assignment_checked,
            c05_assignment_matched=c05_assignment_matched,
            c05_role_defaults_count=c05_role_defaults_count,
            c18f_isolation_applied=c18f_isolation_applied,
            owner_platform_role=owner_platform_role,
        )


def check_internal_permission(
    module: str,
    action: str = ACTION_INTERNAL,
) -> UnifiedPermissionDecision:
    request = UnifiedPermissionRequest(
        user_id=None,
        org_id=None,
        module_id=module,
        action=action,
        role=ROLE_SYSTEM,
        scope_type=SCOPE_GLOBAL,
        scope_key="*",
        source="internal_rbac_wrapper",
    )
    return UnifiedPermissionEngine().decide_platform_metadata(request)
