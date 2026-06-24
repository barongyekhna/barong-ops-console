from typing import Any


# C14E is a dependency binding rules layer only. These declarations do not
# register a service, grant runtime access, or create provider credentials.
MODULE_SERVICE_BINDINGS_V1: tuple[dict[str, Any], ...] = (
    {
        "module_key": "k.product_knowledge",
        "service_id": "serp",
        "binding_status": "restricted",
        "allowed_capabilities": ["serp"],
        "reason": "K product knowledge may use SERP capability after explicit key binding.",
    },
    {
        "module_key": "k.product_knowledge",
        "service_id": "deepseek",
        "binding_status": "restricted",
        "allowed_capabilities": ["reasoning", "writing"],
        "reason": "K product knowledge may use DeepSeek enrichment after explicit key binding.",
    },
    {
        "module_key": "k.product_knowledge",
        "service_id": "chatgpt",
        "binding_status": "restricted",
        "allowed_capabilities": ["reasoning", "writing"],
        "reason": "K product knowledge must use ChatGPT as the first AI keyword filter after explicit key binding.",
    },
    {
        "module_key": "k.product_knowledge",
        "service_id": "claude_opus",
        "binding_status": "restricted",
        "allowed_capabilities": ["reasoning", "writing"],
        "reason": "K product knowledge must use Claude Opus as the second AI keyword filter after explicit key binding.",
    },
    {
        "module_key": "k.product_knowledge",
        "service_id": "ai_provider",
        "binding_status": "restricted",
        "allowed_capabilities": ["reasoning", "writing"],
        "reason": "K product knowledge may use AI reasoning after explicit key binding.",
    },
    {
        "module_key": "k.product_knowledge",
        "service_id": "n8n",
        "binding_status": "restricted",
        "allowed_capabilities": ["writing"],
        "reason": "K product knowledge may hand off normalized output to downstream product workflows.",
    },
    {
        "module_key": "integration.n8n_test_bridge",
        "service_id": "n8n",
        "binding_status": "disabled",
        "allowed_capabilities": [],
        "reason": "n8n is explicitly declared but no C14E capability is enabled.",
    },
)

MODULE_CAPABILITY_BINDINGS_V1: tuple[dict[str, Any], ...] = (
    {
        "module_key": "k.product_knowledge",
        "allowed_capabilities": ["serp", "reasoning", "writing"],
        "binding_status": "restricted",
        "reason": "K product knowledge is restricted to product research and enrichment capabilities.",
    },
    {
        "module_key": "integration.n8n_test_bridge",
        "allowed_capabilities": [],
        "binding_status": "disabled",
        "reason": (
            "The test bridge has no serp, reasoning, writing, or "
            "embedding grant."
        ),
    },
)

SERVICE_CAPABILITY_MAPPINGS_V1: tuple[dict[str, Any], ...] = (
    {
        "service_id": "serp",
        "capabilities": ["serp"],
        "binding_status": "restricted",
        "reason": "SERP service is restricted to search result acquisition.",
    },
    {
        "service_id": "deepseek",
        "capabilities": ["reasoning", "writing"],
        "binding_status": "restricted",
        "reason": "DeepSeek service is restricted to product enrichment.",
    },
    {
        "service_id": "chatgpt",
        "capabilities": ["reasoning", "writing"],
        "binding_status": "restricted",
        "reason": "ChatGPT service is restricted to first-pass keyword filtering.",
    },
    {
        "service_id": "claude_opus",
        "capabilities": ["reasoning", "writing"],
        "binding_status": "restricted",
        "reason": "Claude Opus service is restricted to second-pass keyword filtering.",
    },
    {
        "service_id": "ai_provider",
        "capabilities": ["reasoning", "writing"],
        "binding_status": "restricted",
        "reason": "AI provider service is restricted to product reasoning tasks.",
    },
    {
        "service_id": "n8n",
        "capabilities": ["writing"],
        "binding_status": "restricted",
        "reason": "n8n service is restricted to declared downstream handoff tasks.",
    },
)
