"""Access-control skeleton for the disabled K Product Knowledge module."""

from typing import Any

from fastapi import HTTPException, status

from ....core.roles import is_owner_role
from .constants import ACTION_PERMISSION_KEYS, PERMISSION_KEYS
from .errors import KProductKnowledgeDisabledError
from .feature_flags import is_k_product_knowledge_enabled


def require_k_product_knowledge_access(
    current_user: Any,
    action: str,
) -> Any:
    """Require dormant K access without touching core permission registry.

    Access is denied while the local feature flag returns False. Once a future
    task wires C13/C07/C08 permission registration, the fallback branch may
    allow owner or K-prefixed permissions only.
    """

    if not is_k_product_knowledge_enabled():
        raise KProductKnowledgeDisabledError().to_http_exception()

    permission_key = _permission_key_for_action(action)
    if is_owner_role(str(getattr(current_user, "role", ""))):
        return current_user

    if _has_future_k_prefixed_permission(current_user, permission_key):
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Missing permission: {permission_key}",
    )


def _permission_key_for_action(action: str) -> str:
    permission_key = ACTION_PERMISSION_KEYS.get(action, action)
    if permission_key not in PERMISSION_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid K Product Knowledge action.",
        )
    return permission_key


def _has_future_k_prefixed_permission(
    current_user: Any,
    permission_key: str,
) -> bool:
    del current_user
    return permission_key.startswith("k.product_knowledge.") and False
