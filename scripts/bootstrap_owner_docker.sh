#!/usr/bin/env bash
set -euo pipefail

compose_project="${COMPOSE_PROJECT_NAME:-barong-ops-console-example}"

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

"${compose[@]}" build backend
"${compose[@]}" up --detach "${wait_args[@]}" db
"${compose[@]}" run --rm backend \
    python -m alembic -c backend/alembic.ini upgrade head
"${compose[@]}" run --rm \
    -e OWNER_USERNAME \
    -e OWNER_PASSWORD \
    backend python -m backend.app.cli.bootstrap_owner
