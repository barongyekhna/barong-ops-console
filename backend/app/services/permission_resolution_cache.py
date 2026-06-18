from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable, Hashable

from fastapi import Request
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..models.org_membership import OrgMembershipRecord
from ..models.permission import (
    PermissionRegistry,
    RoleDefaultPermission,
    UserPermissionAssignment,
)
from ..models.user import User
from ..repositories.permissions import (
    get_permission as get_permission_record,
    list_enabled_user_assignments,
    list_role_default_permissions,
)
from ..schemas.module_binding import ModuleBinding
from .request_session_cache import REQUEST_AUTH_SESSION_ATTR

PERMISSION_CACHE_TTL_SECONDS = 45.0
PERMISSION_CACHE_MAX_ENTRIES = 4096
REQUEST_PERMISSION_CACHE_ATTR = "permission_cache"


@dataclass(frozen=True)
class CachedUser:
    id: int
    role: str
    is_active: bool


@dataclass(frozen=True)
class CachedMembership:
    membership_id: str
    user_id: str
    org_id: str
    role: str
    status: str


@dataclass(frozen=True)
class CachedPermissionRegistry:
    permission_key: str
    module_key: str
    category: str
    action: str
    label: str
    description: str | None
    risk_level: str
    menu_policy: str
    is_system: bool
    is_enabled: bool


@dataclass(frozen=True)
class CachedUserPermissionAssignment:
    user_id: int
    permission_key: str
    scope_type: str
    scope_key: str
    is_enabled: bool
    expires_at: Any


@dataclass(frozen=True)
class CachedRoleDefaultPermission:
    role: str
    permission_key: str
    scope_type: str
    scope_key: str
    is_enabled: bool


@dataclass(frozen=True)
class CachedUserOrgContext:
    user: CachedUser | None
    membership: CachedMembership | None


@dataclass
class PermissionRequestCache:
    decisions: dict[Hashable, Any] = field(default_factory=dict)
    materials: dict[Hashable, Any] = field(default_factory=dict)
    decision_evaluations: int = 0
    decision_hits: int = 0
    request_material_hits: int = 0
    ttl_material_hits: int = 0
    material_loads: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "decision_evaluations": self.decision_evaluations,
            "decision_hits": self.decision_hits,
            "request_material_hits": self.request_material_hits,
            "ttl_material_hits": self.ttl_material_hits,
            "material_loads": self.material_loads,
        }


@dataclass(frozen=True)
class _CachedValue:
    value: Any
    expires_at: float


class _ShortTtlCache:
    def __init__(self) -> None:
        self._values: dict[Hashable, _CachedValue] = {}
        self._lock = Lock()

    def get_or_load(
        self,
        key: Hashable,
        *,
        ttl_seconds: float,
        loader: Callable[[], Any],
    ) -> tuple[Any, bool]:
        now = time.monotonic()
        with self._lock:
            cached = self._values.get(key)
            if cached is not None and cached.expires_at > now:
                return cached.value, True
            if cached is not None:
                self._values.pop(key, None)

        value = loader()
        with self._lock:
            if len(self._values) >= PERMISSION_CACHE_MAX_ENTRIES:
                self._values.clear()
            self._values[key] = _CachedValue(
                value=value,
                expires_at=now + ttl_seconds,
            )
        return value, False

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


_TTL_CACHE = _ShortTtlCache()
_MISSING = object()


def clear_permission_ttl_cache() -> None:
    _TTL_CACHE.clear()


def get_permission_request_cache(
    request: Request | None,
) -> PermissionRequestCache | None:
    if request is None:
        return None
    cache = getattr(request.state, REQUEST_PERMISSION_CACHE_ATTR, None)
    if isinstance(cache, PermissionRequestCache):
        return cache
    cache = PermissionRequestCache()
    request.state.permission_cache = cache
    return cache


def permission_request_cache_snapshot(request: Request) -> dict[str, int]:
    cache = get_permission_request_cache(request)
    if cache is None:
        return {}
    return cache.snapshot()


def _db_namespace(db: Session) -> str:
    bind = db.get_bind()
    url = getattr(bind, "url", None)
    if url is None:
        rendered = repr(bind)
    else:
        rendered = url.render_as_string(hide_password=True)
    pytest_scope = os.environ.get("PYTEST_CURRENT_TEST", "")
    return f"{rendered}|{pytest_scope}"


def _user_snapshot(user: User) -> CachedUser:
    return CachedUser(
        id=user.id,
        role=user.role,
        is_active=user.is_active,
    )


def _membership_snapshot(membership: OrgMembershipRecord) -> CachedMembership:
    return CachedMembership(
        membership_id=membership.membership_id,
        user_id=membership.user_id,
        org_id=membership.org_id,
        role=membership.role,
        status=membership.status,
    )


