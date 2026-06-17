#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from sqlalchemy import create_engine

from backend.app.core.config import get_settings
from backend.app.db.migration_safety import (
    build_migration_safety_report,
    default_alembic_ini_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Alembic head/current state before a migration rollout.",
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--app-env", default=None)
    parser.add_argument("--alembic-ini", default=None)
    args = parser.parse_args()

    settings = get_settings()
    database_url = args.database_url or settings.database_url
    app_env = args.app_env or settings.app_env
    alembic_ini = args.alembic_ini or default_alembic_ini_path()

    engine = create_engine(database_url, pool_pre_ping=True)
    report = build_migration_safety_report(
        engine,
        app_env=app_env,
        alembic_ini_path=alembic_ini,
    )
    print(
        "migration_safety "
        f"env={app_env} "
        f"expected_heads={','.join(report.expected_heads) or '[missing]'} "
        f"current={','.join(report.current_revisions) or '[missing]'} "
        f"dirty={str(report.dirty).lower()} "
        f"head_mismatch={str(report.head_mismatch).lower()} "
        f"production_blocked={str(report.production_blocked).lower()} "
        f"reason={report.reason}"
    )
    return 1 if report.production_blocked else 0


if __name__ == "__main__":
    sys.exit(main())
