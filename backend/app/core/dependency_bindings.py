from typing import Any


# C14E is a dependency binding rules layer only. These declarations do not
# register a service, grant runtime access, or create provider credentials.
MODULE_SERVICE_BINDINGS_V1: tuple[dict[str, Any], ...] = (
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
        "service_id": "n8n",
        "capabilities": [],
        "binding_status": "disabled",
        "reason": "n8n has no C14E capability mapping enabled by default.",
    },
)
