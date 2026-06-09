#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

fail() {
    printf 'F13 acceptance failed: %s\n' "$1" >&2
    exit 1
}

./scripts/test_backend_docker.sh
./scripts/test_backend_db_docker.sh
./scripts/test_frontend_docker.sh

if docker compose version >/dev/null 2>&1; then
    compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    compose=(docker-compose)
else
    fail "Docker Compose is required."
fi

"${compose[@]}" -f docker-compose.example.yml config >/dev/null

git diff --check -- \
    backend/app \
    tests/backend \
    frontend/src \
    frontend/scripts \
    scripts \
    README.md \
    CHANGELOG.md \
    docker-compose.example.yml \
    .env.example \
    backend/README.md \
    frontend/README.md \
    docs

git diff --quiet -- \
    backend/alembic \
    backend/requirements.txt \
    frontend/package.json \
    frontend/package-lock.json ||
    fail "A migration or dependency file has an uncommitted change."

registration_endpoint="/auth/"'register'
if rg -n -F "$registration_endpoint" backend/app frontend/src; then
    fail "A public registration API reference was found."
fi

if find frontend/src/app -type d -name register -print -quit | rg -q .; then
    fail "A public registration route was found."
fi

if rg -n \
    'from urllib|import (aiohttp|httpx|requests)' \
    backend/app \
    --glob '!backend/app/services/n8n_test_http_client.py' \
    --glob '!backend/app/services/n8n_test_service.py'; then
    fail "An external HTTP client exists outside the F12 test bridge."
fi

if rg -n -i \
    '(from|import|require[[:space:]]*\()[^[:cntrl:]]*(woocommerce|minio|filebrowser)' \
    backend/app frontend/src; then
    fail "A prohibited external service SDK import was found."
fi

if rg -n 'https?://' backend/app frontend/src \
    --glob '!backend/app/schemas/artifacts.py'; then
    fail "A runtime source URL was found."
fi

if rg -n \
    --glob '*.{py,ts,tsx,js,jsx}' \
    -- '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' \
    backend/app frontend/src; then
    fail "A private key block was found."
fi

if rg -n -i \
    'Bearer[[:space:]]+[A-Za-z0-9._~+/-]{16,}' \
    backend/app frontend/src; then
    fail "A hard-coded Bearer credential was found."
fi

if rg -n \
    'console[[:space:]]*\.[[:space:]]*(log|debug|info)[[:space:]]*\(' \
    frontend/src; then
    fail "Frontend console output was found."
fi

protected_paths_regex='/opt/(n8n|filebrowser|minio)'
if rg -n "$protected_paths_regex" scripts; then
    fail "A script references a protected production path."
fi

if find backend frontend -type d \
    \( -name node_modules -o -name .venv -o -name venv \) \
    -print -quit | rg -q .; then
    fail "A host dependency directory was found."
fi

if find . -maxdepth 3 -type f \
    \( -name .env -o -name '*.pem' -o -name '*.key' \) \
    -print -quit | rg -q .; then
    fail "A non-example environment or key file was found."
fi

unexpected_compose="$(
    find . -maxdepth 3 -type f \
        \( -iname '*compose*.yml' -o -iname '*compose*.yaml' \) \
        ! -path './docker-compose.example.yml' -print
)"
if [[ -n "$unexpected_compose" ]]; then
    printf '%s\n' "$unexpected_compose" >&2
    fail "An unexpected Compose file was found."
fi

printf '%s\n' \
    "F13 foundation acceptance passed." \
    "Safe references retained: F12 test-only n8n bridge, test assertions, documentation, and example placeholders."
