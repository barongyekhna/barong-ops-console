#!/usr/bin/env bash
set -euo pipefail

compose_project="barong-ops-console-f06-test"

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
    python -m alembic -c backend/alembic.ini current &&
    python -m alembic -c backend/alembic.ini upgrade head &&
    python -m alembic -c backend/alembic.ini check &&
    python -m pytest \
        tests/backend/test_health.py \
        tests/backend/test_db_config.py \
        tests/backend/test_alembic_config.py
'
