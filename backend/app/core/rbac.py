from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from .roles import is_owner_role, normalize_role

ACTION_ADMIN = "admin"
ACTION_EXECUTE = "execute"
ACTION_INTERNAL = "internal"
ACTION_READ = "read"
ACTION_WRITE = "write"

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
ROLE_SYSTEM = "system"

ROLE_PERMISSIONS = MappingProxyType(
    {
        ROLE_OWNER: frozenset(("*",)),
        ROLE_ADMIN: frozenset(
            (ACTION_READ, ACTION_WRITE, ACTION_EXECUTE, ACTION_ADMIN)
        ),
        ROLE_OPERATOR: frozenset((ACTION_READ, ACTION_WRITE)),
        ROLE_VIEWER: frozenset((ACTION_READ,)),
        ROLE_SYSTEM: frozenset((ACTION_INTERNAL,)),
    }
)

LEGACY_ROLE_ALIASES = MappingProxyType(
    {
        "super_admin": ROLE_ADMIN,
        "module_admin": ROLE_ADMIN,
        "reviewer": ROLE_OPERATOR,
        "bot_agent": ROLE_SYSTEM,
    }
)

MODULE_PERMISSIONS = MappingProxyType(
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


class RbacUser(Protocol):
    role: str


@dataclass(frozen=True)
class RbacRequirement:
    module: str
    action: str


def normalize_rbac_role(role: str) -> str:
    normalized = normalize_role(role)
    return LEGACY_ROLE_ALIASES.get(normalized, normalized)


def role_allows_action(role: str, action: str) -> bool:
    normalized = normalize_rbac_role(role)
    if is_owner_role(normalized):
        return True
    allowed_actions = ROLE_PERMISSIONS.get(normalized, frozenset())
    return action in allowed_actions


def module_allows_action(module: str, action: str) -> bool:
    allowed_actions = MODULE_PERMISSIONS.get(module)
    if allowed_actions is None:
        return False
    return action in allowed_actions


def check_permission(user: RbacUser, module: str, action: str) -> bool:
    role = normalize_rbac_role(user.role)

    if is_owner_role(role):
        return True

    if not role_allows_action(role, action):
        return False

    if not module_allows_action(module, action):
        return False

    return True


def check_internal_permission(module: str, action: str = ACTION_INTERNAL) -> bool:
    class SystemPrincipal:
        role = ROLE_SYSTEM

    return check_permission(SystemPrincipal(), module, action)
