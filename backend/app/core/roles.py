from types import MappingProxyType
from typing import Any

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"
ROLE_MODULE_ADMIN = "module_admin"
ROLE_OPERATOR = "operator"
ROLE_REVIEWER = "reviewer"
ROLE_VIEWER = "viewer"
ROLE_SYSTEM = "system"
ROLE_BOT_AGENT = "bot_agent"

ROLE_ALIASES = MappingProxyType(
    {
        "super admin": ROLE_SUPER_ADMIN,
        "super-admin": ROLE_SUPER_ADMIN,
        "superadmin": ROLE_SUPER_ADMIN,
        "org_admin": ROLE_SUPER_ADMIN,
        "org admin": ROLE_SUPER_ADMIN,
        "organization_admin": ROLE_SUPER_ADMIN,
        "organization admin": ROLE_SUPER_ADMIN,
    }
)

STANDARD_ROLES = (
    ROLE_OWNER,
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_MODULE_ADMIN,
    ROLE_OPERATOR,
    ROLE_REVIEWER,
    ROLE_VIEWER,
    ROLE_SYSTEM,
    ROLE_BOT_AGENT,
)

ASSIGNABLE_USER_ROLES = (
    ROLE_ADMIN,
    ROLE_VIEWER,
    ROLE_OPERATOR,
    ROLE_REVIEWER,
)

UNASSIGNABLE_USER_ROLES = (
    ROLE_OWNER,
    ROLE_SUPER_ADMIN,
    ROLE_MODULE_ADMIN,
    ROLE_SYSTEM,
    ROLE_BOT_AGENT,
)

ROLE_DISPLAY_METADATA = MappingProxyType(
    {
        ROLE_OWNER: {
            "label": "Owner",
            "description": "Bootstrap/system owner account.",
            "human_or_agent": "human",
            "c04_status": "bootstrap_only",
        },
        ROLE_ADMIN: {
            "label": "Admin",
            "description": "Module-level RBAC administrator.",
            "human_or_agent": "human",
            "c04_status": "assignable_admin_role",
        },
        ROLE_SUPER_ADMIN: {
            "label": "Super Admin",
            "description": "Legacy admin role; mapped to admin by RBAC.",
            "human_or_agent": "human",
            "c04_status": "legacy_admin_alias",
        },
        ROLE_MODULE_ADMIN: {
            "label": "Module Admin",
            "description": "Legacy module admin role; mapped to admin by RBAC.",
            "human_or_agent": "human",
            "c04_status": "legacy_admin_alias",
        },
        ROLE_OPERATOR: {
            "label": "Operator",
            "description": "Assignable managed user role.",
            "human_or_agent": "human",
            "c04_status": "assignable_user_role",
        },
        ROLE_REVIEWER: {
            "label": "Reviewer",
            "description": "Assignable managed user role.",
            "human_or_agent": "human",
            "c04_status": "assignable_user_role",
        },
        ROLE_VIEWER: {
            "label": "Viewer",
            "description": "Assignable managed user role.",
            "human_or_agent": "human",
            "c04_status": "assignable_user_role",
        },
        ROLE_SYSTEM: {
            "label": "System",
            "description": "Internal system principal for signed callbacks and service boundaries.",
            "human_or_agent": "agent",
            "c04_status": "internal_only",
        },
        ROLE_BOT_AGENT: {
            "label": "Bot Agent",
            "description": "Legacy agent role; mapped to system by RBAC.",
            "human_or_agent": "agent",
            "c04_status": "legacy_system_alias",
        },
    }
)


def normalize_role(role: str | None) -> str:
    if role is None:
        return ""
    normalized = role.strip().lower().replace("-", "_")
    normalized = "_".join(normalized.split())
    return ROLE_ALIASES.get(normalized, normalized)


def is_super_admin_role(role: str | None) -> bool:
    return normalize_role(role) == ROLE_SUPER_ADMIN


def is_org_admin_like_role(role: str | None) -> bool:
    return normalize_role(role) in {ROLE_SUPER_ADMIN, ROLE_ADMIN}


def role_filter_values(role: str | None) -> tuple[str, ...]:
    normalized = normalize_role(role)
    if normalized == ROLE_SUPER_ADMIN:
        return (
            ROLE_SUPER_ADMIN,
            "super admin",
            "super-admin",
            "superadmin",
            "org_admin",
            "organization_admin",
        )
    return (normalized,) if normalized else ()


def is_standard_role(role: str) -> bool:
    return normalize_role(role) in STANDARD_ROLES


def is_owner_role(role: str) -> bool:
    return normalize_role(role) == ROLE_OWNER


def is_assignable_user_role(role: str) -> bool:
    return normalize_role(role) in ASSIGNABLE_USER_ROLES


def validate_assignable_user_role(role: str) -> str:
    normalized = normalize_role(role)
    if normalized not in ASSIGNABLE_USER_ROLES:
        allowed = ", ".join(ASSIGNABLE_USER_ROLES)
        raise ValueError(f"Role must be one of: {allowed}.")
    return normalized


def get_role_display_metadata(role: str) -> dict[str, Any]:
    normalized = normalize_role(role)
    if normalized not in ROLE_DISPLAY_METADATA:
        raise ValueError("Unknown role.")

    metadata = dict(ROLE_DISPLAY_METADATA[normalized])
    metadata["name"] = normalized
    metadata["assignable"] = is_assignable_user_role(normalized)
    return metadata


def list_standard_role_metadata() -> list[dict[str, Any]]:
    return [get_role_display_metadata(role) for role in STANDARD_ROLES]


def list_assignable_user_role_metadata() -> list[dict[str, Any]]:
    return [get_role_display_metadata(role) for role in ASSIGNABLE_USER_ROLES]
