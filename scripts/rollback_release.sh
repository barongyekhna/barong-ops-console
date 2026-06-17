#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -n "${PYTHON:-}" ]]; then
    python_bin="$PYTHON"
elif [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
else
    python_bin="python3"
fi

mode="dry-run"
target_env=""
target_service=""
rollback_image=""
database_url="${DATABASE_URL:-}"
expected_app_version="${EXPECTED_APP_VERSION:-}"
expected_schema_revision="${EXPECTED_SCHEMA_REVISION:-}"

fail() {
    printf 'Application rollback failed: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/rollback_release.sh --env production --service backend [--dry-run]
  ./scripts/rollback_release.sh --env staging --service frontend --image IMAGE [--dry-run]
  CONFIRM_APP_ROLLBACK=yes CONFIRM_PRODUCTION_ROLLBACK=yes ./scripts/rollback_release.sh --env production --service backend --execute

Restores the previous docker image by retagging a rollback-* image to the
Compose service image, recreates only the target service, then runs health and
release consistency checks.
USAGE
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "$1 is required."
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)
            [[ $# -ge 2 ]] || fail "--env requires a value."
            target_env="$2"
            shift 2
            ;;
        --service)
            [[ $# -ge 2 ]] || fail "--service requires a value."
            target_service="$2"
            shift 2
            ;;
        --image)
            [[ $# -ge 2 ]] || fail "--image requires a value."
            rollback_image="$2"
            shift 2
            ;;
        --database-url)
            [[ $# -ge 2 ]] || fail "--database-url requires a value."
            database_url="$2"
            shift 2
            ;;
        --expected-app-version)
            [[ $# -ge 2 ]] || fail "--expected-app-version requires a value."
            expected_app_version="$2"
            shift 2
            ;;
        --expected-schema-revision)
            [[ $# -ge 2 ]] || fail "--expected-schema-revision requires a value."
            expected_schema_revision="$2"
            shift 2
            ;;
        --dry-run)
            mode="dry-run"
            shift
            ;;
        --execute)
            mode="execute"
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            fail "Unknown argument: $1"
            ;;
    esac
done

[[ -n "$target_env" ]] || fail "--env is required."
[[ -n "$target_service" ]] || fail "--service is required."

case "$target_service" in
    backend|frontend) ;;
    postgres|console_postgres|console_staging_postgres)
        fail "postgres is not an application rollback target; use db_rollback.sh."
        ;;
    *) fail "Unsupported service '$target_service'. Use backend or frontend." ;;
esac

project_name=""
compose_file=""
compose_service=""
container_name=""
health_url=""
smoke_script=""

case "$target_env/$target_service" in
    staging/backend)
        project_name="barong-ops-console-staging"
        compose_file="docker-compose.staging.yml"
        compose_service="console_staging_backend"
        container_name="barong-ops-console-staging_console_staging_backend_1"
        health_url="http://127.0.0.1:8100/health"
        smoke_script="./scripts/staging_smoke_check.sh"
        ;;
    staging/frontend)
        project_name="barong-ops-console-staging"
        compose_file="docker-compose.staging.yml"
        compose_service="console_staging_frontend"
        container_name="barong-ops-console-staging_console_staging_frontend_1"
        health_url="http://127.0.0.1:3100/login"
        smoke_script="./scripts/staging_smoke_check.sh"
        ;;
    production/backend)
        project_name="barong-ops-console-prod"
        compose_file="docker-compose.production.yml"
        compose_service="console_backend"
        container_name="barong-ops-console-prod_console_backend_1"
        health_url="http://127.0.0.1:8000/health"
        smoke_script="./scripts/production_smoke_check.sh"
        ;;
    production/frontend)
        project_name="barong-ops-console-prod"
        compose_file="docker-compose.production.yml"
        compose_service="console_frontend"
        container_name="barong-ops-console-prod_console_frontend_1"
        health_url="https://ops.barongyekhna.com/login"
        smoke_script="./scripts/production_smoke_check.sh"
        ;;
    *) fail "Unsupported target mapping: $target_env/$target_service." ;;
