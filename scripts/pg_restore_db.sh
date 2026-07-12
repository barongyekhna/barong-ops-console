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

database_url="${DATABASE_URL:-}"
backup_dir="${BARONG_BACKUP_DIR:-backups/postgres}"
archive=""
archive_list=""
expected_revision="${EXPECTED_SCHEMA_REVISION:-}"
mode="dry-run"
validate_only="no"

required_tables=(
    alembic_version
    users
    auth_sessions
    event_streams
    anomaly_events
    ops_alerts
    ops_alert_deliveries
)

fail() {
    printf 'Postgres restore failed: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/pg_restore_db.sh --archive backups/postgres/barong_ops_YYYY.dump --database-url postgresql://... --execute
  ./scripts/pg_restore_db.sh --latest --backup-dir backups/postgres --database-url postgresql://... --dry-run
  ./scripts/pg_restore_db.sh --archive backup.dump --archive-list pg_restore.list --validate-only

Default mode is dry-run. Real restore requires --execute and
CONFIRM_DB_RESTORE=yes. The restore path validates required schema objects and
Alembic revision metadata before pg_restore, then runs migration safety checks.
USAGE
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "$1 is required."
}

metadata_value() {
    local key="$1"
    local file="$2"
    if [[ ! -f "$file" ]]; then
        return 0
    fi
    awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2); exit}' "$file"
}

latest_archive() {
    local latest
    latest="$(find "$backup_dir" -maxdepth 1 -type f -name 'barong_ops_*.dump' -print | sort | tail -n 1)"
    [[ -n "$latest" ]] || fail "No backups found in $backup_dir."
    printf '%s' "$latest"
}

archive_table_present() {
    local table_name="$1"
    local list_file="$2"
    grep -Eq "[[:space:]]TABLE([[:space:]]DATA)?[[:space:]]+public[[:space:]]+${table_name}([[:space:]]|$)" "$list_file"
}

validate_archive_schema() {
    local list_file="$1"
    local missing=()
    for table_name in "${required_tables[@]}"; do
        if ! archive_table_present "$table_name" "$list_file"; then
            missing+=("$table_name")
        fi
    done
    if [[ "${#missing[@]}" -gt 0 ]]; then
        fail "Archive is missing required tables: ${missing[*]}"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --database-url)
            [[ $# -ge 2 ]] || fail "--database-url requires a value."
            database_url="$2"
            shift 2
            ;;
        --archive)
            [[ $# -ge 2 ]] || fail "--archive requires a value."
            archive="$2"
            shift 2
            ;;
        --archive-list)
            [[ $# -ge 2 ]] || fail "--archive-list requires a value."
            archive_list="$2"
            shift 2
            ;;
        --backup-dir)
            [[ $# -ge 2 ]] || fail "--backup-dir requires a value."
            backup_dir="$2"
            shift 2
            ;;
        --expected-revision)
            [[ $# -ge 2 ]] || fail "--expected-revision requires a value."
            expected_revision="$2"
            shift 2
            ;;
        --latest)
            archive="__latest__"
            shift
            ;;
        --dry-run)
            mode="dry-run"
            shift
            ;;
        --execute)
            mode="execute"
            shift
            ;;
        --validate-only)
            validate_only="yes"
            mode="dry-run"
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

[[ -n "$archive" ]] || fail "--archive or --latest is required."
if [[ "$archive" == "__latest__" ]]; then
    if [[ "$mode" == "dry-run" && "$validate_only" == "no" ]]; then
        archive="${backup_dir}/barong_ops_LATEST.dump"
    else
        archive="$(latest_archive)"
    fi
fi

metadata_file="${archive}.metadata"
backup_revision="$(metadata_value alembic_revision "$metadata_file")"
backup_sha256="$(metadata_value archive_sha256 "$metadata_file")"
if [[ -n "$expected_revision" && -n "$backup_revision" && "$backup_revision" != "$expected_revision" ]]; then
    fail "Backup revision $backup_revision does not match expected $expected_revision."
fi
if [[ -f "$archive" ]]; then
    require_command sha256sum
    actual_sha256="$(sha256sum "$archive" | awk '{print $1}')"
    if [[ -n "$backup_sha256" && "$backup_sha256" != "$actual_sha256" ]]; then
        fail "Backup archive checksum does not match its metadata."
    fi
fi
if [[ "$mode" == "execute" && ! "$backup_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    fail "Executing a restore requires archive_sha256 in backup metadata."
fi

tmp_list=""
if [[ -n "$archive_list" ]]; then
    [[ -f "$archive_list" ]] || fail "Archive list does not exist: $archive_list"
    list_file="$archive_list"
else
    if [[ ! -f "$archive" && "$mode" == "dry-run" && "$validate_only" == "no" ]]; then
        list_file=""
    else
        [[ -f "$archive" ]] || fail "Archive does not exist: $archive"
        require_command pg_restore
        tmp_list="$(mktemp)"
        pg_restore --list "$archive" >"$tmp_list"
        list_file="$tmp_list"
    fi
fi
trap '[[ -n "${tmp_list:-}" ]] && rm -f "$tmp_list"' EXIT

if [[ -n "$list_file" ]]; then
    validate_archive_schema "$list_file"
else
    printf 'Postgres restore schema validation skipped for dry-run plan without local archive.\n'
fi

printf 'Postgres restore validation passed\n'
printf 'archive: %s\n' "$archive"
printf 'metadata_file: %s\n' "$metadata_file"
printf 'backup_revision: %s\n' "${backup_revision:-unknown}"
printf 'expected_revision: %s\n' "${expected_revision:-not_set}"

if [[ "$validate_only" == "yes" ]]; then
    exit 0
fi

[[ -n "$database_url" ]] || fail "DATABASE_URL or --database-url is required."

if [[ "$mode" == "dry-run" ]]; then
    printf 'mode: dry-run\n'
    printf 'would run: pg_restore --clean --if-exists --no-owner --no-privileges --single-transaction --dbname DATABASE_URL %s\n' "$archive"
    printf 'would run: scripts/check_migration_safety.py --database-url DATABASE_URL --app-env staging\n'
    exit 0
fi

[[ "${CONFIRM_DB_RESTORE:-}" == "yes" ]] ||
    fail "Set CONFIRM_DB_RESTORE=yes to execute a database restore."

require_command pg_restore
require_command psql

pg_restore \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    --single-transaction \
    --dbname "$database_url" \
    "$archive"

if [[ -n "$expected_revision" ]]; then
    restored_revision="$(
        psql "$database_url" \
            --tuples-only \
            --no-align \
            --command 'select version_num from alembic_version limit 1'
    )"
    [[ "$restored_revision" == "$expected_revision" ]] ||
        fail "Restored revision $restored_revision does not match expected $expected_revision."
fi

"$python_bin" scripts/check_migration_safety.py \
    --database-url "$database_url" \
    --app-env staging

printf 'Postgres restore completed\n'
