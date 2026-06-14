from backend.app.core.config import EXAMPLE_DATABASE_URL, Settings
from backend.app.db.base import Base, metadata
from backend.app.main import app
from backend.app import models  # noqa: F401

CORE_BUSINESS_TABLES = {
    "users",
    "module_registry",
    "agent_registry",
    "workflow_registry",
    "automation_jobs",
    "job_events",
    "artifacts",
    "review_items",
    "system_errors",
    "memory_events",
    "operation_logs",
    "context_packets",
    "memory_summaries",
    "agent_memory_access_logs",
    "permission_registry",
    "user_permission_assignments",
    "role_default_permissions",
    "approval_requests",
    "approval_workflows",
    "approval_decisions",
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
    assert set(metadata.tables) == CORE_BUSINESS_TABLES
