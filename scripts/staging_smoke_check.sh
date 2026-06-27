#!/usr/bin/env bash
set -euo pipefail

frontend_url="${1:-http://127.0.0.1:3100}"
backend_url="${2:-http://127.0.0.1:8100}"

fail() {
    printf 'Staging smoke check failed: %s\n' "$1" >&2
    exit 1
}

staging_not_running() {
    printf '%s\n' "staging is not running yet" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "$1 is required."
}

require_contains() {
    local haystack="$1"
    local needle="$2"
    local message="$3"

    [[ "$haystack" == *"$needle"* ]] || fail "$message"
}

require_contains_any() {
    local haystack="$1"
    local message="$2"
    shift 2

    local needle
    for needle in "$@"; do
        if [[ "$haystack" == *"$needle"* ]]; then
            return 0
        fi
    done

    fail "$message"
}

require_running_contains() {
    local haystack="$1"
    local needle="$2"

    [[ "$haystack" == *"$needle"* ]] || staging_not_running
}

case "$frontend_url" in
    http://127.0.0.1:3100|http://127.0.0.1:3100/) ;;
    *) fail "Frontend URL must be http://127.0.0.1:3100." ;;
esac

case "$backend_url" in
    http://127.0.0.1:8100|http://127.0.0.1:8100/) ;;
    *) fail "Backend URL must be http://127.0.0.1:8100." ;;
esac

require_command curl
require_command docker

printf '%s\n' "Staging smoke check is read-only; it does not start services."

docker_output="$(
    docker ps --filter name=staging \
        --format '{{.Names}}|{{.Status}}|{{.Ports}}'
)" || fail "Docker ps status check failed."

[[ -n "$docker_output" ]] || staging_not_running

require_running_contains "$docker_output" "console_staging_frontend"
require_running_contains "$docker_output" "127.0.0.1:3100->3000/tcp"
require_running_contains "$docker_output" "console_staging_backend"
require_running_contains "$docker_output" "127.0.0.1:8100->8000/tcp"
require_running_contains "$docker_output" "console_staging_postgres"
require_running_contains "$docker_output" "5432/tcp"

case "$docker_output" in
    *"0.0.0.0:5432"*|*"[::]:5432"*|*"127.0.0.1:5432"*)
        fail "console_staging_postgres appears to expose 5432 on the host."
        ;;
esac

login_status="$(
    curl --fail --silent --show-error --output /dev/null \
        --write-out '%{http_code}' --max-time 10 "$frontend_url/login"
)" || fail "Staging frontend login check failed."
[[ "$login_status" == "200" ]] ||
    fail "Staging frontend login returned $login_status, expected 200."

proxy_health_json="$(
    curl --fail --silent --show-error --max-time 10 \
        "$frontend_url/api/backend/health"
)" || fail "Staging frontend backend proxy health check failed."
require_contains "$proxy_health_json" '"status":"ok"' \
    "Staging backend proxy health JSON does not report status ok."
require_contains_any "$proxy_health_json" \
    "Staging backend proxy health JSON does not identify the backend service." \
    '"service":"barong-ops-console-backend"' \
    '"service":"barong-ops-console"'

backend_health_json="$(
    curl --fail --silent --show-error --max-time 10 \
        "$backend_url/health"
)" || fail "Staging backend health check failed."
require_contains "$backend_health_json" '"status":"ok"' \
    "Staging backend health JSON does not report status ok."
require_contains_any "$backend_health_json" \
    "Staging backend health JSON does not identify the backend service." \
    '"service":"barong-ops-console-backend"' \
    '"service":"barong-ops-console"'

printf '%s\n' "Staging smoke check passed."