def _permission_snapshot(permission: PermissionRegistry) -> CachedPermissionRegistry:
    return CachedPermissionRegistry(
        permission_key=permission.permission_key,
        module_key=permission.module_key,
        category=permission.category,
        action=permission.action,
        label=permission.label,
        description=permission.description,
        risk_level=permission.risk_level,
        menu_policy=permission.menu_policy,
        is_system=permission.is_system,
        is_enabled=permission.is_enabled,
    )


def _assignment_snapshot(
    assignment: UserPermissionAssignment,
) -> CachedUserPermissionAssignment:
    return CachedUserPermissionAssignment(
        user_id=assignment.user_id,
        permission_key=assignment.permission_key,
        scope_type=assignment.scope_type,
        scope_key=assignment.scope_key,
        is_enabled=assignment.is_enabled,
        expires_at=assignment.expires_at,
    )


def _role_default_snapshot(
    permission: RoleDefaultPermission,
) -> CachedRoleDefaultPermission:
    return CachedRoleDefaultPermission(
        role=permission.role,
        permission_key=permission.permission_key,
        scope_type=permission.scope_type,
        scope_key=permission.scope_key,
        is_enabled=permission.is_enabled,
    )


class PermissionResolutionCache:
    def __init__(self, *, request: Request | None = None) -> None:
        self.request = request
        self.request_cache = get_permission_request_cache(request)

    def _material(
        self,
        db: Session,
        namespace: str,
        key: Hashable,
        loader: Callable[[], Any],
    ) -> Any:
        request_key = (namespace, key)
        if (
            self.request_cache is not None
            and request_key in self.request_cache.materials
        ):
            self.request_cache.request_material_hits += 1
            return self.request_cache.materials[request_key]

        ttl_key = (_db_namespace(db), namespace, key)
        value, ttl_hit = _TTL_CACHE.get_or_load(
            ttl_key,
            ttl_seconds=PERMISSION_CACHE_TTL_SECONDS,
            loader=loader,
        )
        if self.request_cache is not None:
            if ttl_hit:
                self.request_cache.ttl_material_hits += 1
            else:
                self.request_cache.material_loads += 1
            self.request_cache.materials[request_key] = value
        return value

    def _material_from_request(self, namespace: str, key: Hashable) -> Any:
        if self.request_cache is None:
            return _MISSING
        request_key = (namespace, key)
        if request_key not in self.request_cache.materials:
            return _MISSING
        self.request_cache.request_material_hits += 1
        return self.request_cache.materials[request_key]

    def _store_request_material(
        self,
        namespace: str,
        key: Hashable,
        value: Any,
    ) -> None:
        if self.request_cache is None:
            return
        self.request_cache.materials[(namespace, key)] = value

    def _current_session_user(self, user_id: str) -> CachedUser | None:
        if self.request is None:
            return None
        current_session = getattr(self.request.state, REQUEST_AUTH_SESSION_ATTR, None)
        user = getattr(current_session, "user", None)
        if user is None or str(getattr(user, "id", "")) != user_id:
            return None
        return CachedUser(
            id=user.id,
            role=user.role,
            is_active=user.is_active,
        )

    def _org_context_membership(
        self,
        *,
        user_id: str,
        org_id: str,
    ) -> CachedMembership | None:
        if self.request is None:
            return None
        org_context = getattr(self.request.state, "org_context", None)
        if org_context is None:
            return None
        if (
            str(getattr(org_context, "user_id", "")) != user_id
            or getattr(org_context, "org_id", None) != org_id
        ):
            return None
        return CachedMembership(
            membership_id=f"request:{user_id}:{org_id}",
            user_id=user_id,
            org_id=org_id,
            role=getattr(org_context, "role", "member"),
            status="active",
        )

    def get_user(self, db: Session, user_id: str) -> CachedUser | None:
        cached = self._material_from_request("user_permissions", user_id)
        if cached is not _MISSING:
            return cached

        request_user = self._current_session_user(user_id)
        if request_user is not None:
            self._store_request_material("user_permissions", user_id, request_user)
            return request_user

        try:
            user_pk = int(user_id)
        except ValueError:
            return None

        def load() -> CachedUser | None:
            user = db.get(User, user_pk)
            return _user_snapshot(user) if user is not None else None

        return self._material(db, "user_permissions", user_id, load)

    def get_user_org_context(
        self,
        db: Session,
        *,
        user_id: str,
        org_id: str,
    ) -> CachedUserOrgContext:
        request_key = f"{user_id}:{org_id}"
        cached = self._material_from_request("org_permissions", request_key)
        if cached is not _MISSING:
            return cached

        request_user = self._current_session_user(user_id)
        request_membership = self._org_context_membership(
            user_id=user_id,
            org_id=org_id,
        )
        if request_user is not None and request_membership is not None:
            context = CachedUserOrgContext(
                user=request_user,
                membership=request_membership,
            )
            self._store_request_material("org_permissions", request_key, context)
            self._store_request_material("user_permissions", user_id, request_user)
            self._store_request_material(
                "org_membership",
                request_key,
                request_membership,
            )
            return context

        try:
            user_pk = int(user_id)
        except ValueError:
            return CachedUserOrgContext(user=None, membership=None)

        def load() -> CachedUserOrgContext:
            row = db.execute(
                select(User, OrgMembershipRecord)
                .select_from(User)
                .outerjoin(
                    OrgMembershipRecord,
                    and_(
                        OrgMembershipRecord.user_id == user_id,
                        OrgMembershipRecord.org_id == org_id,
                        OrgMembershipRecord.status == "active",
                    ),
                )
                .where(User.id == user_pk)
                .limit(1)
            ).one_or_none()
            if row is None:
                return CachedUserOrgContext(user=None, membership=None)
            user, membership = row
            return CachedUserOrgContext(
                user=_user_snapshot(user),
                membership=(
                    _membership_snapshot(membership)
                    if membership is not None
                    else None
                ),
            )

        context = self._material(db, "org_permissions", request_key, load)
        if context.user is not None:
            self._store_request_material("user_permissions", user_id, context.user)
        self._store_request_material("org_membership", request_key, context.membership)
        return context

    def get_active_membership(
        self,
        db: Session,
        *,
        user_id: str,
        org_id: str,
    ) -> CachedMembership | None:
        request_key = f"{user_id}:{org_id}"
        cached = self._material_from_request("org_membership", request_key)
        if cached is not _MISSING:
            return cached

        request_membership = self._org_context_membership(
            user_id=user_id,
            org_id=org_id,
        )
        if request_membership is not None:
            self._store_request_material(
                "org_membership",
                request_key,
                request_membership,
            )
            return request_membership

        def load() -> CachedMembership | None:
            membership = db.scalar(
                select(OrgMembershipRecord).where(
                    OrgMembershipRecord.user_id == user_id,
                    OrgMembershipRecord.org_id == org_id,
                    OrgMembershipRecord.status == "active",
                )
            )
            return _membership_snapshot(membership) if membership is not None else None

        return self._material(db, "org_membership", request_key, load)

    def get_permission(
        self,
        db: Session,
        permission_key: str,
    ) -> CachedPermissionRegistry | None:
        def load() -> CachedPermissionRegistry | None:
            permission = get_permission_record(db, permission_key)
            return _permission_snapshot(permission) if permission is not None else None

        return self._material(db, "module_permissions", permission_key, load)

    def list_user_assignments(
        self,
        db: Session,
        *,
        user_id: int,
        now: Any,
    ) -> list[CachedUserPermissionAssignment]:
        def load() -> list[CachedUserPermissionAssignment]:
            return [
                _assignment_snapshot(assignment)
                for assignment in list_enabled_user_assignments(
                    db,
                    user_id,
                    now=time_aware_now(),
                )
            ]

        assignments = self._material(
            db,
            "user_permissions",
            f"assignments:{user_id}",
            load,
        )
        return [
            assignment
            for assignment in assignments
            if _not_expired(assignment.expires_at, now=now)
        ]

    def list_role_defaults(
        self,
        db: Session,
        role: str,
    ) -> list[CachedRoleDefaultPermission]:
        def load() -> list[CachedRoleDefaultPermission]:
            return [
                _role_default_snapshot(permission)
                for permission in list_role_default_permissions(db, role)
            ]

        return self._material(db, "user_permissions", f"role:{role}", load)

    def get_module_binding(
        self,
        db: Session,
        module_id: str,
    ) -> ModuleBinding | None:
        def load() -> ModuleBinding | None:
            from .module_binding_service import (
                ModuleBindingNotFoundError,
                get_module_binding as load_module_binding,
            )

            try:
                return load_module_binding(module_id, db=db)
            except ModuleBindingNotFoundError:
                return None

        return self._material(db, "module_permissions", f"binding:{module_id}", load)

    def module_bound_to_org_from_request(
        self,
        *,
        module_id: str,
        org_id: str,
    ) -> bool | None:
        if self.request is None:
            return None
        org_context = getattr(self.request.state, "org_context", None)
        if org_context is None or getattr(org_context, "org_id", None) != org_id:
            return None
        module_scope = getattr(org_context, "module_scope", None)
        if module_scope is None:
            return None
        return module_id in set(module_scope)


def time_aware_now() -> datetime:
    return datetime.now(timezone.utc)


def _not_expired(value: Any, *, now: Any) -> bool:
    if value is None:
        return True
    expires_at = value
    current_time = now
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if isinstance(current_time, datetime) and current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    return expires_at > current_time
