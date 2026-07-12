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
dataset_id="${BARONG_BACKUP_DATASET_ID:-}"
mode="dry-run"

fail() {
    printf 'Postgres backup failed: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/pg_backup.sh --dry-run --dataset-id DATASET --database-url postgresql+psycopg://...
  CONFIRM_BARONG_BACKUP=<printed-value> ./scripts/pg_backup.sh --execute --dataset-id DATASET --database-url postgresql+psycopg://...

Creates a timestamped full PostgreSQL custom-format archive with pg_dump -Fc
and a mode-0600 sidecar containing its SHA-256 and schema revision. Execution
is fail-closed behind a dataset-scoped confirmation and an exclusive lock.
USAGE
}

redact_url() {
    printf '%s' "$1" | "$python_bin" -c '
import sys
from urllib.parse import urlsplit

value = urlsplit(sys.stdin.read())
host = value.hostname or "invalid-host"
if ":" in host:
    host = f"[{host}]"
port = f":{value.port}" if value.port else ""
database = value.path.lstrip("/")
print(f"{value.scheme}://[redacted]@{host}{port}/{database}")
'
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
        --dataset-id)
            [[ $# -ge 2 ]] || fail "--dataset-id requires a value."
            dataset_id="$2"
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

[[ -n "$database_url" ]] || fail "DATABASE_URL or --database-url is required."
if [[ "$mode" == "execute" ]]; then
    [[ "$dataset_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$ ]] || \
        fail "BARONG_BACKUP_DATASET_ID or --dataset-id is required and invalid."
fi

# Barong uses SQLAlchemy driver-qualified URLs such as
# postgresql+psycopg://....  libpq tools accept the same authority/path/query
# only after the driver suffix is removed from the scheme.
libpq_database_url="$(
    printf '%s' "$database_url" | "$python_bin" -c '
import sys
from urllib.parse import urlsplit, urlunsplit

value = urlsplit(sys.stdin.read())
scheme = value.scheme.split("+", 1)[0]
if scheme not in {"postgres", "postgresql"} or not value.hostname:
    raise SystemExit(1)
print(urlunsplit((scheme, value.netloc, value.path, value.query, "")))
'
)" || fail "The PostgreSQL target URL is invalid."

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${output_dir}/barong_ops_${timestamp}.dump"
metadata_file="${backup_file}.metadata"
redacted_database_url="$(redact_url "$libpq_database_url")"
database_name="$(
    printf '%s' "$libpq_database_url" | "$python_bin" -c \
        'import sys; from urllib.parse import urlsplit; value=urlsplit(sys.stdin.read()); print(value.path.lstrip("/"))'
)"
[[ "$database_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || \
    fail "The PostgreSQL database name is invalid."
database_target="$(
    printf '%s' "$libpq_database_url" | "$python_bin" -c '
import hashlib
import sys
from urllib.parse import urlsplit

value = urlsplit(sys.stdin.read())
if value.scheme not in {"postgres", "postgresql"} or not value.hostname:
    raise SystemExit(1)
identity = "|".join((value.hostname, str(value.port or 5432), value.path.lstrip("/")))
print(hashlib.sha256(identity.encode()).hexdigest()[:16])
'
)" || fail "The PostgreSQL target URL is invalid."
confirmation="${dataset_id:-dry-run-dataset}/${database_name}/${database_target}"

if [[ -z "$app_version" ]]; then
    app_version="$(
        "$python_bin" - <<'PY'
from backend.app.core.config import get_settings

print(get_settings().app_version)
PY
    )"
fi
[[ "$app_version" =~ ^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$ ]] || \
    fail "APP_VERSION or --app-version is invalid."

if [[ "$mode" == "dry-run" ]]; then
    printf 'Postgres backup plan\n'
    printf 'mode: dry-run\n'
    printf 'database_url: %s\n' "$redacted_database_url"
    printf 'output_dir: %s\n' "$output_dir"
    printf 'backup_file: %s\n' "$backup_file"
    printf 'metadata_file: %s\n' "$metadata_file"
    printf 'dataset_id: %s\n' "${dataset_id:-not_set}"
    printf 'required_confirmation: %s\n' "$confirmation"
    printf 'would run: pg_dump --format=custom --compress=9 --verbose --file %s DATABASE_URL\n' "$backup_file"
    exit 0
fi

[[ "${CONFIRM_BARONG_BACKUP:-}" == "$confirmation" ]] || \
    fail "CONFIRM_BARONG_BACKUP does not match the printed plan."

require_command pg_dump
require_command psql
require_command flock
require_command sha256sum

[[ ! -L "$output_dir" ]] || fail "Backup output directory must not be a symbolic link."
mkdir -p "$output_dir"
chmod 700 "$output_dir"
lock_dir="${BARONG_BACKUP_LOCK_DIR:-${output_dir}/.locks}"
[[ ! -L "$lock_dir" ]] || fail "Backup lock directory must not be a symbolic link."
mkdir -p "$lock_dir"
chmod 700 "$lock_dir"
lock_file="${lock_dir}/${dataset_id}.lock"
[[ ! -L "$lock_file" ]] || fail "Backup lock file must not be a symbolic link."
exec 9>"$lock_file"
chmod 600 "$lock_file"
flock -n 9 || fail "Another backup owns Barong dataset $dataset_id."
[[ ! -e "$backup_file" && ! -e "$metadata_file" ]] || \
    fail "Timestamped backup output already exists."
umask 077

alembic_revision="$(
    psql "$libpq_database_url" \
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
    "$libpq_database_url"

archive_sha256="$(sha256sum "$backup_file" | awk '{print $1}')"

cat >"$metadata_file" <<EOF
created_at=${timestamp}
source_dataset_id=${dataset_id}
app_version=${app_version}
alembic_revision=${alembic_revision}
database_url=${redacted_database_url}
format=pg_dump_custom
archive=${backup_file}
archive_sha256=${archive_sha256}
EOF
chmod 600 "$backup_file" "$metadata_file"

printf 'Postgres backup completed\n'
printf 'backup_file: %s\n' "$backup_file"
printf 'metadata_file: %s\n' "$metadata_file"
printf 'app_version: %s\n' "$app_version"
printf 'alembic_revision: %s\n' "$alembic_revision"
printf 'source_dataset_id: %s\n' "$dataset_id"
printf 'archive_sha256: %s\n' "$archive_sha256"
