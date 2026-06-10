from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPOSITORY_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260610_01_create_permission_tables.py"
)

PERMISSION_TABLES = {
    "permission_registry",
    "user_permission_assignments",
    "role_default_permissions",
}

EXISTING_CORE_TABLES = {
    "users",
    "operation_logs",
    "module_registry",
}


def test_permission_migration_only_manages_permission_tables() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    lowered = source.lower()

    assert 'down_revision: str | sequence[str] | none = "f07_core_001"' in lowered
    assert "insert" not in lowered
    for table_name in PERMISSION_TABLES:
        assert f'"{table_name}"' in source

    for table_name in EXISTING_CORE_TABLES:
        assert f'drop_table("{table_name}")' not in source
        assert f'create_table("{table_name}")' not in source
