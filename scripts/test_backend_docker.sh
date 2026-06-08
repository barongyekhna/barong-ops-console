#!/usr/bin/env bash
set -euo pipefail

if docker compose version >/dev/null 2>&1; then
    docker compose -f docker-compose.example.yml build backend
    docker compose -f docker-compose.example.yml run --rm backend python -m pytest tests/backend/test_health.py
elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f docker-compose.example.yml build backend
    docker-compose -f docker-compose.example.yml run --rm backend python -m pytest tests/backend/test_health.py
else
    echo "Docker Compose is required (docker compose or docker-compose)." >&2
    exit 1
fi
