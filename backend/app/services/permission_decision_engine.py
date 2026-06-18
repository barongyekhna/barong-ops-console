from __future__ import annotations

from typing import Hashable

from fastapi import Request
from sqlalchemy.orm import Session

from .permission_resolution_cache import (
    PermissionResolutionCache,
    get_permission_request_cache,
)
from .unified_permission_engine import (
    UnifiedPermissionDecision,
    UnifiedPermissionEngine,
    UnifiedPermissionRequest,
)


def _text(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = getattr(value, "value")
    return str(value).strip() or None


def _decision_key(request: UnifiedPermissionRequest, mode: str) -> Hashable:
    return (
        mode,
        _text(request.user_id),
        _text(request.org_id),
        _text(request.module_id),
        (_text(request.action) or "read").lower(),
        _text(request.role),
        _text(request.scope_type),
        _text(request.scope_key),
        _text(request.permission_key),
    )


class PermissionDecisionEngine:
    def __init__(
        self,
        db: Session | None = None,
        *,
        request: Request | None = None,
    ) -> None:
        self.db = db
        self.request = request
        self.request_cache = get_permission_request_cache(request)
        self.resolution_cache = PermissionResolutionCache(request=request)

    def decide(
        self,
        permission_request: UnifiedPermissionRequest,
    ) -> UnifiedPermissionDecision:
        return self._decide(permission_request, mode="auto")

    def decide_org_module(
        self,
        permission_request: UnifiedPermissionRequest,
    ) -> UnifiedPermissionDecision:
        return self._decide(permission_request, mode="org_module")

    def decide_permission_key(
        self,
        permission_request: UnifiedPermissionRequest,
    ) -> UnifiedPermissionDecision:
        return self._decide(permission_request, mode="permission_key")

    def decide_platform_metadata(
        self,
        permission_request: UnifiedPermissionRequest,
    ) -> UnifiedPermissionDecision:
        return self._decide(permission_request, mode="platform_metadata")

    def _decide(
        self,
        permission_request: UnifiedPermissionRequest,
        *,
        mode: str,
    ) -> UnifiedPermissionDecision:
        key = _decision_key(permission_request, mode)
        if self.request_cache is not None and key in self.request_cache.decisions:
            self.request_cache.decision_hits += 1
            return self.request_cache.decisions[key]

        if self.request_cache is not None:
            self.request_cache.decision_evaluations += 1

        engine = UnifiedPermissionEngine(
            self.db,
            resolution_cache=self.resolution_cache,
        )
        if mode == "org_module":
            decision = engine.decide_org_module(permission_request)
        elif mode == "permission_key":
            decision = engine.decide_permission_key(permission_request)
        elif mode == "platform_metadata":
            decision = engine.decide_platform_metadata(permission_request)
        else:
            decision = engine.decide(permission_request)

        if self.request_cache is not None:
            self.request_cache.decisions[key] = decision
        return decision
