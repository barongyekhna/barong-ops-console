from typing import Any


# C15A is the single source of truth for Console module -> n8n workflow
# metadata. Webhook values are opaque references only; real n8n URLs stay
# outside the registry and are not exposed by API responses.
WORKFLOW_REGISTRY_V1: tuple[dict[str, Any], ...] = (
    {
        "workflow_id": "n8n.workflow.k.product_knowledge.to_p_series.v1",
        "module": "k.product_knowledge",
        "trigger": "webhook",
        "status": "active",
        "n8n_webhook": (
            "n8n-webhook-ref://c15a/k.product_knowledge/"
            "to-p-series/v1"
        ),
        "version": "1.0.0",
        "created_at": "2026-06-24T00:00:00Z",
        "updated_at": "2026-06-24T00:00:00Z",
    },
    {
        "workflow_id": "n8n.workflow.k.product_knowledge.to_gmc.v1",
        "module": "k.product_knowledge",
        "trigger": "webhook",
        "status": "active",
        "n8n_webhook": (
            "n8n-webhook-ref://c15a/k.product_knowledge/"
            "to-gmc/v1"
        ),
        "version": "1.0.0",
        "created_at": "2026-06-24T00:00:00Z",
        "updated_at": "2026-06-24T00:00:00Z",
    },
    {
        "workflow_id": "n8n.workflow.k.product_knowledge.to_seo.v1",
        "module": "k.product_knowledge",
        "trigger": "webhook",
        "status": "active",
        "n8n_webhook": (
            "n8n-webhook-ref://c15a/k.product_knowledge/"
            "to-seo/v1"
        ),
        "version": "1.0.0",
        "created_at": "2026-06-24T00:00:00Z",
        "updated_at": "2026-06-24T00:00:00Z",
    },
    {
        "workflow_id": "n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
        "module": "integration.n8n_test_bridge",
        "trigger": "webhook",
        "status": "active",
        "n8n_webhook": (
            "n8n-webhook-ref://c15a/integration.n8n_test_bridge/"
            "dispatch/v1"
        ),
        "version": "1.0.0",
        "created_at": "2026-06-15T00:00:00Z",
        "updated_at": "2026-06-15T00:00:00Z",
    },
    {
        "workflow_id": "n8n.workflow.integration.n8n_test_bridge.legacy.v1",
        "module": "integration.n8n_test_bridge",
        "trigger": "webhook",
        "status": "deprecated",
        "n8n_webhook": (
            "n8n-webhook-ref://c15a/integration.n8n_test_bridge/"
            "legacy/v1"
        ),
        "version": "1.0.0",
        "created_at": "2026-06-15T00:00:00Z",
        "updated_at": "2026-06-15T00:00:00Z",
    },
)
