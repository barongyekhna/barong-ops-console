from pathlib import Path

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

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_ROOT = REPOSITORY_ROOT / "backend" / "alembic"
VERSIONS_ROOT = ALEMBIC_ROOT / "versions"


def test_alembic_skeleton_exists() -> None:
    assert (REPOSITORY_ROOT / "backend" / "alembic.ini").is_file()
    assert (ALEMBIC_ROOT / "env.py").is_file()
    assert (ALEMBIC_ROOT / "script.py.mako").is_file()
    assert VERSIONS_ROOT.is_dir()


def test_alembic_targets_empty_metadata() -> None:
    env_source = (ALEMBIC_ROOT / "env.py").read_text(encoding="utf-8")

    assert "from backend.app import models" in env_source
    assert "target_metadata = Base.metadata" in env_source
    assert "get_settings().database_url" in env_source


def test_versions_contain_core_permission_and_approval_migrations() -> None:
    migration_files = sorted(VERSIONS_ROOT.glob("*.py"))

    assert len(migration_files) == 3
    assert migration_files[0].name.endswith("create_core_foundation_tables.py")
    assert migration_files[1].name.endswith("create_permission_tables.py")
    assert migration_files[2].name.endswith("create_approval_tables.py")

    migration_sources = [
        migration_file.read_text(encoding="utf-8").lower()
        for migration_file in migration_files
    ]
    assert all("insert" not in source for source in migration_sources)
    assert all(
        any(table_name in source for source in migration_sources)
        for table_name in CORE_BUSINESS_TABLES
    )
