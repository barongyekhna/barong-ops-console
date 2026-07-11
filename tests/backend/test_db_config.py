from backend.app.core.config import EXAMPLE_DATABASE_URL, Settings
from backend.app.db.base import Base, metadata
from backend.app.main import app
from backend.app import models  # noqa: F401

CORE_BUSINESS_TABLES = {
    "agent_registry",
    "agent_memory_access_logs",
    "anomaly_events",
    "api_key_module_bindings",
    "api_key_records",
    "approval_workflows",
    "approval_decisions",
    "approval_requests",
    "artifacts",
    "audit_logs",
    "auth_sessions",
    "automation_jobs",
    "callback_state",
    "callback_state_transitions",
    "c19_affiliations",
    "c19_conversation_members",
    "c19_conversation_user_settings",
    "c19_conversations",
    "c19_friend_requests",
    "c19_profiles",
    "c19_relationships",
    "c19_user_blocks",
    "contact_identities",
    "context_packets",
    "dlq_state",
    "event_streams",
    "execution_callbacks",
    "execution_dlq",
    "execution_results",
    "job_events",
    "memory_events",
    "memory_summaries",
    "messages",
    "module_bindings",
    "module_control_states",
    "module_registry",
    "operation_logs",
    "ops_alert_deliveries",
    "ops_alerts",
    "ops_canary_rollouts",
    "ops_execution_unlock_tokens",
    "ops_live_gate_policies",
    "ops_rollback_guards",
    "org_memberships",
    "organizations",
    "permission_registry",
    "replay_jobs",
    "review_items",
    "role_default_permissions",
    "security_rate_limit_buckets",
    "security_replay_nonces",
    "shared_modules",
    "storage_events",
    "system_errors",
    "user_permission_assignments",
    "users",
    "workflow_registry",
}

K_SERIES_EXTENSION_TABLES = {
    "k_product_knowledge_ai_events",
    "k_product_knowledge_attributes",
    "k_product_knowledge_keywords",
    "k_product_knowledge_media_assets",
    "k_product_knowledge_products",
    "k_product_knowledge_research_runs",
    "k_product_knowledge_review_items",
    "k_product_knowledge_risk_terms",
    "k_product_knowledge_translations",
    "k_product_knowledge_variants",
    "k_product_knowledge_versions",
    "k_product_knowledge_workflow_executions",
    "provider_config",
}


def test_app_imports() -> None:
    assert app.title == "barong-ops-console-backend"


def test_database_url_uses_example_default(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings()

    assert settings.database_url == EXAMPLE_DATABASE_URL
    assert "barong_console_example" in settings.database_url
    assert "production" not in settings.database_url.lower()
    assert "prod" not in settings.database_url.lower()


def test_sqlalchemy_metadata_contains_core_foundation_tables() -> None:
    assert Base.metadata is metadata
    metadata_tables = set(metadata.tables)

    assert CORE_BUSINESS_TABLES <= metadata_tables
    assert K_SERIES_EXTENSION_TABLES <= metadata_tables
