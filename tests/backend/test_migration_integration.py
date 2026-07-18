import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from backend.app.db.session import engine

pytestmark = pytest.mark.integration

ALEMBIC_CONFIG = "backend/alembic.ini"

REQUIRED_ALEMBIC_TABLES = {
    "alembic_version",
    "arcade_high_scores",
    "users",
    "auth_sessions",
    "organizations",
    "org_memberships",
    "module_bindings",
    "module_control_states",
    "api_key_records",
    "api_key_module_bindings",
    "execution_callbacks",
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
    "dlq_state",
    "execution_dlq",
    "execution_results",
    "event_streams",
    "audit_logs",
    "anomaly_events",
    "replay_jobs",
    "storage_events",
    "ops_alerts",
    "ops_alert_deliveries",
    "ops_live_gate_policies",
    "ops_execution_unlock_tokens",
    "ops_canary_rollouts",
    "ops_rollback_guards",
    "k_category_spec_templates",
    "k_product_knowledge_products",
    "k_product_knowledge_attributes",
    "k_product_knowledge_translations",
    "k_product_knowledge_keywords",
    "k_product_knowledge_variants",
    "k_product_knowledge_risk_terms",
    "k_product_knowledge_research_runs",
    "k_product_knowledge_ai_events",
    "k_product_knowledge_workflow_executions",
    "k_product_knowledge_versions",
    "k_product_knowledge_media_assets",
    "k_product_knowledge_review_items",
    "provider_config",
}


def test_alembic_upgrade_head_created_required_schema() -> None:
    script = ScriptDirectory.from_config(Config(ALEMBIC_CONFIG))
    heads = tuple(script.get_heads())
    assert len(heads) == 1
    alembic_head = heads[0]

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    missing_tables = REQUIRED_ALEMBIC_TABLES - table_names
    assert not missing_tables

    with engine.connect() as connection:
        current_revision = connection.execute(
            text("select version_num from alembic_version")
        ).scalar_one()

    assert current_revision == alembic_head
