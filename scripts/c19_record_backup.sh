#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

compose_file="${C19_RECORD_COMPOSE_FILE:-docker-compose.c19-record.yml}"
project_name="${C19_RECORD_COMPOSE_PROJECT:-c19-record}"
env_file="${C19_RECORD_ENV_FILE:-.env.c19-record.production}"
output_dir="${C19_RECORD_BACKUP_DIR:-backups/c19-record}"
volume_name="${C19_RECORD_VOLUME_NAME:-c19_record_postgres_data}"

fail() {
    printf 'C19 record backup failed: %s\n' "$1" >&2
    exit 1
}

env_value() {
    local key="$1"
    awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2); exit}' "$env_file" | tr -d '\r'
}

require_unique_env_key() {
    local key="$1"
    local count
    local canonical_count
    count="$(awk -v key="$key" '$0 ~ "^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=" {count += 1} END {print count + 0}' "$env_file")"
    canonical_count="$(awk -v key="$key" '$0 ~ ("^" key "=") {count += 1} END {print count + 0}' "$env_file")"
    [[ "$count" == "1" && "$canonical_count" == "1" ]] || \
        fail "$key must appear once using the exact KEY=value form."
}

command -v docker >/dev/null 2>&1 || fail "docker is required."
if command -v docker-compose >/dev/null 2>&1; then
    compose_cli=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
    compose_cli=(docker compose)
else
    fail "Docker Compose v1 or v2 is required."
fi
command -v flock >/dev/null 2>&1 || fail "flock is required."
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required."
[[ -f "$compose_file" ]] || fail "Compose file does not exist: $compose_file"
[[ -f "$env_file" ]] || fail "Environment file does not exist: $env_file"

export C19_RECORD_ENV_FILE="$env_file"
export C19_RECORD_VOLUME_NAME="$volume_name"
compose=("${compose_cli[@]}" -p "$project_name" -f "$compose_file")
for required_key in C19_RECORD_DATASET_ID POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD; do
    require_unique_env_key "$required_key"
done
dataset_id="$(env_value C19_RECORD_DATASET_ID)"
target_db="$(env_value POSTGRES_DB)"
target_user="$(env_value POSTGRES_USER)"
target_password="$(env_value POSTGRES_PASSWORD)"
[[ "$dataset_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$ ]] || \
    fail "C19_RECORD_DATASET_ID is missing or invalid."
[[ "$target_db" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || \
    fail "POSTGRES_DB is missing or invalid."
[[ "$target_user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || \
    fail "POSTGRES_USER is missing or invalid."
[[ -n "$target_password" && "${target_password^^}" != *CHANGE-ME* ]] || \
    fail "POSTGRES_PASSWORD is missing or still contains a deployment placeholder."
[[ "$volume_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || \
    fail "C19_RECORD_VOLUME_NAME is invalid."
export C19_RECORD_DATASET_ID="$dataset_id"

volume_dataset_id="$(
    docker volume inspect --format \
        '{{index .Labels "com.barong.c19.dataset-id"}}' \
        "$volume_name"
)" || fail "The confirmed C19 record volume does not exist."
[[ "$volume_dataset_id" == "$dataset_id" ]] || \
    fail "The C19 record volume dataset label does not match C19_RECORD_DATASET_ID."

postgres_container="$("${compose[@]}" ps -q c19-record-postgres 2>/dev/null || true)"
[[ -n "$postgres_container" ]] || \
    fail "The C19 record PostgreSQL container does not exist for project $project_name."
mount_identity="$(
    docker inspect --format \
        '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{printf "%s\t%s" .Type .Name}}{{end}}{{end}}' \
        "$postgres_container"
)" || fail "Could not inspect the C19 record PostgreSQL data mount."
IFS=$'\t' read -r mount_type mounted_volume <<<"$mount_identity"
[[ "$mount_type" == "volume" && "$mounted_volume" == "$volume_name" ]] || \
    fail "The running PostgreSQL container is not attached to the confirmed C19_RECORD_VOLUME_NAME."

lock_dir="${C19_RECORD_LOCK_DIR:-${repo_root}/backups/c19-record/.locks}"
[[ ! -L "$lock_dir" ]] || fail "C19_RECORD_LOCK_DIR must not be a symbolic link."
mkdir -p "$lock_dir"
chmod 700 "$lock_dir"
lock_file="${lock_dir}/${volume_name}.lock"
[[ ! -L "$lock_file" ]] || fail "The C19 record lock file must not be a symbolic link."
exec 9>"$lock_file"
chmod 600 "$lock_file"
flock -n 9 || fail "Another backup or restore is already using volume $volume_name."

"${compose[@]}" exec -T c19-record-postgres sh -ec \
    'pg_isready --quiet --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
    || fail "C19 record PostgreSQL is not ready."
locked_container="$("${compose[@]}" ps -q c19-record-postgres 2>/dev/null || true)"
[[ "$locked_container" == "$postgres_container" ]] || \
    fail "The C19 record PostgreSQL container changed while acquiring the backup lock."
runtime_identity="$(
    "${compose[@]}" exec -T c19-record-postgres sh -ec \
        'printf "%s\t%s\t%s" "$POSTGRES_DB" "$POSTGRES_USER" "$C19_RECORD_DATASET_ID"'
)" || fail "Could not read the running C19 record PostgreSQL identity."
IFS=$'\t' read -r runtime_db runtime_user runtime_dataset_id <<<"$runtime_identity"
[[ "$runtime_db" == "$target_db" \
    && "$runtime_user" == "$target_user" \
    && "$runtime_dataset_id" == "$dataset_id" ]] || \
    fail "The running PostgreSQL identity does not match the confirmed env file."

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$output_dir"
archive="$output_dir/c19_records_${timestamp}.dump"
metadata="$archive.metadata"

revision="$(
    "${compose[@]}" exec -T c19-record-postgres sh -ec \
        'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --tuples-only --no-align --command="select version_num from alembic_version limit 1"'
)"
[[ -n "$revision" ]] || fail "Could not read the C19 record Alembic revision."

umask 077
"${compose[@]}" exec -T c19-record-postgres sh -ec \
    'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --compress=9 --no-owner --no-privileges' \
    >"$archive"

archive_sha256="$(sha256sum "$archive" | awk '{print $1}')"
cat >"$metadata" <<EOF
created_at=${timestamp}
source_dataset_id=${dataset_id}
alembic_revision=${revision}
format=pg_dump_custom
archive_sha256=${archive_sha256}
EOF
chmod 600 "$archive" "$metadata"

printf 'C19 record backup completed\n'
printf 'archive: %s\n' "$archive"
printf 'metadata: %s\n' "$metadata"
printf 'alembic_revision: %s\n' "$revision"
printf 'source_dataset_id: %s\n' "$dataset_id"
printf 'archive_sha256: %s\n' "$archive_sha256"
