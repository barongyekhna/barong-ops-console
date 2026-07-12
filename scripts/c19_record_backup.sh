#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

compose_file="${C19_RECORD_COMPOSE_FILE:-docker-compose.c19-record.yml}"
project_name="${C19_RECORD_COMPOSE_PROJECT:-c19-record}"
env_file="${C19_RECORD_ENV_FILE:-.env.c19-record.production}"
output_dir="${C19_RECORD_BACKUP_DIR:-backups/c19-record}"
volume_name="${C19_RECORD_VOLUME_NAME:-c19_record_postgres_data}"
required_revision="c19_record_20260712_04"
required_tables=(
    alembic_version
    chat_records
    record_asset_coordination
    record_asset_deletion_outbox
    record_retention_operations
    record_retention_batches
)
required_column_identities=(
    "record_asset_coordination:asset_id"
    "record_asset_coordination:created_at"
    "record_asset_deletion_outbox:id"
    "record_asset_deletion_outbox:asset_id"
    "record_asset_deletion_outbox:record_id"
    "record_asset_deletion_outbox:conversation_id"
    "record_asset_deletion_outbox:retention_operation_id"
    "record_asset_deletion_outbox:state"
    "record_asset_deletion_outbox:attempt_count"
    "record_asset_deletion_outbox:created_at"
    "record_asset_deletion_outbox:last_attempt_at"
    "record_asset_deletion_outbox:authorized_at"
    "record_asset_deletion_outbox:lease_owner"
    "record_asset_deletion_outbox:lease_until"
    "record_asset_deletion_outbox:outcome"
    "record_asset_deletion_outbox:completed_at"
    "record_retention_operations:operation_id"
    "record_retention_operations:requested_by_user_id"
    "record_retention_operations:reason"
    "record_retention_operations:delete_before"
    "record_retention_operations:conversation_id"
    "record_retention_operations:approved_maximum_records"
    "record_retention_operations:approved_maximum_asset_jobs"
    "record_retention_operations:affected_count"
    "record_retention_operations:asset_jobs_enqueued_count"
    "record_retention_operations:asset_jobs_completed_count"
    "record_retention_operations:next_batch_ordinal"
    "record_retention_operations:created_at"
    "record_retention_operations:updated_at"
    "record_retention_operations:completed_at"
    "record_retention_batches:operation_id"
    "record_retention_batches:batch_ordinal"
    "record_retention_batches:maximum_records"
    "record_retention_batches:affected_count"
    "record_retention_batches:cumulative_affected_count"
    "record_retention_batches:operation_complete"
    "record_retention_batches:completed_at"
)
required_constraint_identities=(
    "record_asset_coordination:pk_record_asset_coordination:p"
    "record_asset_deletion_outbox:pk_record_asset_deletion_outbox:p"
    "record_retention_operations:pk_record_retention_operations:p"
    "record_retention_batches:pk_record_retention_batches:p"
    "record_asset_deletion_outbox:fk_record_asset_deletion_outbox_retention_operation_id_record_retention_operations:f"
    "record_retention_batches:fk_record_retention_batches_operation_id_record_retention_operations:f"
    "record_asset_deletion_outbox:uq_record_asset_deletion_outbox_record_asset:u"
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_attempt_count_nonnegative:c"
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_state_supported:c"
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_outcome_supported:c"
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_lease_pair_consistent:c"
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_completion_consistent:c"
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_authorization_consistent:c"
    "record_retention_operations:ck_record_retention_operations_approved_maximum_supported:c"
    "record_retention_operations:ck_record_retention_operations_approved_asset_maximum_supported:c"
    "record_retention_operations:ck_record_retention_operations_asset_jobs_enqueued_within_maximum:c"
    "record_retention_operations:ck_record_retention_operations_asset_jobs_completed_within_enqueued:c"
    "record_retention_operations:ck_record_retention_operations_affected_count_nonnegative:c"
    "record_retention_operations:ck_record_retention_operations_affected_within_approved_maximum:c"
    "record_retention_operations:ck_record_retention_operations_next_batch_ordinal_nonnegative:c"
    "record_retention_batches:ck_record_retention_batches_batch_ordinal_nonnegative:c"
    "record_retention_batches:ck_record_retention_batches_maximum_records_supported:c"
    "record_retention_batches:ck_record_retention_batches_affected_within_batch_maximum:c"
    "record_retention_batches:ck_record_retention_batches_cumulative_count_consistent:c"
)
required_foreign_key_identities=(
    "record_asset_deletion_outbox:fk_record_asset_deletion_outbox_retention_operation_id_record_retention_operations:retention_operation_id:record_retention_operations:operation_id:r"
    "record_retention_batches:fk_record_retention_batches_operation_id_record_retention_operations:operation_id:record_retention_operations:operation_id:r"
)
required_index_identities=(
    "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_state_created"
    "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_retention_operation"
    "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_asset_state"
    "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_lease_until"
    "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_authorized_at"
    "record_retention_operations:ix_record_retention_operations_completed_at"
)

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
[[ ! -L "$output_dir" ]] || fail "Backup output directory must not be a symbolic link."
mkdir -p "$output_dir"
chmod 700 "$output_dir"
archive="$output_dir/c19_records_${timestamp}.dump"
metadata="$archive.metadata"
[[ ! -e "$archive" && ! -e "$metadata" ]] || \
    fail "Timestamped record backup output already exists."

