#!/usr/bin/env bash
set -euo pipefail

compose_project="barong-ops-console-f11-frontend-test"

if docker compose version >/dev/null 2>&1; then
    compose=(docker compose -p "$compose_project" -f docker-compose.example.yml)
elif command -v docker-compose >/dev/null 2>&1; then
    compose=(docker-compose -p "$compose_project" -f docker-compose.example.yml)
else
    echo "Docker Compose is required (docker compose or docker-compose)." >&2
    exit 1
fi

"${compose[@]}" build frontend
