from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_pre20_o_backup_restore_scripts_are_guarded_and_versioned() -> None:
    backup = _read("scripts/pg_backup.sh")
    restore = _read("scripts/pg_restore_db.sh")

    assert "pg_dump" in backup
    assert "--format=custom" in backup
    assert "--compress=9" in backup
    assert "barong_ops_${timestamp}.dump" in backup
    assert "alembic_revision=" in backup

    assert "pg_restore" in restore
    assert "--single-transaction" in restore
    assert "validate_archive_schema" in restore
    assert "alembic_version" in restore
    assert "CONFIRM_DB_RESTORE=yes" in restore
    assert "scripts/check_migration_safety.py" in restore


def test_pre20_o_rollback_scripts_cover_app_db_and_consistency() -> None:
    app_rollback = _read("scripts/rollback_release.sh")
    db_rollback = _read("scripts/db_rollback.sh")
    consistency = _read("scripts/check_release_consistency.py")

    assert "rollback-*" in app_rollback
    assert "docker tag" in app_rollback
    assert "docker-compose -p" in app_rollback
    assert "check_release_consistency.py" in app_rollback
    assert "CONFIRM_APP_ROLLBACK=yes" in app_rollback

    assert "restore-latest" in db_rollback
    assert "restore-archive" in db_rollback
    assert "alembic-downgrade" in db_rollback
    assert "CONFIRM_DB_ROLLBACK=yes" in db_rollback

    assert "current_schema_revision" in consistency
    assert "expected_app_version" in consistency
    assert "expected_schema_revision" in consistency
    assert "consistent=" in consistency


def test_pre20_o_dr_policy_defines_required_recovery_contract() -> None:
    policy = _read("docs/dr_policy.md")

    for required in (
        "RPO",
        "RTO, DB crash",
        "RTO, server crash",
        "RTO, region loss",
        "DB Crash",
        "Server Crash",
        "Region Loss",
        "scripts/pg_restore_db.sh",
        "scripts/rollback_release.sh",
        "ops_alerts",
    ):
        assert required in policy


def test_pre20_o_simulation_script_covers_required_scenarios() -> None:
    simulation = _read("scripts/simulate_pre20_o_dr.sh")

    assert "DB backup plan" in simulation
    assert "backup restore validation" in simulation
    assert "application rollback plan" in simulation
    assert "DB rollback restore-latest plan" in simulation
    assert "Alembic downgrade rollback plan" in simulation
    assert "ops_alerts" in simulation
