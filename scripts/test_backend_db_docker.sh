#!/usr/bin/env bash
set -euo pipefail

mode="${1:---full}"
if (( $# > 0 )); then
    shift
fi
if (( $# > 0 )); then
    echo "Usage: $0 [--full|--c19]" >&2
    exit 2
fi

case "$mode" in
    --full)
        default_compose_project="barong-ops-console-f12-test"
        ;;
    --c19)
        default_compose_project="barong-ops-console-c19-migration-test"
        ;;
    *)
        echo "Usage: $0 [--full|--c19]" >&2
        exit 2
        ;;
esac

compose_project="$default_compose_project"

assert_test_compose_project() {
    if [[ "$compose_project" != *test* \
        || "$compose_project" == *prod* \
        || "$compose_project" == "barong-ops-console" ]]; then
        echo "Refusing unsafe Docker Compose project: $compose_project" >&2
        return 1
    fi
}

assert_test_compose_project

if docker compose version >/dev/null 2>&1; then
    compose=(docker compose -p "$compose_project" -f docker-compose.example.yml)
    wait_args=(--wait)
elif command -v docker-compose >/dev/null 2>&1; then
    compose=(docker-compose -p "$compose_project" -f docker-compose.example.yml)
    wait_args=()
else
    echo "Docker Compose is required (docker compose or docker-compose)." >&2
    exit 1
fi

cleanup() {
    assert_test_compose_project
    "${compose[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${compose[@]}" build backend
"${compose[@]}" up --detach "${wait_args[@]}" db

if [[ "$mode" == "--c19" ]]; then
    run_backend() {
        "${compose[@]}" run --rm -T backend "$@"
    }

    verify_native_schema() {
        local expectation="$1"
        "${compose[@]}" run --rm -T \
            -e C19_NATIVE_SCHEMA_EXPECTATION="$expectation" \
            backend python - <<'PY'
import os

from sqlalchemy import inspect, text

from backend.app.db.session import engine


HEAD = "20260712_01_c19_native_access"
PREVIOUS = "20260711_03_render_staging"
PROFILE_FK = "fk_c19_conversation_members_user_profile"
SNAPSHOT_CHECK = (
    "ck_c19_conversation_members_affiliation_snapshot_consistent"
)
PROBE_USERNAME = "c19_pg_native_access_probe"
PROBE_CONVERSATION_ID = "conv_c19_pg_native_access_probe"
PROBE_MEMBER_ID = "c19mem_pg_native_access_probe"

expectation = os.environ["C19_NATIVE_SCHEMA_EXPECTATION"]
if expectation not in {"head", "previous", "head-backfill"}:
    raise AssertionError(f"Unsupported schema expectation: {expectation}")

with engine.begin() as connection:
    revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    expected_revision = PREVIOUS if expectation == "previous" else HEAD
    assert revision == expected_revision, (revision, expected_revision)

    inspector = inspect(connection)
    columns = {
        column["name"]: column
        for column in inspector.get_columns("c19_conversation_members")
    }
    foreign_keys = {
        constraint["name"]: constraint
        for constraint in inspector.get_foreign_keys(
            "c19_conversation_members"
        )
    }
    checks = {
        constraint["name"]: constraint
        for constraint in inspector.get_check_constraints(
            "c19_conversation_members"
        )
    }

    native_schema_expected = expectation != "previous"
    assert columns["affiliation_id"]["nullable"] is native_schema_expected
    assert columns["org_id_at_join"]["nullable"] is native_schema_expected
    assert (PROFILE_FK in foreign_keys) is native_schema_expected
    assert (SNAPSHOT_CHECK in checks) is native_schema_expected

    if native_schema_expected:
        snapshot_sql = str(checks[SNAPSHOT_CHECK]["sqltext"]).lower()
        assert "affiliation_id is null" in snapshot_sql
        assert "org_id_at_join is null" in snapshot_sql
        assert "affiliation_id is not null" in snapshot_sql
        assert "org_id_at_join is not null" in snapshot_sql

    if native_schema_expected:
        profile_fk = foreign_keys[PROFILE_FK]
        assert profile_fk["referred_table"] == "c19_profiles"
        assert profile_fk["constrained_columns"] == ["user_id"]
        assert profile_fk["referred_columns"] == ["user_id"]
        assert profile_fk.get("options", {}).get("ondelete") == "RESTRICT"

    if expectation == "previous":
        # Seed a user with no organization or C19 profile. The subsequent real
        # PostgreSQL upgrade must create the one global communication card.
        connection.execute(
            text("DELETE FROM users WHERE username = :username"),
            {"username": PROBE_USERNAME},
        )
        user_id = connection.scalar(
            text(
                """
                INSERT INTO users (username, password_hash, role, is_active)
                VALUES (:username, :password_hash, 'user', true)
                RETURNING id
                """
            ),
            {
                "username": PROBE_USERNAME,
                "password_hash": "not-a-real-password-hash",
            },
        )
        assert user_id is not None
        assert connection.scalar(
            text("SELECT count(*) FROM c19_profiles WHERE user_id = :user_id"),
            {"user_id": user_id},
        ) == 0

    if expectation == "head-backfill":
        probe = connection.execute(
            text(
                """
                SELECT users.id, c19_profiles.display_name
                FROM users
                JOIN c19_profiles ON c19_profiles.user_id = users.id
                WHERE users.username = :username
                """
            ),
            {"username": PROBE_USERNAME},
        ).mappings().one()
        assert probe["display_name"] == PROBE_USERNAME

        # Exercise the actual native-user path: a conversation member with no
        # affiliation and no organization snapshot must be accepted.
        connection.execute(
            text(
                """
                INSERT INTO c19_conversations (
                    conversation_id, type, title, created_by_user_id
                ) VALUES (
                    :conversation_id, 'group', 'C19 PostgreSQL probe', :user_id
                )
                """
            ),
            {
                "conversation_id": PROBE_CONVERSATION_ID,
                "user_id": probe["id"],
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO c19_conversation_members (
                    member_id,
                    conversation_id,
                    affiliation_id,
                    user_id,
                    org_id_at_join
                ) VALUES (
                    :member_id, :conversation_id, NULL, :user_id, NULL
                )
                """
            ),
            {
                "member_id": PROBE_MEMBER_ID,
                "conversation_id": PROBE_CONVERSATION_ID,
                "user_id": probe["id"],
            },
        )
        assert connection.scalar(
            text(
                """
                SELECT count(*)
                FROM c19_conversation_members
                WHERE member_id = :member_id
                  AND affiliation_id IS NULL
                  AND org_id_at_join IS NULL
                """
            ),
            {"member_id": PROBE_MEMBER_ID},
        ) == 1

        connection.execute(
            text(
                "DELETE FROM c19_conversations "
                "WHERE conversation_id = :conversation_id"
            ),
            {"conversation_id": PROBE_CONVERSATION_ID},
        )
        connection.execute(
            text("DELETE FROM users WHERE username = :username"),
            {"username": PROBE_USERNAME},
        )

print(
    "C19 PostgreSQL schema acceptance passed: "
    f"expectation={expectation} revision={expected_revision}"
)
PY
    }

    verify_c19_alembic_drift() {
        "${compose[@]}" run --rm -T backend python - <<'PY'
from collections.abc import Iterator

from alembic.autogenerate import produce_migrations
from alembic.migration import MigrationContext

from backend.app import models  # noqa: F401 - register model metadata
from backend.app.db.base import Base
from backend.app.db.session import engine


TABLE_ATTRIBUTES = (
    "table_name",
    "source_table",
    "referent_table",
    "local_table",
    "remote_table",
)


def operation_targets(operation: object) -> tuple[str, ...]:
    return tuple(
        value
        for attribute in TABLE_ATTRIBUTES
        if isinstance((value := getattr(operation, attribute, None)), str)
    )


def leaf_operations(
    operation: object,
    inherited_targets: tuple[str, ...] = (),
) -> Iterator[tuple[object, tuple[str, ...]]]:
    targets = inherited_targets + operation_targets(operation)
    children = getattr(operation, "ops", None)
    if children:
        for child in children:
            yield from leaf_operations(child, targets)
        return
    yield operation, targets


with engine.connect() as connection:
    context = MigrationContext.configure(
        connection,
        opts={
            "compare_type": True,
            "target_metadata": Base.metadata,
        },
    )
    migration_script = produce_migrations(context, Base.metadata)

leaves = list(leaf_operations(migration_script.upgrade_ops))
c19_drift = [
    (operation, targets)
    for operation, targets in leaves
    if any(table_name.startswith("c19_") for table_name in targets)
]
if c19_drift:
    details = ", ".join(
        f"{type(operation).__name__}:{'/'.join(targets)}"
        for operation, targets in c19_drift
    )
    raise AssertionError(f"C19 Alembic drift detected: {details}")

print(
    "C19 Alembic autogenerate drift check passed: "
    f"c19_upgrade_ops=0 excluded_non_c19_upgrade_ops={len(leaves)}"
)
PY
    }

    run_backend python -m alembic -c backend/alembic.ini upgrade head
    run_backend python -m alembic -c backend/alembic.ini current
    verify_native_schema head

    run_backend sh -c '
        BARONG_TEST_DB_READY=1 python -m pytest \
            -c backend/pytest.ini \
            tests/backend/test_c19_*.py
    '

    run_backend python -m alembic -c backend/alembic.ini \
        downgrade 20260711_03_render_staging
    run_backend python -m alembic -c backend/alembic.ini current
    verify_native_schema previous

    run_backend python -m alembic -c backend/alembic.ini upgrade head
    run_backend python -m alembic -c backend/alembic.ini current
    verify_native_schema head-backfill
    verify_c19_alembic_drift
    exit 0
fi

"${compose[@]}" run --rm backend sh -c '
    python -m pytest \
        -c backend/pytest.ini \
        tests/backend/test_health.py \
        tests/backend/test_db_config.py \
        tests/backend/test_alembic_config.py \
        tests/backend/test_schema_models.py \
        tests/backend/test_security.py &&
    python -m alembic -c backend/alembic.ini upgrade head &&
    python -m alembic -c backend/alembic.ini current &&
    BARONG_TEST_DB_READY=1 python -m pytest \
        -c backend/pytest.ini \
        tests/backend/test_auth_api.py \
        tests/backend/test_user_management_api.py \
        tests/backend/test_owner_bootstrap.py \
        tests/backend/test_registry_api.py \
        tests/backend/test_jobs_api.py \
        tests/backend/test_artifacts_reviews_errors_api.py \
        tests/backend/test_memory_operation_logs_api.py \
        tests/backend/test_foundation_demo_api.py \
        tests/backend/test_n8n_test_bridge_api.py &&
    OWNER_USERNAME=f08_example_owner \
        OWNER_PASSWORD=f08-example-only-not-for-production-password \
        python -m backend.app.cli.bootstrap_owner &&
    OWNER_USERNAME=f08_example_owner \
        OWNER_PASSWORD=f08-example-only-not-for-production-password \
        python -m backend.app.cli.bootstrap_owner &&
    python -m alembic -c backend/alembic.ini downgrade base &&
    python -m alembic -c backend/alembic.ini current &&
    python -m alembic -c backend/alembic.ini upgrade head &&
    python -m alembic -c backend/alembic.ini current &&
    python -m alembic -c backend/alembic.ini check
'
