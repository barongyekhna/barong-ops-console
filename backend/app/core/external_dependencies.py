from typing import Any


# C14D intentionally ships with no built-in service/provider allowlist.
# Dynamic registration data must be supplied by a controlled registry source.
EXTERNAL_SERVICE_REGISTRY_V1: tuple[dict[str, Any], ...] = (
    {
        "service_id": "serp",
        "service_type": "ai_api",
        "status": "active",
        "trust_level": "medium",
        "metadata": {"scope": "k_product_keyword_research"},
    },
    {
        "service_id": "deepseek",
        "service_type": "ai_api",
        "status": "active",
        "trust_level": "medium",
        "metadata": {"scope": "k_product_enrichment"},
    },
    {
        "service_id": "ai_provider",
        "service_type": "ai_api",
        "status": "active",
        "trust_level": "medium",
        "metadata": {"scope": "k_product_reasoning"},
    },
    {
        "service_id": "n8n",
        "service_type": "automation",
        "status": "active",
        "trust_level": "medium",
        "metadata": {"scope": "k_product_handoff"},
    },
)
EXTERNAL_DEPENDENCY_POLICIES_V1: tuple[dict[str, Any], ...] = (
    {
        "policy_id": "k.product_knowledge.serp.allow",
        "description": "Allow K product knowledge SERP capability by registered service id.",
        "module": "k.product_knowledge",
        "action": "k.product_knowledge.serp.execute",
        "service_id": "serp",
        "min_trust_level": "medium",
        "decision": "allow",
        "requires_c12_approval": False,
        "enabled": True,
    },
    {
        "policy_id": "k.product_knowledge.deepseek.allow",
        "description": "Allow K product knowledge DeepSeek enrichment by registered service id.",
        "module": "k.product_knowledge",
        "action": "k.product_knowledge.ai_enrich.execute",
        "service_id": "deepseek",
        "min_trust_level": "medium",
        "decision": "allow",
        "requires_c12_approval": False,
        "enabled": True,
    },
    {
        "policy_id": "k.product_knowledge.ai_provider.allow",
        "description": "Allow K product knowledge AI reasoning by registered service id.",
        "module": "k.product_knowledge",
        "action": "k.product_knowledge.prompt.execute",
        "service_id": "ai_provider",
        "min_trust_level": "medium",
        "decision": "allow",
        "requires_c12_approval": False,
        "enabled": True,
    },
    {
        "policy_id": "k.product_knowledge.risk_filter.allow",
        "description": "Allow K product knowledge risk filtering by registered service id.",
        "module": "k.product_knowledge",
        "action": "k.product_knowledge.risk_filter.execute",
        "service_id": "ai_provider",
        "min_trust_level": "medium",
        "decision": "require_approval",
        "requires_c12_approval": True,
        "enabled": True,
    },
)
