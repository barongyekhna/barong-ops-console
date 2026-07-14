import re
from types import MappingProxyType
from typing import TypedDict

RISK_LEVEL_LOW = "low"
RISK_LEVEL_MEDIUM = "medium"
RISK_LEVEL_HIGH = "high"
RISK_LEVEL_CRITICAL = "critical"

MENU_POLICY_SHOW_LOCKED = "show_locked"
MENU_POLICY_HIDE_WHEN_DENIED = "hide_when_denied"

SCOPE_GLOBAL = "global"
SCOPE_COMPANY = "company"
SCOPE_FACTORY = "factory"
SCOPE_DEPARTMENT = "department"
SCOPE_ORGANIZATION = "organization"
SCOPE_MODULE = "module"
RETIRED_PERMISSION_PREFIXES = ("jobs.", "workflows.", "c19.")

PERMISSION_KEY_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
)

ALLOWED_RISK_LEVELS = (
    RISK_LEVEL_LOW,
    RISK_LEVEL_MEDIUM,
    RISK_LEVEL_HIGH,
    RISK_LEVEL_CRITICAL,
)
ALLOWED_MENU_POLICIES = (
    MENU_POLICY_SHOW_LOCKED,
    MENU_POLICY_HIDE_WHEN_DENIED,
)
ALLOWED_SCOPE_TYPES = (
    SCOPE_GLOBAL,
    SCOPE_COMPANY,
    SCOPE_FACTORY,
    SCOPE_DEPARTMENT,
    SCOPE_ORGANIZATION,
    SCOPE_MODULE,
)


class PermissionDefinition(TypedDict):
    permission_key: str
    module_key: str
    category: str
    action: str
    label: str
    description: str
    risk_level: str
    menu_policy: str


