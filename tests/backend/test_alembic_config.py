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

    assert "target_metadata = Base.metadata" in env_source
    assert "get_settings().database_url" in env_source


def test_versions_contain_no_business_table_migrations() -> None:
    migration_files = [
        path
        for path in VERSIONS_ROOT.rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    ]

    assert migration_files == []

    migration_source = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in migration_files
    )
    assert not any(table_name in migration_source for table_name in CORE_BUSINESS_TABLES)
