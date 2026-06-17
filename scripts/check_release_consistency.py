#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from backend.app.core.config import get_settings


def script_head() -> str:
    config = Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected exactly one Alembic head, found {heads!r}.")
    return heads[0]


def current_schema_revision(database_url: str) -> str:
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        if not inspect(connection).has_table("alembic_version"):
            raise RuntimeError("Database is missing alembic_version.")
        revisions = tuple(
            row[0]
            for row in connection.execute(text("select version_num from alembic_version"))
        )
    if len(revisions) != 1:
        raise RuntimeError(f"Expected one Alembic revision, found {revisions!r}.")
    return revisions[0]


def app_version_from_health(health_url: str) -> str:
    with urllib.request.urlopen(health_url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError(f"Health response did not contain version: {payload!r}")
    return version.strip()


def read_manifest(path: str | None) -> dict[str, Any]:
    if path is None:
        return {}
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("Release manifest must be a JSON object.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate app-version and DB-schema consistency after release or rollback.",
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--health-url", default=None)
    parser.add_argument("--expected-app-version", default=None)
    parser.add_argument("--expected-schema-revision", default=None)
    parser.add_argument("--release-manifest", default=None)
    parser.add_argument(
        "--strict-equal",
        action="store_true",
        help="Also require the app version string to equal the Alembic revision string.",
    )
    args = parser.parse_args()

    settings = get_settings()
    manifest = read_manifest(args.release_manifest)
    database_url = args.database_url or settings.database_url
    expected_app_version = (
        args.expected_app_version
        or manifest.get("app_version")
        or settings.app_version
    )
    expected_schema_revision = (
        args.expected_schema_revision
        or manifest.get("schema_revision")
        or script_head()
    )

    current_app_version = (
        app_version_from_health(args.health_url)
        if args.health_url
        else settings.app_version
    )
    current_schema = current_schema_revision(database_url)
    consistent = (
        current_app_version == expected_app_version
        and current_schema == expected_schema_revision
    )
    if args.strict_equal:
        consistent = consistent and current_app_version == current_schema

    print(
        "release_consistency "
        f"app_version={current_app_version} "
        f"schema_revision={current_schema} "
        f"expected_app_version={expected_app_version} "
        f"expected_schema_revision={expected_schema_revision} "
        f"strict_equal={str(args.strict_equal).lower()} "
        f"consistent={str(consistent).lower()}"
    )
    return 0 if consistent else 1


if __name__ == "__main__":
    sys.exit(main())
