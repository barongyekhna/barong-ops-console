#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

fail() {
    printf 'Production deploy file check failed: %s\n' "$1" >&2
    exit 1
}

require_file() {
    local path="$1"
    [[ -f "$path" ]] || fail "$path is missing."
}

require_file docker-compose.production.yml
require_file .env.production.example
require_file deploy/nginx/ops.barongyekhna.com.conf.template
require_file .gitignore

git check-ignore -q .env.production ||
    fail ".gitignore does not ignore .env.production."
git check-ignore -q .env.anything.local ||
    fail ".gitignore does not ignore .env.*.local."
git check-ignore -q secrets/production.key ||
    fail ".gitignore does not ignore secret material under secrets/."

rg -q '^N8N_TEST_WEBHOOK_URL=$' .env.production.example ||
    fail "N8N_TEST_WEBHOOK_URL must stay empty in .env.production.example."
rg -q '^N8N_TEST_CALLBACK_SECRET=$' .env.production.example ||
    fail "N8N_TEST_CALLBACK_SECRET must stay empty in .env.production.example."
rg -q 'server_name ops\.barongyekhna\.com;' \
    deploy/nginx/ops.barongyekhna.com.conf.template ||
    fail "Nginx template must use server_name ops.barongyekhna.com."

if [[ -e .env.production ]]; then
    fail "Refusing to read existing .env.production; move it aside before static placeholder validation."
fi

config_output="$(mktemp)"
cleanup() {
    if [[ -f .env.production ]] && cmp -s .env.production .env.production.example; then
        rm -f .env.production
    fi
    rm -f "$config_output"
}
trap cleanup EXIT

cp .env.production.example .env.production

if docker compose version >/dev/null 2>&1; then
    compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    compose=(docker-compose)
else
    fail "Docker Compose is required."
fi

"${compose[@]}" -f docker-compose.production.yml config >"$config_output"

printf '%s\n' "Production deploy file check passed."
