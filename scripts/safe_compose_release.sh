#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

mode="dry-run"
target_env=""
target_service=""

fail() {
    printf 'Safe compose release failed: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/safe_compose_release.sh --env staging --service backend [--dry-run]
  ./scripts/safe_compose_release.sh --env production --service frontend [--dry-run]
  CONFIRM_SAFE_RELEASE=yes ./scripts/safe_compose_release.sh --env staging --service backend --execute
  CONFIRM_SAFE_RELEASE=yes CONFIRM_PRODUCTION_RELEASE=yes ./scripts/safe_compose_release.sh --env production --service frontend --execute

Targets:
  env:     staging | production
  service: backend | frontend

Default mode is dry-run. Real release requires --execute plus confirmation
environment variables.
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
        fail "postgres is not an allowed release target."
        ;;
    *)
        fail "Unsupported service '$target_service'. Use backend or frontend."
        ;;
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
    *)
        fail "Unsupported target mapping: $target_env/$target_service."
        ;;
esac

[[ -n "$project_name" ]] || fail "Project name is required."
[[ -n "$compose_file" ]] || fail "Compose file is required."
[[ -n "$compose_service" ]] || fail "Compose service is required."
[[ -n "$container_name" ]] || fail "Container name is required."
[[ -n "$health_url" ]] || fail "Health check URL is required."
[[ -f "$compose_file" ]] || fail "Compose file does not exist: $compose_file."

print_plan() {
    printf '%s\n' "Safe compose release plan"
    printf 'mode: %s\n' "$mode"
    printf 'mapping: %s/%s\n' "$target_env" "$target_service"
    printf 'target env: %s\n' "$target_env"
    printf 'target service: %s\n' "$target_service"
    printf 'compose file: %s\n' "$compose_file"
    printf 'project name: %s\n' "$project_name"
    printf 'compose service: %s\n' "$compose_service"
    printf 'container name: %s\n' "$container_name"
    printf 'health check URL: %s\n' "$health_url"
}

print_dry_run_steps() {
    local rollback_tag

    rollback_tag="${project_name}_${compose_service}:rollback-YYYYmmddHHMMSS"

    printf '\n%s\n' "Dry-run only. No containers will be changed."
    printf 'would run pre smoke check: %s\n' "$smoke_script"
    printf 'would build image: docker-compose -p %s -f %s build %s\n' \
        "$project_name" "$compose_file" "$compose_service"
    printf 'would inspect current image: docker inspect --format {{.Image}} %s\n' \
        "$container_name"
    printf 'would tag rollback image: docker tag CURRENT_IMAGE %s\n' \
        "$rollback_tag"
    printf 'would remove only target container: docker container rm --force %s\n' \
        "$container_name"
    printf 'would create target service: docker-compose -p %s -f %s up -d --no-deps --no-build %s\n' \
        "$project_name" "$compose_file" "$compose_service"
    printf 'would wait for health: %s\n' "$health_url"
    printf 'would run post smoke check: %s\n' "$smoke_script"
}

wait_for_health() {
    local attempt
    local max_attempts=30

    require_command curl

    for attempt in $(seq 1 "$max_attempts"); do
        if curl --fail --silent --show-error --output /dev/null \
            --max-time 10 "$health_url"
        then
            printf 'Health check passed: %s\n' "$health_url"
            return 0
        fi

        printf 'Health check not ready yet: attempt %s/%s\n' \
            "$attempt" "$max_attempts"
        sleep 2
    done

    fail "Health check did not pass: $health_url"
}

run_release() {
    local current_image
    local rollback_tag
    local timestamp

    require_command docker
    require_command docker-compose
    require_command curl

    [[ "${CONFIRM_SAFE_RELEASE:-}" == "yes" ]] ||
        fail "Set CONFIRM_SAFE_RELEASE=yes to execute a release."

    if [[ "$target_env" == "production" ]]; then
        [[ "${CONFIRM_PRODUCTION_RELEASE:-}" == "yes" ]] ||
            fail "Set CONFIRM_PRODUCTION_RELEASE=yes for production."
    fi

    timestamp="$(date -u +%Y%m%d%H%M%S)"
    rollback_tag="${project_name}_${compose_service}:rollback-${timestamp}"

    printf '\n%s\n' "Running pre smoke check..."
    "$smoke_script"

    printf '\n%s\n' "Building target service image..."
    docker-compose -p "$project_name" -f "$compose_file" build "$compose_service"

    printf '\n%s\n' "Tagging current running image for rollback..."
    current_image="$(docker inspect --format '{{.Image}}' "$container_name")" ||
        fail "Could not inspect current container image for $container_name."
    [[ -n "$current_image" ]] ||
        fail "Current image for $container_name is empty."
    docker tag "$current_image" "$rollback_tag"
    printf 'Rollback tag: %s\n' "$rollback_tag"

    printf '\n%s\n' "Removing only the target container..."
    docker container rm --force "$container_name"

    printf '\n%s\n' "Creating target service with Compose v1..."
    docker-compose -p "$project_name" -f "$compose_file" \
        up -d --no-deps --no-build "$compose_service"

    printf '\n%s\n' "Waiting for target health..."
    wait_for_health

    printf '\n%s\n' "Running post smoke check..."
    "$smoke_script"

    printf '\n%s\n' "Safe compose release completed."
}

print_plan

if [[ "$mode" == "dry-run" ]]; then
    print_dry_run_steps
    exit 0
fi

run_release
