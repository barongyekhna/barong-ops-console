#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

release_script="./scripts/safe_compose_release.sh"

fail() {
    printf 'Safe release plan check failed: %s\n' "$1" >&2
    exit 1
}

require_contains() {
    local haystack="$1"
    local needle="$2"
    local message="$3"

    [[ "$haystack" == *"$needle"* ]] || fail "$message"
}

require_no_match() {
    local pattern="$1"
    local message="$2"

    if grep -Eq "$pattern" "$release_script"; then
        fail "$message"
    fi
}

require_match() {
    local pattern="$1"
    local message="$2"

    if ! grep -Eq "$pattern" "$release_script"; then
        fail "$message"
    fi
}

require_all_compose_lines_have_project() {
    local line

    while IFS= read -r line; do
        if [[ "$line" != *"docker-compose -p"* ]]; then
            fail "every docker-compose reference must include an explicit project name: $line"
        fi
    done < <(grep -n 'docker-compose[[:space:]]' "$release_script" || true)
}

run_dry_run() {
    local target_env="$1"
    local target_service="$2"

    "$release_script" --env "$target_env" --service "$target_service" --dry-run
}

[[ -f "$release_script" ]] || fail "$release_script does not exist."
[[ -x "$release_script" ]] || fail "$release_script is not executable."

require_no_match 'docker-compose[[:space:]].*down' \
    "safe release script must not call docker-compose down."
require_no_match 'docker[[:space:]]+stop([[:space:]]|$)' \
    "safe release script must not call docker stop."
require_no_match 'docker[[:space:]]+restart([[:space:]]|$)' \
    "safe release script must not call docker restart."

require_match 'postgres.*not an allowed release target|not an allowed release target.*postgres' \
    "safe release script must explicitly reject postgres targets."
require_match 'CONFIRM_SAFE_RELEASE' \
    "safe release script must require CONFIRM_SAFE_RELEASE."
require_match 'CONFIRM_PRODUCTION_RELEASE' \
    "safe release script must require CONFIRM_PRODUCTION_RELEASE."
require_match 'docker-compose[[:space:]]+-p[[:space:]]+"\$project_name"[[:space:]]+-f[[:space:]]+"\$compose_file"' \
    "safe release script must call docker-compose with explicit project name and compose file."
require_all_compose_lines_have_project

staging_backend_output="$(run_dry_run staging backend)"
require_contains "$staging_backend_output" "mapping: staging/backend" \
    "dry-run is missing staging/backend mapping."
require_contains "$staging_backend_output" "project name: barong-ops-console-staging" \
    "dry-run is missing staging project name."
require_contains "$staging_backend_output" "compose file: docker-compose.staging.yml" \
    "dry-run is missing staging compose file."
require_contains "$staging_backend_output" "compose service: console_staging_backend" \
    "dry-run is missing staging backend service."
require_contains "$staging_backend_output" \
    "container name: barong-ops-console-staging_console_staging_backend_1" \
    "dry-run is missing staging backend container."
require_contains "$staging_backend_output" "health check URL: http://127.0.0.1:8100/health" \
    "dry-run is missing staging backend health URL."

staging_frontend_output="$(run_dry_run staging frontend)"
require_contains "$staging_frontend_output" "mapping: staging/frontend" \
    "dry-run is missing staging/frontend mapping."
require_contains "$staging_frontend_output" "compose service: console_staging_frontend" \
    "dry-run is missing staging frontend service."
require_contains "$staging_frontend_output" \
    "container name: barong-ops-console-staging_console_staging_frontend_1" \
    "dry-run is missing staging frontend container."
require_contains "$staging_frontend_output" "health check URL: http://127.0.0.1:3100/login" \
    "dry-run is missing staging frontend health URL."

production_backend_output="$(run_dry_run production backend)"
require_contains "$production_backend_output" "mapping: production/backend" \
    "dry-run is missing production/backend mapping."
require_contains "$production_backend_output" "project name: barong-ops-console-prod" \
    "dry-run is missing production project name."
require_contains "$production_backend_output" "compose file: docker-compose.production.yml" \
    "dry-run is missing production compose file."
require_contains "$production_backend_output" "compose service: console_backend" \
    "dry-run is missing production backend service."
require_contains "$production_backend_output" \
    "container name: barong-ops-console-prod_console_backend_1" \
    "dry-run is missing production backend container."
require_contains "$production_backend_output" "health check URL: http://127.0.0.1:8000/health" \
    "dry-run is missing production backend health URL."

production_frontend_output="$(run_dry_run production frontend)"
require_contains "$production_frontend_output" "mapping: production/frontend" \
    "dry-run is missing production/frontend mapping."
require_contains "$production_frontend_output" "compose service: console_frontend" \
    "dry-run is missing production frontend service."
require_contains "$production_frontend_output" \
    "container name: barong-ops-console-prod_console_frontend_1" \
    "dry-run is missing production frontend container."
require_contains "$production_frontend_output" "health check URL: https://ops.barongyekhna.com/login" \
    "dry-run is missing production frontend health URL."

postgres_output="$("$release_script" --env staging --service postgres --dry-run 2>&1 || true)"
require_contains "$postgres_output" "postgres is not an allowed release target" \
    "postgres target rejection did not appear in dry-run output."

printf '%s\n' "Safe release plan check passed."
