from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sqlalchemy import Engine, inspect, text

from ..core.environments import is_production_like

PRODUCTION_COMPATIBILITY_BASELINE_REVISIONS = frozenset(("c05b_permissions_001",))


class MigrationSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class MigrationSafetyReport:
    expected_heads: tuple[str, ...]
    current_revisions: tuple[str, ...]
    dirty: bool
    head_mismatch: bool
    production_blocked: bool
    reason: str

    @property
    def clean(self) -> bool:
        return not self.dirty and not self.head_mismatch


def default_alembic_ini_path() -> Path:
    return Path(__file__).resolve().parents[2] / "alembic.ini"


def _normalize(values: Iterable[str | None]) -> tuple[str, ...]:
    return tuple(sorted(value for value in values if value))


def _script_heads(alembic_ini_path: Path | None = None) -> tuple[str, ...]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(alembic_ini_path or default_alembic_ini_path()))
    script = ScriptDirectory.from_config(config)
    return _normalize(script.get_heads())


def _current_revisions(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        if not inspect(connection).has_table("alembic_version"):
            return ()
        rows = connection.execute(text("select version_num from alembic_version"))
        return _normalize(row[0] for row in rows)


def build_migration_safety_report(
    engine: Engine,
    *,
    app_env: str,
    alembic_ini_path: Path | None = None,
) -> MigrationSafetyReport:
    expected_heads = _script_heads(alembic_ini_path)
    current_revisions = _current_revisions(engine)
    dirty = len(expected_heads) != 1 or len(current_revisions) != 1
    head_mismatch = current_revisions != expected_heads

    reason = "migration state is clean"
    if not expected_heads:
        reason = "alembic script head is missing"
    elif not current_revisions:
        reason = "database alembic_version is missing"
    elif len(expected_heads) != 1:
        reason = f"multiple alembic heads found: {', '.join(expected_heads)}"
    elif len(current_revisions) != 1:
        reason = (
            "database alembic_version is dirty: "
            f"{', '.join(current_revisions)}"
        )
    elif head_mismatch:
        reason = (
            f"database revision {current_revisions[0]} does not match "
            f"script head {expected_heads[0]}"
        )

    production_like = is_production_like(app_env)
    compatibility_baseline_allowed = (
        production_like
        and len(expected_heads) == 1
        and len(current_revisions) == 1
        and current_revisions[0] in PRODUCTION_COMPATIBILITY_BASELINE_REVISIONS
        and head_mismatch
    )
    if compatibility_baseline_allowed:
        reason = (
            f"database revision {current_revisions[0]} is accepted as a "
            f"production compatibility baseline; script head {expected_heads[0]} "
            "remains unapplied"
        )

    production_blocked = production_like and (
        dirty or head_mismatch
    ) and not compatibility_baseline_allowed
    return MigrationSafetyReport(
        expected_heads=expected_heads,
        current_revisions=current_revisions,
        dirty=dirty,
        head_mismatch=head_mismatch,
        production_blocked=production_blocked,
        reason=reason,
    )


def enforce_migration_safety(
    engine: Engine,
    *,
    app_env: str,
    alembic_ini_path: Path | None = None,
) -> MigrationSafetyReport:
    report = build_migration_safety_report(
        engine,
        app_env=app_env,
        alembic_ini_path=alembic_ini_path,
    )
    if report.production_blocked:
        raise MigrationSafetyError(
            "Production-like startup blocked by migration safety check: "
            f"{report.reason}"
        )
    return report