esac

target_image="${project_name}_${compose_service}:latest"

find_latest_rollback_image() {
    require_command docker
    docker images \
        --format '{{.Repository}}:{{.Tag}}' \
        "${project_name}_${compose_service}" |
        grep ':rollback-' |
        sort |
        tail -n 1
}

wait_for_health() {
    local attempt
    require_command curl
    for attempt in $(seq 1 30); do
        if curl --fail --silent --show-error --output /dev/null --max-time 10 "$health_url"; then
            printf 'Health check passed: %s\n' "$health_url"
            return 0
        fi
        printf 'Health check not ready yet: attempt %s/30\n' "$attempt"
        sleep 2
    done
    fail "Health check did not pass: $health_url"
}

print_plan() {
    printf 'Application rollback plan\n'
    printf 'mode: %s\n' "$mode"
    printf 'target env: %s\n' "$target_env"
    printf 'target service: %s\n' "$target_service"
    printf 'compose file: %s\n' "$compose_file"
    printf 'project name: %s\n' "$project_name"
    printf 'compose service: %s\n' "$compose_service"
    printf 'container name: %s\n' "$container_name"
    printf 'rollback image: %s\n' "${rollback_image:-latest rollback-* image}"
    printf 'target image: %s\n' "$target_image"
    printf 'health check URL: %s\n' "$health_url"
    printf 'smoke script: %s\n' "$smoke_script"
}

run_consistency_check() {
    local args=()
    [[ -n "$database_url" ]] && args+=(--database-url "$database_url")
    [[ -n "$expected_app_version" ]] &&
        args+=(--expected-app-version "$expected_app_version")
    [[ -n "$expected_schema_revision" ]] &&
        args+=(--expected-schema-revision "$expected_schema_revision")
    if [[ "$target_service" == "backend" ]]; then
        args+=(--health-url "$health_url")
    fi
    "$python_bin" scripts/check_release_consistency.py "${args[@]}"
}

print_plan

if [[ "$mode" == "dry-run" ]]; then
    printf '\nDry-run only. No containers will be changed.\n'
    printf 'would resolve rollback image if --image is not supplied\n'
    printf 'would tag rollback image to: %s\n' "$target_image"
    printf 'would remove only target container: docker container rm --force %s\n' "$container_name"
    printf 'would recreate target service: docker-compose -p %s -f %s up -d --no-deps --no-build %s\n' "$project_name" "$compose_file" "$compose_service"
    printf 'would wait for health: %s\n' "$health_url"
    printf 'would run smoke script: %s\n' "$smoke_script"
    printf 'would run release consistency check\n'
    exit 0
fi

require_command docker
require_command docker-compose
require_command curl

[[ "${CONFIRM_APP_ROLLBACK:-}" == "yes" ]] ||
    fail "Set CONFIRM_APP_ROLLBACK=yes to execute application rollback."
if [[ "$target_env" == "production" ]]; then
    [[ "${CONFIRM_PRODUCTION_ROLLBACK:-}" == "yes" ]] ||
        fail "Set CONFIRM_PRODUCTION_ROLLBACK=yes for production rollback."
fi

if [[ -z "$rollback_image" ]]; then
    rollback_image="$(find_latest_rollback_image)"
fi
[[ -n "$rollback_image" ]] || fail "No rollback image found for $project_name/$compose_service."

printf '\nTagging rollback image...\n'
docker tag "$rollback_image" "$target_image"

printf '\nRemoving only target container...\n'
docker container rm --force "$container_name"

printf '\nRecreating target service...\n'
docker-compose -p "$project_name" -f "$compose_file" \
    up -d --no-deps --no-build "$compose_service"

printf '\nWaiting for health...\n'
wait_for_health

printf '\nRunning smoke check...\n'
"$smoke_script"

printf '\nRunning release consistency check...\n'
run_consistency_check

printf '\nApplication rollback completed.\n'
