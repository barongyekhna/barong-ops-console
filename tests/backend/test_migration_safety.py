from __future__ import annotations

from sqlalchemy import create_engine, text

from backend.app.db import migration_safety


def _engine_with_revision(revision: str):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("create table alembic_version (version_num text)"))
        connection.execute(
            text("insert into alembic_version (version_num) values (:revision)"),
            {"revision": revision},
        )
    return engine


def test_c05b_production_compatibility_baseline_does_not_block_startup(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        migration_safety,
        "_script_heads",
        lambda alembic_ini_path=None: ("pre20_q_live_enable_gate_001",),
    )

    report = migration_safety.build_migration_safety_report(
        _engine_with_revision("c05b_permissions_001"),
        app_env="production",
    )

    assert report.current_revisions == ("c05b_permissions_001",)
    assert report.expected_heads == ("pre20_q_live_enable_gate_001",)
    assert report.head_mismatch is True
    assert report.clean is False
    assert report.production_blocked is False
    assert "production compatibility baseline" in report.reason


def test_non_baseline_production_head_mismatch_still_blocks(monkeypatch) -> None:
    monkeypatch.setattr(
        migration_safety,
        "_script_heads",
        lambda alembic_ini_path=None: ("pre20_q_live_enable_gate_001",),
    )

    report = migration_safety.build_migration_safety_report(
        _engine_with_revision("c12d_approval_001"),
        app_env="production",
    )

    assert report.head_mismatch is True
    assert report.production_blocked is True
