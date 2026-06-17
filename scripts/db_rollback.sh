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
rollback_mode="restore-latest"
database_url="${DATABASE_URL:-}"
backup_dir="${BARONG_BACKUP_DIR:-backups/postgres}"
archive=""
downgrade_revision="head-1"
expected_revision="${EXPECTED_SCHEMA_REVISION:-}"
health_url=""
expected_app_version="${EXPECTED_APP_VERSION:-}"

fail() {
    printf 'DB rollback failed: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/db_rollback.sh --mode restore-latest --database-url postgresql://... [--dry-run]
  CONFIRM_DB_ROLLBACK=yes ./scripts/db_rollback.sh --mode restore-archive --archive backup.dump --database-url postgresql://... --execute
  CONFIRM_DB_ROLLBACK=yes ./scripts/db_rollback.sh --mode alembic-downgrade --revision head-1 --database-url postgresql://... --execute

Modes:
  restore-latest      restore the newest pg_dump archive from --backup-dir
  restore-archive     restore the explicit --archive
  alembic-downgrade   run python -m alembic downgrade REVISION

Default mode is dry-run. Real DB rollback requires --execute and
CONFIRM_DB_ROLLBACK=yes.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            [[ $# -ge 2 ]] || fail "--mode requires a value."
            rollback_mode="$2"
            shift 2
            ;;
        --database-url)
            [[ $# -ge 2 ]] || fail "--database-url requires a value."
            database_url="$2"
            shift 2
            ;;
        --backup-dir)
            [[ $# -ge 2 ]] || fail "--backup-dir requires a value."
            backup_dir="$2"
            shift 2
            ;;
        --archive)
            [[ $# -ge 2 ]] || fail "--archive requires a value."
            archive="$2"
            shift 2
            ;;
        --revision)
            [[ $# -ge 2 ]] || fail "--revision requires a value."
            downgrade_revision="$2"
            shift 2
            ;;
        --expected-revision)
            [[ $# -ge 2 ]] || fail "--expected-revision requires a value."
            expected_revision="$2"
            shift 2
            ;;
        --expected-app-version)
            [[ $# -ge 2 ]] || fail "--expected-app-version requires a value."
            expected_app_version="$2"
            shift 2
            ;;
        --health-url)
            [[ $# -ge 2 ]] || fail "--health-url requires a value."
            health_url="$2"
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

case "$rollback_mode" in
    restore-latest|restore-archive|alembic-downgrade) ;;
    *) fail "Unsupported rollback mode: $rollback_mode" ;;
esac

printf 'DB rollback plan\n'
printf 'mode: %s\n' "$mode"
printf 'rollback_mode: %s\n' "$rollback_mode"
printf 'backup_dir: %s\n' "$backup_dir"
printf 'archive: %s\n' "${archive:-not_set}"
printf 'downgrade_revision: %s\n' "$downgrade_revision"
printf 'expected_revision: %s\n' "${expected_revision:-not_set}"

if [[ "$mode" == "execute" ]]; then
    [[ "${CONFIRM_DB_ROLLBACK:-}" == "yes" ]] ||
        fail "Set CONFIRM_DB_ROLLBACK=yes to execute a DB rollback."
fi

case "$rollback_mode" in
    restore-latest)
        restore_args=(--latest --backup-dir "$backup_dir")
        [[ -n "$expected_revision" ]] &&
            restore_args+=(--expected-revision "$expected_revision")
        if [[ "$mode" == "execute" ]]; then
            CONFIRM_DB_RESTORE=yes ./scripts/pg_restore_db.sh \
                "${restore_args[@]}" \
                --database-url "$database_url" \
                --execute
        else
            ./scripts/pg_restore_db.sh \
                "${restore_args[@]}" \
                --database-url "${database_url:-postgresql://dry-run}" \
                --dry-run
        fi
        ;;
    restore-archive)
        [[ -n "$archive" ]] || fail "--archive is required for restore-archive."
        restore_args=(--archive "$archive")
        [[ -n "$expected_revision" ]] &&
            restore_args+=(--expected-revision "$expected_revision")
        if [[ "$mode" == "execute" ]]; then
            CONFIRM_DB_RESTORE=yes ./scripts/pg_restore_db.sh \
                "${restore_args[@]}" \
                --database-url "$database_url" \
                --execute
        else
            ./scripts/pg_restore_db.sh \
                "${restore_args[@]}" \
                --database-url "${database_url:-postgresql://dry-run}" \
                --dry-run
        fi
        ;;
    alembic-downgrade)
        [[ -n "$database_url" || "$mode" == "dry-run" ]] ||
            fail "DATABASE_URL or --database-url is required."
        if [[ "$mode" == "execute" ]]; then
            DATABASE_URL="$database_url" "$python_bin" -m alembic \
                -c backend/alembic.ini downgrade "$downgrade_revision"
        else
            printf 'would run: DATABASE_URL=... %s -m alembic -c backend/alembic.ini downgrade %s\n' "$python_bin" "$downgrade_revision"
        fi
        ;;
esac

consistency_args=()
[[ -n "$database_url" ]] && consistency_args+=(--database-url "$database_url")
[[ -n "$health_url" ]] && consistency_args+=(--health-url "$health_url")
[[ -n "$expected_app_version" ]] &&
    consistency_args+=(--expected-app-version "$expected_app_version")
[[ -n "$expected_revision" ]] &&
    consistency_args+=(--expected-schema-revision "$expected_revision")

if [[ "$mode" == "execute" ]]; then
    "$python_bin" scripts/check_release_consistency.py "${consistency_args[@]}"
else
    printf 'would run: %s scripts/check_release_consistency.py' "$python_bin"
    printf ' %q' "${consistency_args[@]}"
    printf '\n'
fi