revision="$(
    "${compose[@]}" exec -T c19-record-postgres sh -ec \
        'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --tuples-only --no-align --command="select version_num from alembic_version limit 1"'
)"
[[ -n "$revision" ]] || fail "Could not read the C19 record Alembic revision."
[[ "$revision" == "$required_revision" ]] || \
    fail "C19 record backup requires Alembic revision $required_revision."
for table_name in "${required_tables[@]}"; do
    table_exists="$(
        "${compose[@]}" exec -T c19-record-postgres psql \
            --username="$target_user" \
            --dbname="$target_db" \
            --tuples-only \
            --no-align \
            --set=ON_ERROR_STOP=1 \
            --command="select (to_regclass('public.${table_name}') is not null)::text"
    )"
    [[ "$table_exists" == true ]] || \
        fail "C19 record backup source is missing required table $table_name."
done
column_rows="$(
    "${compose[@]}" exec -T c19-record-postgres psql \
        --username="$target_user" \
        --dbname="$target_db" \
        --tuples-only \
        --no-align \
        --set=ON_ERROR_STOP=1 \
        --command="select table_name || ':' || column_name from information_schema.columns where table_schema = 'public' and table_name in ('record_asset_coordination','record_asset_deletion_outbox','record_retention_operations','record_retention_batches') order by table_name, ordinal_position"
)" || fail "Could not validate the C19 Record v4 source columns."
for column_identity in "${required_column_identities[@]}"; do
    grep -Fxq "$column_identity" <<<"$column_rows" || \
        fail "C19 Record v4 backup source is missing required column $column_identity."
done
constraint_rows="$(
    "${compose[@]}" exec -T c19-record-postgres psql \
        --username="$target_user" \
        --dbname="$target_db" \
        --tuples-only \
        --no-align \
        --set=ON_ERROR_STOP=1 \
        --command="select table_record.relname || ':' || constraint_record.conname || ':' || constraint_record.contype from pg_constraint as constraint_record join pg_class as table_record on table_record.oid = constraint_record.conrelid join pg_namespace as schema_record on schema_record.oid = table_record.relnamespace where schema_record.nspname = 'public' and table_record.relname in ('record_asset_coordination','record_asset_deletion_outbox','record_retention_operations','record_retention_batches') and constraint_record.convalidated order by table_record.relname, constraint_record.conname"
)" || fail "Could not validate the C19 Record v4 source constraints."
for constraint_identity in "${required_constraint_identities[@]}"; do
    grep -Fxq "$constraint_identity" <<<"$constraint_rows" || \
        fail "C19 Record v4 backup source is missing validated constraint $constraint_identity."
done
foreign_key_rows="$(
    "${compose[@]}" exec -T c19-record-postgres psql \
        --username="$target_user" \
        --dbname="$target_db" \
        --tuples-only \
        --no-align \
        --set=ON_ERROR_STOP=1 \
        --command="select child_table.relname || ':' || constraint_record.conname || ':' || child_column.attname || ':' || parent_table.relname || ':' || parent_column.attname || ':' || constraint_record.confdeltype from pg_constraint as constraint_record join pg_class as child_table on child_table.oid = constraint_record.conrelid join pg_class as parent_table on parent_table.oid = constraint_record.confrelid join pg_namespace as schema_record on schema_record.oid = child_table.relnamespace join pg_attribute as child_column on child_column.attrelid = child_table.oid and child_column.attnum = constraint_record.conkey[1] join pg_attribute as parent_column on parent_column.attrelid = parent_table.oid and parent_column.attnum = constraint_record.confkey[1] where schema_record.nspname = 'public' and constraint_record.contype = 'f' and constraint_record.convalidated and array_length(constraint_record.conkey, 1) = 1 and child_table.relname in ('record_asset_deletion_outbox','record_retention_batches') order by child_table.relname, constraint_record.conname"
)" || fail "Could not validate the C19 Record v4 source foreign keys."
for foreign_key_identity in "${required_foreign_key_identities[@]}"; do
    grep -Fxq "$foreign_key_identity" <<<"$foreign_key_rows" || \
        fail "C19 Record v4 backup source has an invalid foreign key $foreign_key_identity."
done
index_rows="$(
    "${compose[@]}" exec -T c19-record-postgres psql \
        --username="$target_user" \
        --dbname="$target_db" \
        --tuples-only \
        --no-align \
        --set=ON_ERROR_STOP=1 \
        --command="select table_record.relname || ':' || index_record.relname from pg_index as index_state join pg_class as index_record on index_record.oid = index_state.indexrelid join pg_class as table_record on table_record.oid = index_state.indrelid join pg_namespace as schema_record on schema_record.oid = table_record.relnamespace where schema_record.nspname = 'public' and table_record.relname in ('record_asset_deletion_outbox','record_retention_operations') and index_state.indisvalid and index_state.indisready order by table_record.relname, index_record.relname"
)" || fail "Could not validate the C19 Record v4 source indexes."
for index_identity in "${required_index_identities[@]}"; do
    grep -Fxq "$index_identity" <<<"$index_rows" || \
        fail "C19 Record v4 backup source is missing ready index $index_identity."
done

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
