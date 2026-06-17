import pytest
from sqlalchemy import inspect, text

from backend.app.db.session import engine

pytestmark = pytest.mark.integration

ALEMBIC_HEAD = "c17_durable_observability_001"

REQUIRED_ALEMBIC_TABLES = {
    "alembic_version",
    "users",
    "auth_sessions",
    "organizations",
    "org_memberships",
    "module_bindings",
    "execution_callbacks",
    "execution_dlq",
    "execution_results",
    "event_streams",
    "audit_logs",
    "anomaly_events",
    "replay_jobs",
}


def test_alembic_upgrade_head_created_required_schema() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    missing_tables = REQUIRED_ALEMBIC_TABLES - table_names
    assert not missing_tables

    with engine.connect() as connection:
        current_revision = connection.execute(
            text("select version_num from alembic_version")
        ).scalar_one()

    assert current_revision == ALEMBIC_HEAD
