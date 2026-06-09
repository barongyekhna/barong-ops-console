#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

printf '%s\n' "C02B static check only, no services started."

fail() {
    printf 'Staging deploy file check failed: %s\n' "$1" >&2
    exit 1
}

require_file() {
    local path="$1"
    [[ -f "$path" ]] || fail "$path is missing."
}

require_file docker-compose.staging.yml
require_file .env.staging.example
require_file .gitignore

git check-ignore -q .env.staging ||
    fail ".gitignore does not ignore .env.staging."
git check-ignore -q .env.production ||
    fail ".gitignore does not ignore .env.production."
git check-ignore -q .env.anything.local ||
    fail ".gitignore does not ignore .env.*.local."
git check-ignore -q secrets/staging.key ||
    fail ".gitignore does not ignore secret material under secrets/."

for service in \
    console_staging_postgres \
    console_staging_backend \
    console_staging_frontend
do
    rg -q "^  ${service}:" docker-compose.staging.yml ||
        fail "Missing staging service $service."
    [[ "$service" == *staging* ]] ||
        fail "Service $service does not include staging in its name."
done

rg -q '^  barong-ops-console-staging:$' docker-compose.staging.yml ||
    fail "Missing staging network definition."
rg -q '^    name: barong-ops-console-staging$' docker-compose.staging.yml ||
    fail "Staging network must be named barong-ops-console-staging."
rg -q '^  console_staging_postgres_data:$' docker-compose.staging.yml ||
    fail "Missing staging volume definition."
rg -q '^    name: console_staging_postgres_data$' docker-compose.staging.yml ||
    fail "Staging volume must be named console_staging_postgres_data."

env_file_count="$(rg -c '^[[:space:]]+- \.env\.staging$' \
    docker-compose.staging.yml || true)"
[[ "$env_file_count" == "3" ]] ||
    fail "Each staging service must use env_file: .env.staging."

rg -q '127\.0\.0\.1:3100:3000' docker-compose.staging.yml ||
    fail "Staging frontend must bind 127.0.0.1:3100:3000."
rg -q '127\.0\.0\.1:8100:8000' docker-compose.staging.yml ||
    fail "Staging backend must bind 127.0.0.1:8100:8000."

postgres_block="$(
    awk '
        /^  console_staging_postgres:/ { in_block = 1; next }
        /^  console_staging_backend:/ { in_block = 0 }
        in_block { print }
    ' docker-compose.staging.yml
)"
[[ "$postgres_block" != *"ports:"* ]] ||
    fail "Staging postgres must not expose a host port."

rg -q '^APP_ENV=staging$' .env.staging.example ||
    fail ".env.staging.example must set APP_ENV=staging."
rg -q '^DATABASE_URL=.*@console_staging_postgres:5432/' \
    .env.staging.example ||
    fail "Staging DATABASE_URL must point at console_staging_postgres."
rg -q '^BACKEND_API_URL=http://console_staging_backend:8000$' \
    .env.staging.example ||
    fail "Staging BACKEND_API_URL must point at console_staging_backend."
rg -q '^N8N_TEST_WEBHOOK_URL=$' .env.staging.example ||
    fail "N8N_TEST_WEBHOOK_URL must stay empty in .env.staging.example."
rg -q '^N8N_TEST_CALLBACK_SECRET=$' .env.staging.example ||
    fail "N8N_TEST_CALLBACK_SECRET must stay empty in .env.staging.example."

deployment_files=(docker-compose.staging.yml .env.staging.example)

if rg -q 'ops\.barongyekhna\.com' "${deployment_files[@]}"; then
    fail "Staging deploy files must not hard-code the production domain."
fi

if rg -q 'barong-ops-console-prod|\.env\.production|console_postgres_data' \
    "${deployment_files[@]}"
then
    fail "Staging deploy files contain production project/env/volume names."
fi

if rg -q '127\.0\.0\.1:3000:3000|127\.0\.0\.1:8000:8000' \
    docker-compose.staging.yml
then
    fail "Staging deploy files reuse production host ports."
fi

if rg -q '^N8N_TEST_WEBHOOK_URL=.' .env.staging.example; then
    fail "Staging example must not contain a webhook URL."
fi

if rg -q 'https?://[^[:space:]]*webhook' "${deployment_files[@]}"; then
    fail "Staging deploy files must not contain a webhook URL."
fi

config_dir="$(mktemp -d "${TMPDIR:-/tmp}/c02b-staging-config.XXXXXX")"
config_output="$(mktemp "${TMPDIR:-/tmp}/c02b-staging-config-output.XXXXXX")"
cleanup() {
    rm -rf "$config_dir"
    rm -f "$config_output"
}
trap cleanup EXIT

cp docker-compose.staging.yml "$config_dir/docker-compose.staging.yml"
cp .env.staging.example "$config_dir/.env.staging"

if docker compose version >/dev/null 2>&1; then
    compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    compose=(docker-compose)
else
    fail "Docker Compose is required."
fi

(
    cd "$config_dir"
    "${compose[@]}" -f docker-compose.staging.yml config >"$config_output"
)

for name in \
    console_staging_postgres \
    console_staging_backend \
    console_staging_frontend \
    barong-ops-console-staging \
    console_staging_postgres_data
do
    rg -q "$name" "$config_output" ||
        fail "Compose config does not include $name."
done

printf '%s\n' "Staging deploy file check passed."
