#!/usr/bin/env bash
set -euo pipefail

compose_project="barong-ops-console-f12-test"

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
    "${compose[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${compose[@]}" build backend
"${compose[@]}" up --detach "${wait_args[@]}" db
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
