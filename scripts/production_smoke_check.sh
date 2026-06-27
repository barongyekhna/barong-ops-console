#!/usr/bin/env bash
set -euo pipefail

base_url="${1:-https://ops.barongyekhna.com}"

fail() {
    printf 'Production smoke check failed: %s\n' "$1" >&2
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

case "$base_url" in
    https://*) ;;
    *) fail "Base URL must start with https://." ;;
esac

http_url="http://${base_url#https://}"

require_command curl
require_command docker

login_status="$(
    curl --fail --silent --show-error --output /dev/null \
        --write-out '%{http_code}' --max-time 10 "$base_url/login"
)" || fail "HTTPS login check failed."
[[ "$login_status" == "200" ]] ||
    fail "HTTPS login returned $login_status, expected 200."

health_json="$(
    curl --fail --silent --show-error --max-time 10 \
        "$base_url/api/backend/health"
)" || fail "HTTPS backend health proxy check failed."
require_contains "$health_json" '"status":"ok"' \
    "Backend health JSON does not report status ok."
require_contains_any "$health_json" \
    "Backend health JSON does not identify the backend service." \
    '"service":"barong-ops-console-backend"' \
    '"service":"barong-ops-console"'

redirect_result="$(
    curl --silent --show-error --output /dev/null \
        --write-out '%{http_code} %{redirect_url}' --max-time 10 \
        "$http_url/login"
)" || fail "HTTP redirect check failed."
[[ "$redirect_result" == "301 $base_url/login" ]] ||
    fail "HTTP redirect returned '$redirect_result', expected '301 $base_url/login'."

docker_output="$(
    docker ps --filter name=console_ \
        --format '{{.Names}}|{{.Status}}|{{.Ports}}'
)" || fail "Docker ps status check failed."

require_contains "$docker_output" "_console_frontend_" \
    "console_frontend container is not listed by docker ps."
require_contains "$docker_output" "127.0.0.1:3000->3000/tcp" \
    "console_frontend is not bound to 127.0.0.1:3000."
require_contains "$docker_output" "_console_backend_" \
    "console_backend container is not listed by docker ps."
require_contains "$docker_output" "127.0.0.1:8000->8000/tcp" \
    "console_backend is not bound to 127.0.0.1:8000."
require_contains "$docker_output" "_console_postgres_" \
    "console_postgres container is not listed by docker ps."
require_contains "$docker_output" "(healthy)" \
    "console_postgres is not reported healthy by docker ps."
require_contains "$docker_output" "5432/tcp" \
    "console_postgres internal 5432/tcp port is not listed."

case "$docker_output" in
    *"0.0.0.0:5432"*|*"[::]:5432"*|*"127.0.0.1:5432"*)
        fail "console_postgres appears to expose 5432 on the host."
        ;;
esac

printf 'Production smoke check passed for %s\n' "$base_url"