BASE_PERMISSION_REGISTRY_SEED: tuple[PermissionDefinition, ...] = (
    {
        "permission_key": "users.read",
        "module_key": "users",
        "category": "admin",
        "action": "read",
        "label": "Read users",
        "description": "View internal user accounts and basic user metadata.",
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
    {
        "permission_key": "users.manage",
        "module_key": "users",
        "category": "admin",
        "action": "manage",
        "label": "Manage users",
        "description": "Create, update, disable, enable, and reset internal users.",
        "risk_level": RISK_LEVEL_HIGH,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
    {
        "permission_key": "roles.read",
        "module_key": "roles",
        "category": "admin",
        "action": "read",
        "label": "Read roles",
        "description": "View the system role catalog and assignable role metadata.",
        "risk_level": RISK_LEVEL_LOW,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
    {
        "permission_key": "permissions.read",
        "module_key": "permissions",
        "category": "admin",
        "action": "read",
        "label": "Read permissions",
        "description": "View permission registry entries and assignment state.",
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
    {
        "permission_key": "permissions.manage",
        "module_key": "permissions",
        "category": "admin",
        "action": "manage",
        "label": "Manage permissions",
        "description": "Grant, disable, or change scoped user permission assignments.",
        "risk_level": RISK_LEVEL_CRITICAL,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
    {
        "permission_key": "reviews.read",
        "module_key": "reviews",
        "category": "business",
        "action": "read",
        "label": "Read reviews",
        "description": "View review queues and safe review metadata.",
        "risk_level": RISK_LEVEL_LOW,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "reviews.approve",
        "module_key": "reviews",
        "category": "business",
        "action": "approve",
        "label": "Approve reviews",
        "description": "Approve assigned review items within an authorized scope.",
        "risk_level": RISK_LEVEL_HIGH,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "artifacts.read",
        "module_key": "artifacts",
        "category": "business",
        "action": "read",
        "label": "Read artifacts",
        "description": "View artifact metadata and safe artifact records.",
        "risk_level": RISK_LEVEL_LOW,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "products.read",
        "module_key": "k.product_knowledge",
        "category": "business",
        "action": "read",
        "label": "Read products",
        "description": "View product knowledge records through the products workspace.",
        "risk_level": RISK_LEVEL_LOW,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "k.product_knowledge.read",
        "module_key": "k.product_knowledge",
        "category": "business",
        "action": "read",
        "label": "Read product knowledge",
        "description": "View K-series product knowledge records.",
        "risk_level": RISK_LEVEL_LOW,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "k.product_knowledge.create",
        "module_key": "k.product_knowledge",
        "category": "business",
        "action": "create",
        "label": "Create product knowledge",
        "description": "Create K-series product knowledge records.",
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "k.product_knowledge.update",
        "module_key": "k.product_knowledge",
        "category": "business",
        "action": "update",
        "label": "Update product knowledge",
        "description": "Edit K-series product knowledge records and enrichment outputs.",
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "k.product_knowledge.archive",
        "module_key": "k.product_knowledge",
        "category": "business",
        "action": "archive",
        "label": "Archive product knowledge",
        "description": "Archive K-series product knowledge records.",
        "risk_level": RISK_LEVEL_HIGH,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "k.product_knowledge.attributes.manage",
        "module_key": "k.product_knowledge",
        "category": "business",
        "action": "manage",
        "label": "Manage product attributes",
        "description": "Create or update K-series product attribute records.",
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "k.product_knowledge.keywords.manage",
        "module_key": "k.product_knowledge",
        "category": "business",
        "action": "manage",
        "label": "Manage product keywords",
        "description": "Create, update, approve, or archive K-series keyword records.",
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "k.product_knowledge.risk_terms.manage",
        "module_key": "k.product_knowledge",
        "category": "business",
        "action": "manage",
        "label": "Manage product risk terms",
        "description": "Create, update, resolve, or ignore K-series risk terms.",
        "risk_level": RISK_LEVEL_HIGH,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "i.image_system.read",
        "module_key": "i.image_system",
        "category": "business",
        "action": "read",
        "label": "Read I image system metadata",
        "description": "View the independent I-series image system boundary metadata.",
        "risk_level": RISK_LEVEL_LOW,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "i.image_system.execute",
        "module_key": "i.image_system",
        "category": "business",
        "action": "execute",
        "label": "Generate and edit I-series images",
        "description": "Run prompt enhancement, image generation, and image editing.",
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "i.image_system.manage",
        "module_key": "i.image_system",
        "category": "business",
        "action": "manage",
        "label": "Manage I-series media library",
        "description": "Save, download, and delete I-series media library images.",
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "p.upload.read",
        "module_key": "p.upload",
        "category": "business",
        "action": "read",
        "label": "Read P-series upload pipeline",
        "description": "View the P-series upload ledger and product upload board.",
        "risk_level": RISK_LEVEL_LOW,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "p.upload.execute",
        "module_key": "p.upload",
        "category": "business",
        "action": "execute",
        "label": "Dispatch P-series uploads",
        "description": "Trigger single or batch product uploads to the storefront through P-series.",
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "f.enrichment.read",
        "module_key": "f.enrichment",
        "category": "business",
        "action": "read",
        "label": "Read category enrichment",
        "description": "View F-series enrichment runs, keywords, and candidates.",
        "risk_level": RISK_LEVEL_LOW,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "f.enrichment.execute",
        "module_key": "f.enrichment",
        "category": "business",
        "action": "execute",
        "label": "Execute enrichment runs",
        "description": (
            "Start keyword harvest and 1688 sourcing runs over selected "
            "Google taxonomy branches (consumes daily provider quota)."
        ),
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "f.enrichment.review",
        "module_key": "f.enrichment",
        "category": "business",
        "action": "manage",
        "label": "Review enrichment candidates",
        "description": (
            "Create and review sourcing candidates (approve / reject) and "
            "import approved candidates into K."
        ),
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_SHOW_LOCKED,
    },
    {
        "permission_key": "operation_logs.read",
        "module_key": "operation_logs",
        "category": "system",
        "action": "read",
        "label": "Read operation logs",
        "description": "View audit logs and operation history.",
        "risk_level": RISK_LEVEL_HIGH,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
    {
        "permission_key": "modules.read",
        "module_key": "modules",
        "category": "admin",
        "action": "read",
        "label": "Read modules",
        "description": "View registered modules and module metadata.",
        "risk_level": RISK_LEVEL_LOW,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
    {
        "permission_key": "modules.manage",
        "module_key": "modules",
        "category": "admin",
        "action": "manage",
        "label": "Manage modules",
        "description": "Manage module registry metadata and future module manifests.",
        "risk_level": RISK_LEVEL_HIGH,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
    {
        "permission_key": "settings.read",
        "module_key": "settings",
        "category": "admin",
        "action": "read",
        "label": "Read settings",
        "description": "View safe system settings metadata.",
        "risk_level": RISK_LEVEL_MEDIUM,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
    {
        "permission_key": "settings.manage",
        "module_key": "settings",
        "category": "admin",
        "action": "manage",
        "label": "Manage settings",
        "description": "Change system settings when a settings API is added.",
        "risk_level": RISK_LEVEL_CRITICAL,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
    {
        "permission_key": "production.release",
        "module_key": "production",
        "category": "system",
        "action": "release",
        "label": "Release production",
        "description": "Approve or execute future production release workflows.",
        "risk_level": RISK_LEVEL_CRITICAL,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
    {
        "permission_key": "system.admin",
        "module_key": "system",
        "category": "system",
        "action": "admin",
        "label": "System admin",
        "description": "Reserved high-risk system administration permission.",
        "risk_level": RISK_LEVEL_CRITICAL,
        "menu_policy": MENU_POLICY_HIDE_WHEN_DENIED,
    },
)

PERMISSIONS_BY_KEY = MappingProxyType(
    {
        permission["permission_key"]: permission
        for permission in BASE_PERMISSION_REGISTRY_SEED
    }
)


def validate_permission_key(permission_key: str) -> str:
    normalized = permission_key.strip()
    if not PERMISSION_KEY_PATTERN.fullmatch(normalized):
        raise ValueError("Permission key must use module.action segments.")
    return normalized


def validate_risk_level(risk_level: str) -> str:
    normalized = risk_level.strip().lower()
    if normalized not in ALLOWED_RISK_LEVELS:
        allowed = ", ".join(ALLOWED_RISK_LEVELS)
        raise ValueError(f"Risk level must be one of: {allowed}.")
    return normalized


def validate_menu_policy(menu_policy: str) -> str:
    normalized = menu_policy.strip().lower()
    if normalized not in ALLOWED_MENU_POLICIES:
        allowed = ", ".join(ALLOWED_MENU_POLICIES)
        raise ValueError(f"Menu policy must be one of: {allowed}.")
    return normalized


def validate_scope(scope_type: str, scope_key: str) -> tuple[str, str]:
    normalized_type = scope_type.strip().lower()
    normalized_key = scope_key.strip()
    if normalized_type not in ALLOWED_SCOPE_TYPES:
        allowed = ", ".join(ALLOWED_SCOPE_TYPES)
        raise ValueError(f"Scope type must be one of: {allowed}.")
    if not normalized_key:
        raise ValueError("Scope key must not be empty.")
    if normalized_type == SCOPE_GLOBAL and normalized_key != "*":
        raise ValueError("Global scope must use '*' as scope key.")
    return normalized_type, normalized_key


def validate_permission_definition(
    permission: PermissionDefinition,
) -> PermissionDefinition:
    permission_key = validate_permission_key(permission["permission_key"])
    module_key = permission["module_key"].strip()
    category = permission["category"].strip().lower()
    action = permission["action"].strip().lower()
    label = permission["label"].strip()
    description = permission["description"].strip()
    risk_level = validate_risk_level(permission["risk_level"])
    menu_policy = validate_menu_policy(permission["menu_policy"])

    if not module_key:
        raise ValueError("Permission module key must not be empty.")
    if not category:
        raise ValueError("Permission category must not be empty.")
    if not action:
        raise ValueError("Permission action must not be empty.")
    if not label:
        raise ValueError("Permission label must not be empty.")

    return {
        "permission_key": permission_key,
        "module_key": module_key,
        "category": category,
        "action": action,
        "label": label,
        "description": description,
        "risk_level": risk_level,
        "menu_policy": menu_policy,
    }
