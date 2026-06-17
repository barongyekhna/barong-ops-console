#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

postgres_image="${BARONG_TEST_POSTGRES_IMAGE:-postgres:17.5-alpine}"
db_container="${BARONG_TEST_DB_CONTAINER:-barong-test-db-$(date +%s)-$$}"
db_user="${BARONG_TEST_DB_USER:-barong_test}"
db_password="${BARONG_TEST_DB_PASSWORD:-barong_test}"
db_name="${BARONG_TEST_DB_NAME:-barong_test_$(date +%s)_$$}"
if [[ -n "${PYTHON:-}" ]]; then
    python_bin="$PYTHON"
elif [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
else
    python_bin="python3"
fi

usage() {
    cat <<'USAGE'
Usage:
  scripts/run_backend_tests.sh unit
  scripts/run_backend_tests.sh integration
  scripts/run_backend_tests.sh all
  scripts/run_backend_tests.sh -m "unit and not slow"
  scripts/run_backend_tests.sh --marker "integration"
USAGE
}

run_pytest() {
    local marker_expr="$1"
    "$python_bin" -m pytest -c backend/pytest.ini tests/backend -m "$marker_expr"
}

assert_safe_database_url() {
    local database_url="$1"
    local lowered
    lowered="$(printf '%s' "$database_url" | tr '[:upper:]' '[:lower:]')"

    case "$lowered" in
        *production*|*prod*|*ops.barongyekhna.com*)
            echo "Refusing to run tests against a production-like DATABASE_URL." >&2
            exit 1
            ;;
    esac

    if [[ "$lowered" != *barong_test* && "$lowered" != *localhost* && "$lowered" != *127.0.0.1* ]]; then
        echo "Refusing to run tests against a non-isolated DATABASE_URL: $database_url" >&2
        exit 1
    fi
}

wait_for_db() {
    for _ in {1..60}; do
        if docker exec "$db_container" pg_isready -U "$db_user" -d "$db_name" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done

    echo "Timed out waiting for test PostgreSQL container." >&2
    exit 1
}

with_test_db() {
    local marker_expr="$1"
    local db_port

    if ! command -v docker >/dev/null 2>&1; then
        echo "Docker is required for backend integration tests." >&2
        exit 1
    fi

    cleanup() {
        docker rm -f "$db_container" >/dev/null 2>&1 || true
    }
    trap cleanup EXIT

    docker run \
        --rm \
        --detach \
        --name "$db_container" \
        -e POSTGRES_DB="$db_name" \
        -e POSTGRES_USER="$db_user" \
        -e POSTGRES_PASSWORD="$db_password" \
        -p 127.0.0.1::5432 \
        "$postgres_image" >/dev/null

    wait_for_db

    db_port="$(docker port "$db_container" 5432/tcp | sed 's/.*://')"
    export DATABASE_URL="postgresql+psycopg://${db_user}:${db_password}@127.0.0.1:${db_port}/${db_name}"
    export BARONG_TEST_DB_READY=1

    assert_safe_database_url "$DATABASE_URL"
    "$python_bin" -m alembic -c backend/alembic.ini upgrade head
    run_pytest "$marker_expr"
}

case "${1:-all}" in
    unit)
        run_pytest "unit"
        ;;
    integration)
        with_test_db "integration"
        ;;
    all)
        run_pytest "unit"
        with_test_db "integration"
        ;;
    -m|--marker)
        marker_expr="${2:-}"
        if [[ -z "$marker_expr" ]]; then
            usage >&2
            exit 2
        fi
        if [[ "$marker_expr" == *integration* ]]; then
            with_test_db "$marker_expr"
        else
            run_pytest "$marker_expr"
        fi
        ;;
    -h|--help)
        usage
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
