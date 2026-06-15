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
    "auth_sessions",
    "security_rate_limit_buckets",
    "security_replay_nonces",
}
REQUIRED_MIGRATION_SUFFIXES = {
    "create_core_foundation_tables.py",
    "create_permission_tables.py",
    "create_approval_tables.py",
    "create_auth_sessions.py",
    "add_login_lockout_fields.py",
    "c16_adv_security_hardening.py",
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
    migration_names = {migration_file.name for migration_file in migration_files}

    assert len(migration_files) >= len(REQUIRED_MIGRATION_SUFFIXES)
    assert all(
        any(name.endswith(suffix) for name in migration_names)
        for suffix in REQUIRED_MIGRATION_SUFFIXES
    )

    migration_sources = [
        migration_file.read_text(encoding="utf-8").lower()
        for migration_file in migration_files
    ]
    assert all("insert" not in source for source in migration_sources)
    assert all(
        any(table_name in source for source in migration_sources)
        for table_name in CORE_BUSINESS_TABLES
    )
