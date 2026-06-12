"""Module-local constants for the unregistered K Product Knowledge skeleton."""

MODULE_KEY = "k.product_knowledge"
API_PREFIX = "/api/k/product-knowledge"

DEFAULT_WORKSPACE_KEY = "default_independent_store"
DEFAULT_BUSINESS_CONTEXT = "independent_store"
DEFAULT_SCOPE_MODE = "adapter_pending"
DEFAULT_CANONICAL_LANGUAGE = "en"

PERMISSION_READ = "k.product_knowledge.read"
PERMISSION_CREATE = "k.product_knowledge.create"
PERMISSION_UPDATE = "k.product_knowledge.update"
PERMISSION_ARCHIVE = "k.product_knowledge.archive"
PERMISSION_ATTRIBUTES_MANAGE = "k.product_knowledge.attributes.manage"
PERMISSION_KEYWORDS_MANAGE = "k.product_knowledge.keywords.manage"
PERMISSION_RISK_TERMS_MANAGE = "k.product_knowledge.risk_terms.manage"

PERMISSION_KEYS = frozenset(
    {
        PERMISSION_READ,
        PERMISSION_CREATE,
        PERMISSION_UPDATE,
        PERMISSION_ARCHIVE,
        PERMISSION_ATTRIBUTES_MANAGE,
        PERMISSION_KEYWORDS_MANAGE,
        PERMISSION_RISK_TERMS_MANAGE,
    }
)

ACTION_PERMISSION_KEYS = {
    "read": PERMISSION_READ,
    "create": PERMISSION_CREATE,
    "update": PERMISSION_UPDATE,
    "archive": PERMISSION_ARCHIVE,
    "attributes.manage": PERMISSION_ATTRIBUTES_MANAGE,
    "keywords.manage": PERMISSION_KEYWORDS_MANAGE,
    "risk_terms.manage": PERMISSION_RISK_TERMS_MANAGE,
}

OPERATION_PRODUCT_CREATED = "k.product_knowledge.created"
OPERATION_PRODUCT_UPDATED = "k.product_knowledge.updated"
OPERATION_PRODUCT_ARCHIVED = "k.product_knowledge.archived"
OPERATION_ATTRIBUTE_UPDATED = "k.product_knowledge.attribute.updated"
OPERATION_KEYWORD_UPDATED = "k.product_knowledge.keyword.updated"
OPERATION_RISK_TERM_UPDATED = "k.product_knowledge.risk_term.updated"

OPERATION_ACTIONS = frozenset(
    {
        OPERATION_PRODUCT_CREATED,
        OPERATION_PRODUCT_UPDATED,
        OPERATION_PRODUCT_ARCHIVED,
        OPERATION_ATTRIBUTE_UPDATED,
        OPERATION_KEYWORD_UPDATED,
        OPERATION_RISK_TERM_UPDATED,
    }
)
