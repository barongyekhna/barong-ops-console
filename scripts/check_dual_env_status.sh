#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

production_frontend="barong-ops-console-prod_console_frontend_1"
production_backend="barong-ops-console-prod_console_backend_1"
production_postgres="barong-ops-console-prod_console_postgres_1"
staging_frontend="barong-ops-console-staging_console_staging_frontend_1"
staging_backend="barong-ops-console-staging_console_staging_backend_1"
staging_postgres="barong-ops-console-staging_console_staging_postgres_1"

fail() {
    printf 'Dual environment status check failed: %s\n' "$1" >&2
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

print_section() {
    printf '\n%s\n' "$1"
}

container_line() {
    local name="$1"

    printf '%s\n' "$docker_output" |
        awk -F'|' -v expected="$name" '
            $1 == expected {
                print
                found = 1
            }
            END {
                if (!found) {
                    exit 1
                }
            }
        '
}

require_production_container() {
    local name="$1"
    local line

    if ! line="$(container_line "$name")"; then
        fail "Production container $name is not running."
    fi

    printf '%s\n' "$line"
}

require_staging_container() {
    local name="$1"
    local line

    if ! line="$(container_line "$name")"; then
        staging_not_running
    fi

    printf '%s\n' "$line"
}

require_postgres_private() {
    local label="$1"
    local line="$2"

    require_contains "$line" "5432/tcp" \
        "$label postgres does not list its internal 5432/tcp port."

    case "$line" in
        *"->5432/tcp"*|*"0.0.0.0:5432"*|*"[::]:5432"*|*"127.0.0.1:5432"*)
            fail "$label postgres appears to expose PostgreSQL on the host."
            ;;
    esac
}

check_host_5432_not_listening() {
    local ss_output

    if ! command -v ss >/dev/null 2>&1; then
        printf '%s\n' "ss is unavailable; Docker port mapping check already passed."
        return
    fi

    if ! ss_output="$(ss -ltn 2>/dev/null)"; then
        printf '%s\n' \
            "Host port 5432 listener check skipped; Docker port mapping check already passed."
        return
    fi

    if printf '%s\n' "$ss_output" |
        awk '
            NR > 1 {
                local_address = $4
                sub(/.*:/, "", local_address)
                gsub(/[^0-9]/, "", local_address)
                if (local_address == "5432") {
                    found = 1
                }
            }
            END {
                exit found ? 0 : 1
            }
        '
    then
        fail "Host port 5432 is listening."
    fi

    printf '%s\n' "Host port 5432 is not listening."
}

require_http_200() {
    local label="$1"
    local url="$2"
    local status

    status="$(
        curl --fail --silent --show-error --output /dev/null \
            --write-out '%{http_code}' --max-time 10 "$url"
    )" || fail "$label check failed for $url."

    [[ "$status" == "200" ]] ||
        fail "$label returned $status for $url, expected 200."
}

require_health() {
    local label="$1"
    local url="$2"
    local expected_env="$3"
    local health_json

    health_json="$(
        curl --fail --silent --show-error --max-time 10 "$url"
    )" || fail "$label health check failed for $url."

    require_contains "$health_json" '"status":"ok"' \
        "$label health JSON does not report status ok."
    require_contains "$health_json" '"service":"barong-ops-console-backend"' \
        "$label health JSON does not identify the backend service."
    require_contains "$health_json" "\"environment\":\"$expected_env\"" \
        "$label health JSON does not report environment $expected_env."
}

require_command git
require_command docker
require_command curl

printf '%s\n' "Dual environment status check target: production + staging"
printf '%s\n' "Read-only check only; no env contents are read and no services are modified."

print_section "Git status"
git_status="$(git status --short --untracked-files=all)" ||
    fail "git status failed."
if [[ -z "$git_status" ]]; then
    printf '%s\n' "Git working tree is clean."
else
    printf '%s\n' "Git working tree has changes:"
    printf '%s\n' "$git_status"
fi

print_section "Env ignore rules"
git check-ignore -q .env.production ||
    fail ".env.production is not ignored by Git."
git check-ignore -q .env.staging ||
    fail ".env.staging is not ignored by Git."
printf '%s\n' ".env.production is ignored by Git."
printf '%s\n' ".env.staging is ignored by Git."

print_section "Docker container status"
docker_output="$(
    docker ps --format '{{.Names}}|{{.Status}}|{{.Ports}}'
)" || fail "Docker ps status check failed."

production_frontend_line="$(require_production_container "$production_frontend")"
production_backend_line="$(require_production_container "$production_backend")"
production_postgres_line="$(require_production_container "$production_postgres")"
staging_frontend_line="$(require_staging_container "$staging_frontend")"
staging_backend_line="$(require_staging_container "$staging_backend")"
staging_postgres_line="$(require_staging_container "$staging_postgres")"

printf '%s\n' "$production_frontend_line"
printf '%s\n' "$production_backend_line"
printf '%s\n' "$production_postgres_line"
printf '%s\n' "$staging_frontend_line"
printf '%s\n' "$staging_backend_line"
printf '%s\n' "$staging_postgres_line"

require_contains "$production_postgres_line" "(healthy)" \
    "Production postgres is not healthy."
require_contains "$staging_postgres_line" "(healthy)" \
    "Staging postgres is not healthy."

print_section "Port isolation"
require_contains "$production_frontend_line" "127.0.0.1:3000->3000/tcp" \
    "Production frontend is not bound to 127.0.0.1:3000."
require_contains "$production_backend_line" "127.0.0.1:8000->8000/tcp" \
    "Production backend is not bound to 127.0.0.1:8000."
require_contains "$staging_frontend_line" "127.0.0.1:3100->3000/tcp" \
    "Staging frontend is not bound to 127.0.0.1:3100."
require_contains "$staging_backend_line" "127.0.0.1:8100->8000/tcp" \
    "Staging backend is not bound to 127.0.0.1:8100."
require_postgres_private "Production" "$production_postgres_line"
require_postgres_private "Staging" "$staging_postgres_line"
check_host_5432_not_listening
printf '%s\n' "Production and staging host ports are isolated."
printf '%s\n' "Console Postgres containers do not expose a host PostgreSQL port."

print_section "Production smoke"
require_http_200 "Production login" "https://ops.barongyekhna.com/login"
require_health "Production backend proxy" \
    "https://ops.barongyekhna.com/api/backend/health" "production"
printf '%s\n' "Production smoke passed."

print_section "Staging smoke"
require_http_200 "Staging login" "http://127.0.0.1:3100/login"
require_health "Staging backend proxy" \
    "http://127.0.0.1:3100/api/backend/health" "staging"
require_health "Staging backend direct" \
    "http://127.0.0.1:8100/health" "staging"
printf '%s\n' "Staging smoke passed."

printf '\n%s\n' "Dual environment status check passed."
