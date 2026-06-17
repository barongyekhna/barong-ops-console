from dataclasses import dataclass
from types import MappingProxyType

from .roles import normalize_role

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
        ROLE_OWNER: frozenset(
            (ACTION_READ, ACTION_WRITE, ACTION_EXECUTE, ACTION_ADMIN)
        ),
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

@dataclass(frozen=True)
class RoleMetadata:
    role: str
    normalized_role: str
    legacy_alias_of: str | None
    role_actions: frozenset[str]
    role_known: bool


def normalize_rbac_role(role: str) -> str:
    return normalize_role(role)


def get_role_metadata(role: str) -> RoleMetadata:
    normalized = normalize_rbac_role(role)
    role_actions = ROLE_PERMISSIONS.get(normalized, frozenset())
    return RoleMetadata(
        role=role,
        normalized_role=normalized,
        legacy_alias_of=LEGACY_ROLE_ALIASES.get(normalized),
        role_actions=role_actions,
        role_known=normalized in ROLE_PERMISSIONS,
    )
