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
output_dir="${BARONG_BACKUP_DIR:-backups/postgres}"
app_version="${APP_VERSION:-}"
mode="execute"

fail() {
    printf 'Postgres backup failed: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/pg_backup.sh --database-url postgresql://... [--output-dir backups/postgres]
  ./scripts/pg_backup.sh --dry-run --database-url postgresql://...

Creates a timestamped full PostgreSQL custom-format archive with pg_dump -Fc
and a sidecar metadata file containing the app and Alembic schema revision.
USAGE
}

redact_url() {
    printf '%s' "$1" | sed -E 's#(postgresql(\+[^:]+)?://[^:/@]+:)[^@]+@#\1[redacted]@#'
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "$1 is required."
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --database-url)
            [[ $# -ge 2 ]] || fail "--database-url requires a value."
            database_url="$2"
            shift 2
            ;;
        --output-dir)
            [[ $# -ge 2 ]] || fail "--output-dir requires a value."
            output_dir="$2"
            shift 2
            ;;
        --app-version)
            [[ $# -ge 2 ]] || fail "--app-version requires a value."
            app_version="$2"
            shift 2
            ;;
        --dry-run)
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

[[ -n "$database_url" ]] || fail "DATABASE_URL or --database-url is required."

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${output_dir}/barong_ops_${timestamp}.dump"
metadata_file="${backup_file}.metadata"
redacted_database_url="$(redact_url "$database_url")"

if [[ -z "$app_version" ]]; then
    app_version="$(
        "$python_bin" - <<'PY'
from backend.app.core.config import get_settings

print(get_settings().app_version)
PY
    )"
fi

if [[ "$mode" == "dry-run" ]]; then
    printf 'Postgres backup plan\n'
    printf 'mode: dry-run\n'
    printf 'database_url: %s\n' "$redacted_database_url"
    printf 'output_dir: %s\n' "$output_dir"
    printf 'backup_file: %s\n' "$backup_file"
    printf 'metadata_file: %s\n' "$metadata_file"
    printf 'would run: pg_dump --format=custom --compress=9 --verbose --file %s DATABASE_URL\n' "$backup_file"
    exit 0
fi

require_command pg_dump
require_command psql

mkdir -p "$output_dir"

alembic_revision="$(
    psql "$database_url" \
        --tuples-only \
        --no-align \
        --command 'select version_num from alembic_version limit 1'
)"
[[ -n "$alembic_revision" ]] || fail "Could not read alembic_version."

pg_dump \
    --format=custom \
    --compress=9 \
    --verbose \
    --file "$backup_file" \
    "$database_url"

cat >"$metadata_file" <<EOF
created_at=${timestamp}
app_version=${app_version}
alembic_revision=${alembic_revision}
database_url=${redacted_database_url}
format=pg_dump_custom
archive=${backup_file}
EOF

printf 'Postgres backup completed\n'
printf 'backup_file: %s\n' "$backup_file"
printf 'metadata_file: %s\n' "$metadata_file"
printf 'app_version: %s\n' "$app_version"
printf 'alembic_revision: %s\n' "$alembic_revision"
