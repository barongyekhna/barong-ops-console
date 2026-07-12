#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

mode="dry-run"
generation_id="${C19_FULL_GENERATION_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
output_root="${C19_FULL_BACKUP_DIR:-backups/c19-full}"
barong_dataset_id="${C19_FULL_BARONG_DATASET_ID:-}"
record_dataset_id="${C19_FULL_RECORD_DATASET_ID:-}"
asset_dataset_id="${C19_FULL_ASSET_DATASET_ID:-}"
barong_app_version="${C19_FULL_BARONG_APP_VERSION:-}"
hmac_key_file="${C19_FULL_MANIFEST_HMAC_KEY_FILE:-}"
required_record_revision="c19_record_20260712_04"
required_asset_revision="c19_asset_20260712_03"

barong_project="${C19_FULL_BARONG_COMPOSE_PROJECT:-barong-ops-console}"
barong_compose_file="${C19_FULL_BARONG_COMPOSE_FILE:-docker-compose.production.yml}"
record_project="${C19_RECORD_COMPOSE_PROJECT:-c19-record}"
record_compose_file="${C19_RECORD_COMPOSE_FILE:-docker-compose.c19-record.yml}"
record_env_file="${C19_RECORD_ENV_FILE:-.env.c19-record.production}"
asset_project="${C19_ASSET_COMPOSE_PROJECT:-c19-asset}"
asset_compose_file="${C19_ASSET_COMPOSE_FILE:-docker-compose.c19-asset.yml}"
asset_env_file="${C19_ASSET_ENV_FILE:-.env.c19-asset.production}"

barong_writer_services=(
    console_backend
    r-w-worker
    r-a-worker
    k-worker
    key-health-worker
)

fail() {
    printf 'C19 full backup failed: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/c19_full_backup.sh --dry-run --generation-id ID \
    --barong-dataset-id ID --record-dataset-id ID --asset-dataset-id ID

  CONFIRM_C19_FULL_BACKUP=<printed-value> \
  C19_FULL_BARONG_APP_VERSION=... \
  C19_FULL_MANIFEST_HMAC_KEY_FILE=/secure/key \
  ./scripts/c19_full_backup.sh --execute --generation-id ID \
    --barong-dataset-id ID --record-dataset-id ID --asset-dataset-id ID

Dry-run is the default and performs no Docker or database operation. Execute
freezes all Barong database writers and the C19 Record/Asset single writers,
captures all three stores, seals an HMAC-authenticated bundle, verifies it,
then resumes only the source services that were running before the freeze.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            mode="dry-run"
            shift
            ;;
        --execute)
            mode="execute"
            shift
            ;;
        --generation-id)
            [[ $# -ge 2 ]] || fail "--generation-id requires a value."
            generation_id="$2"
            shift 2
            ;;
        --output-dir)
            [[ $# -ge 2 ]] || fail "--output-dir requires a value."
            output_root="$2"
            shift 2
            ;;
        --barong-dataset-id)
            [[ $# -ge 2 ]] || fail "--barong-dataset-id requires a value."
            barong_dataset_id="$2"
            shift 2
            ;;
        --record-dataset-id)
            [[ $# -ge 2 ]] || fail "--record-dataset-id requires a value."
            record_dataset_id="$2"
            shift 2
            ;;
        --asset-dataset-id)
            [[ $# -ge 2 ]] || fail "--asset-dataset-id requires a value."
            asset_dataset_id="$2"
            shift 2
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

for value in "$generation_id" "$barong_dataset_id" "$record_dataset_id" "$asset_dataset_id"; do
    [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$ ]] || \
        fail "Generation and dataset IDs must be explicit safe identifiers."
done
for value in "$barong_project" "$record_project" "$asset_project"; do
    [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{1,127}$ ]] || \
        fail "Compose project names must be explicit safe identifiers."
done
[[ "$barong_dataset_id" != "$record_dataset_id" \
    && "$barong_dataset_id" != "$asset_dataset_id" \
    && "$record_dataset_id" != "$asset_dataset_id" ]] || \
    fail "Barong, Record, and Asset dataset IDs must be distinct."

confirmation="BACKUP/${generation_id}/${barong_dataset_id}/${record_dataset_id}/${asset_dataset_id}/${barong_project}"
generation_dir="${output_root}/${generation_id}"
manifest="${generation_dir}/c19-full-${generation_id}.json"

printf 'C19 full backup plan\n'
printf 'mode: %s\n' "$mode"
printf 'generation_id: %s\n' "$generation_id"
printf 'barong_dataset: %s\n' "$barong_dataset_id"
printf 'record_dataset: %s\n' "$record_dataset_id"
printf 'asset_dataset: %s\n' "$asset_dataset_id"
printf 'generation_dir: %s\n' "$generation_dir"
printf 'manifest: %s\n' "$manifest"
printf 'writer_policy: freeze-all-single-writers\n'
printf 'required_confirmation: %s\n' "$confirmation"

if [[ "$mode" == "dry-run" ]]; then
    printf '%s\n' 'No containers, databases, volumes, or files were changed.'
    exit 0
fi

[[ "${CONFIRM_C19_FULL_BACKUP:-}" == "$confirmation" ]] || \
    fail "CONFIRM_C19_FULL_BACKUP does not match the printed plan."
[[ -n "$barong_app_version" ]] || \
    fail "C19_FULL_BARONG_APP_VERSION is required for execution."
[[ "$barong_app_version" =~ ^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$ ]] || \
    fail "C19_FULL_BARONG_APP_VERSION is invalid."
[[ -n "$hmac_key_file" ]] || \
    fail "C19_FULL_MANIFEST_HMAC_KEY_FILE is required for execution."
for file in \
    "$barong_compose_file" "$record_compose_file" "$record_env_file" \
    "$asset_compose_file" "$asset_env_file" "$hmac_key_file"; do
    [[ -f "$file" && ! -L "$file" ]] || fail "Required file is missing or a symlink: $file"
done
for command_name in docker flock sha256sum; do
    command -v "$command_name" >/dev/null 2>&1 || fail "$command_name is required."
done
if [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
else
    command -v python3 >/dev/null 2>&1 || fail "python3 is required."
    python_bin=python3
fi
if command -v docker-compose >/dev/null 2>&1; then
    compose_cli=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
    compose_cli=(docker compose)
else
    fail "Docker Compose v1 or v2 is required."
fi

env_value() {
    local key="$1"
    local file="$2"
    local count
    count="$(awk -v key="$key" '$0 ~ ("^" key "=") {count += 1} END {print count + 0}' "$file")"
    [[ "$count" == 1 ]] || fail "$key must appear once in $file using exact KEY=value form."
    awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2); exit}' "$file" | tr -d '\r'
}

[[ "$(env_value C19_RECORD_DATASET_ID "$record_env_file")" == "$record_dataset_id" ]] || \
    fail "Record dataset does not match its environment file."
[[ "$(env_value C19_ASSET_DATASET_ID "$asset_env_file")" == "$asset_dataset_id" ]] || \
    fail "Asset dataset does not match its environment file."

[[ ! -L "$output_root" ]] || fail "Full backup output directory must not be a symlink."
mkdir -p "$output_root"
chmod 700 "$output_root"
lock_dir="${C19_FULL_LOCK_DIR:-${output_root}/.locks}"
[[ ! -L "$lock_dir" ]] || fail "Full backup lock directory must not be a symlink."
mkdir -p "$lock_dir"
chmod 700 "$lock_dir"
lock_file="${lock_dir}/full-system.lock"
[[ ! -L "$lock_file" ]] || fail "Full backup lock file must not be a symlink."
exec 8>"$lock_file"
chmod 600 "$lock_file"
flock -n 8 || fail "Another full C19 backup or restore verification is running."
[[ ! -e "$generation_dir" ]] || fail "Generation directory already exists."
umask 077
mkdir -p "$generation_dir/barong" "$generation_dir/record" "$generation_dir/asset"
chmod 700 "$generation_dir" "$generation_dir/barong" "$generation_dir/record" "$generation_dir/asset"

barong_compose=("${compose_cli[@]}" -p "$barong_project" -f "$barong_compose_file")
export C19_RECORD_DATASET_ID="$record_dataset_id"
export C19_ASSET_DATASET_ID="$asset_dataset_id"
record_compose=("${compose_cli[@]}" -p "$record_project" -f "$record_compose_file")
asset_compose=("${compose_cli[@]}" -p "$asset_project" -f "$asset_compose_file")

container_running() {
    local project="$1"
    local service="$2"
    local containers
    local count
    containers="$(
        docker ps -aq \
            --filter "label=com.docker.compose.project=${project}" \
            --filter "label=com.docker.compose.service=${service}"
    )"
    count="$(awk 'NF {count += 1} END {print count + 0}' <<<"$containers")"
    [[ "$count" == 1 ]] || fail "Expected exactly one container for $service."
    [[ "$(docker inspect --format '{{.State.Running}}' "$containers")" == true ]]
}

assert_all_c19_writers_stopped() {
    local service
    for service in "${barong_writer_services[@]}"; do
        if container_running "$barong_project" "$service"; then
            fail "Barong writer $service is running inside the backup quiesce boundary."
        fi
    done
    if container_running "$record_project" c19-record-service; then
        fail "Record Service is running inside the backup quiesce boundary."
    fi
    for service in c19-asset-api c19-asset-gateway c19-asset-worker; do
        if container_running "$asset_project" "$service"; then
            fail "Asset writer $service is running inside the backup quiesce boundary."
        fi
    done
}

barong_running=()
for service in "${barong_writer_services[@]}"; do
    if container_running "$barong_project" "$service"; then
        barong_running+=("$service")
    fi
done
[[ " ${barong_running[*]} " == *" console_backend "* ]] || \
    fail "Barong backend must be running before a coordinated backup."
container_running "$barong_project" console_postgres || \
    fail "Barong PostgreSQL must be running before a coordinated backup."
record_was_running=0
container_running "$record_project" c19-record-service && record_was_running=1
[[ "$record_was_running" == 1 ]] || \
    fail "Record Service must be running before a coordinated backup."

export C19_ASSET_ENV_FILE="$asset_env_file"
export C19_ASSET_COMPOSE_FILE="$asset_compose_file"
export C19_ASSET_COMPOSE_PROJECT="$asset_project"
export C19_ASSET_BACKUP_DIR="$generation_dir/asset"
asset_plan="$(./scripts/c19_asset_backup.sh --dry-run --leave-stopped)"
asset_confirmation="$(awk -F': ' '$1 == "required_confirmation" {print $2; exit}' <<<"$asset_plan")"
[[ -n "$asset_confirmation" ]] || fail "Could not derive the Asset backup confirmation."

barong_stopped=0
record_stopped=0
asset_stopped=0
backup_complete=0

resume_sources() {
    local result=0
    if [[ "$asset_stopped" == 1 ]]; then
        "${asset_compose[@]}" start c19-asset-worker c19-asset-api c19-asset-gateway \
            >/dev/null 2>&1 || result=1
        [[ "$result" != 0 ]] || asset_stopped=0
    fi
    if [[ "$record_stopped" == 1 && "$record_was_running" == 1 ]]; then
        "${record_compose[@]}" start c19-record-service >/dev/null 2>&1 || result=1
        [[ "$result" != 0 ]] || record_stopped=0
    fi
    if [[ "$barong_stopped" == 1 && "${#barong_running[@]}" -gt 0 ]]; then
        "${barong_compose[@]}" start "${barong_running[@]}" >/dev/null 2>&1 || result=1
        [[ "$result" != 0 ]] || barong_stopped=0
    fi
    return "$result"
}

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM HUP
    if ! resume_sources; then
        printf '%s\n' \
            'C19 full backup cleanup failed to resume one or more source services; manual intervention is required.' \
            >&2
        exit_code=1
    fi
    if [[ "$exit_code" != 0 && "$backup_complete" == 0 ]]; then
        printf '%s\n' \
            'C19 full backup did not produce an accepted manifest; partial generation remains quarantined.' \
            >&2
    fi
    exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

quiesced_at="$(date -u +%Y%m%dT%H%M%SZ)"
barong_stopped=1
"${barong_compose[@]}" stop -t 60 "${barong_running[@]}"
for service in "${barong_writer_services[@]}"; do
    if container_running "$barong_project" "$service"; then
        fail "Barong writer $service is still running after the coordinated stop."
    fi
done

record_stopped=1
"${record_compose[@]}" stop -t 60 c19-record-service
if container_running "$record_project" c19-record-service; then
    fail "Record Service is still running after the coordinated stop."
fi

asset_stopped=1
CONFIRM_C19_ASSET_BACKUP="$asset_confirmation" \
    ./scripts/c19_asset_backup.sh --execute --leave-stopped
assert_all_c19_writers_stopped

export C19_RECORD_ENV_FILE="$record_env_file"
export C19_RECORD_COMPOSE_FILE="$record_compose_file"
export C19_RECORD_COMPOSE_PROJECT="$record_project"
export C19_RECORD_BACKUP_DIR="$generation_dir/record"
./scripts/c19_record_backup.sh

"${barong_compose[@]}" exec -T console_postgres sh -ec \
    'pg_isready --quiet --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' || \
    fail "Barong PostgreSQL is not ready after writers stopped."
barong_runtime_identity="$(
    "${barong_compose[@]}" exec -T console_postgres sh -ec \
        'printf "%s\t%s" "$POSTGRES_DB" "$POSTGRES_USER"'
)"
IFS=$'\t' read -r barong_database barong_database_user <<<"$barong_runtime_identity"
[[ "$barong_database" =~ ^[A-Za-z_][A-Za-z0-9_]*$ \
    && "$barong_database_user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || \
    fail "Barong PostgreSQL returned an invalid runtime identity."
barong_revision="$(
    "${barong_compose[@]}" exec -T console_postgres sh -ec \
        'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --tuples-only --no-align --command="select version_num from alembic_version limit 1"'
)"
[[ "$barong_revision" =~ ^[A-Za-z0-9_.-]+$ ]] || \
    fail "Could not read the Barong Alembic revision."
barong_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
barong_archive="$generation_dir/barong/barong_ops_${barong_timestamp}.dump"
barong_metadata="${barong_archive}.metadata"
"${barong_compose[@]}" exec -T console_postgres sh -ec \
    'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --compress=9 --no-owner --no-privileges' \
    >"$barong_archive"
barong_archive_sha256="$(sha256sum "$barong_archive" | awk '{print $1}')"
cat >"$barong_metadata" <<EOF
created_at=${barong_timestamp}
source_dataset_id=${barong_dataset_id}
app_version=${barong_app_version}
alembic_revision=${barong_revision}
database_url=docker://${barong_project}/console_postgres/${barong_database}
format=pg_dump_custom
archive=${barong_archive}
archive_sha256=${barong_archive_sha256}
EOF
chmod 600 "$barong_archive" "$barong_metadata"
assert_all_c19_writers_stopped

single_artifact() {
    local directory="$1"
    local pattern="$2"
    local values
    local count
    values="$(find "$directory" -maxdepth 1 -type f -name "$pattern" -print | sort)"
    count="$(awk 'NF {count += 1} END {print count + 0}' <<<"$values")"
    [[ "$count" == 1 ]] || fail "Expected exactly one artifact matching $pattern."
    printf '%s' "$values"
}

barong_archive="$(single_artifact "$generation_dir/barong" 'barong_ops_*.dump')"
record_archive="$(single_artifact "$generation_dir/record" 'c19_records_*.dump')"
record_metadata="${record_archive}.metadata"
asset_metadata="$(single_artifact "$generation_dir/asset" 'c19_assets_*.metadata')"
asset_database="${asset_metadata%.metadata}.dump"
record_revision="$(awk -F= '$1 == "alembic_revision" {print substr($0, length($1) + 2); exit}' "$record_metadata")"
asset_revision="$(awk -F= '$1 == "alembic_revision" {print substr($0, length($1) + 2); exit}' "$asset_metadata")"
[[ "$record_revision" == "$required_record_revision" ]] || \
    fail "Coordinated backup requires Record revision $required_record_revision."
[[ "$asset_revision" == "$required_asset_revision" ]] || \
    fail "Coordinated backup requires Asset revision $required_asset_revision."

validate_record_source_catalog() {
    local record_database
    local record_database_user
    local column_rows
    local constraint_rows
    local foreign_key_rows
    local index_rows
    local expected
    record_database="$(env_value POSTGRES_DB "$record_env_file")"
    record_database_user="$(env_value POSTGRES_USER "$record_env_file")"
    [[ "$record_database" =~ ^[A-Za-z_][A-Za-z0-9_]*$ \
        && "$record_database_user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || \
        fail "Record PostgreSQL identity is invalid during schema validation."
    column_rows="$(
        "${record_compose[@]}" exec -T c19-record-postgres psql \
            --username="$record_database_user" \
            --dbname="$record_database" \
            --tuples-only \
            --no-align \
            --set=ON_ERROR_STOP=1 \
            --command="select table_name || ':' || column_name from information_schema.columns where table_schema = 'public' and table_name in ('record_asset_coordination','record_asset_deletion_outbox','record_retention_operations','record_retention_batches') order by table_name, ordinal_position"
    )" || fail "Could not validate the frozen Record v4 column catalog."
    for expected in \
        "record_asset_coordination:asset_id" \
        "record_asset_coordination:created_at" \
        "record_asset_deletion_outbox:id" \
        "record_asset_deletion_outbox:asset_id" \
        "record_asset_deletion_outbox:record_id" \
        "record_asset_deletion_outbox:conversation_id" \
        "record_asset_deletion_outbox:retention_operation_id" \
        "record_asset_deletion_outbox:state" \
        "record_asset_deletion_outbox:attempt_count" \
        "record_asset_deletion_outbox:created_at" \
        "record_asset_deletion_outbox:last_attempt_at" \
        "record_asset_deletion_outbox:authorized_at" \
        "record_asset_deletion_outbox:lease_owner" \
        "record_asset_deletion_outbox:lease_until" \
        "record_asset_deletion_outbox:outcome" \
        "record_asset_deletion_outbox:completed_at" \
        "record_retention_operations:operation_id" \
        "record_retention_operations:requested_by_user_id" \
        "record_retention_operations:reason" \
        "record_retention_operations:delete_before" \
        "record_retention_operations:conversation_id" \
        "record_retention_operations:approved_maximum_records" \
        "record_retention_operations:approved_maximum_asset_jobs" \
        "record_retention_operations:affected_count" \
        "record_retention_operations:asset_jobs_enqueued_count" \
        "record_retention_operations:asset_jobs_completed_count" \
        "record_retention_operations:next_batch_ordinal" \
        "record_retention_operations:created_at" \
        "record_retention_operations:updated_at" \
        "record_retention_operations:completed_at" \
        "record_retention_batches:operation_id" \
        "record_retention_batches:batch_ordinal" \
        "record_retention_batches:maximum_records" \
        "record_retention_batches:affected_count" \
        "record_retention_batches:cumulative_affected_count" \
        "record_retention_batches:operation_complete" \
        "record_retention_batches:completed_at"; do
        grep -Fxq "$expected" <<<"$column_rows" || \
            fail "Frozen Record v4 source is missing required column $expected."
    done
    constraint_rows="$(
        "${record_compose[@]}" exec -T c19-record-postgres psql \
            --username="$record_database_user" \
            --dbname="$record_database" \
            --tuples-only \
            --no-align \
            --set=ON_ERROR_STOP=1 \
            --command="select table_record.relname || ':' || constraint_record.conname || ':' || constraint_record.contype from pg_constraint as constraint_record join pg_class as table_record on table_record.oid = constraint_record.conrelid join pg_namespace as schema_record on schema_record.oid = table_record.relnamespace where schema_record.nspname = 'public' and table_record.relname in ('record_asset_coordination','record_asset_deletion_outbox','record_retention_operations','record_retention_batches') and constraint_record.convalidated order by table_record.relname, constraint_record.conname"
    )" || fail "Could not validate the frozen Record v4 constraint catalog."
    for expected in \
        "record_asset_coordination:pk_record_asset_coordination:p" \
        "record_asset_deletion_outbox:pk_record_asset_deletion_outbox:p" \
        "record_retention_operations:pk_record_retention_operations:p" \
        "record_retention_batches:pk_record_retention_batches:p" \
        "record_asset_deletion_outbox:fk_record_asset_deletion_outbox_retention_operation_id_record_retention_operations:f" \
        "record_retention_batches:fk_record_retention_batches_operation_id_record_retention_operations:f" \
        "record_asset_deletion_outbox:uq_record_asset_deletion_outbox_record_asset:u" \
        "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_attempt_count_nonnegative:c" \
        "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_state_supported:c" \
        "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_outcome_supported:c" \
        "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_lease_pair_consistent:c" \
        "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_completion_consistent:c" \
        "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_authorization_consistent:c" \
        "record_retention_operations:ck_record_retention_operations_approved_maximum_supported:c" \
        "record_retention_operations:ck_record_retention_operations_approved_asset_maximum_supported:c" \
        "record_retention_operations:ck_record_retention_operations_asset_jobs_enqueued_within_maximum:c" \
        "record_retention_operations:ck_record_retention_operations_asset_jobs_completed_within_enqueued:c" \
        "record_retention_operations:ck_record_retention_operations_affected_count_nonnegative:c" \
        "record_retention_operations:ck_record_retention_operations_affected_within_approved_maximum:c" \
        "record_retention_operations:ck_record_retention_operations_next_batch_ordinal_nonnegative:c" \
        "record_retention_batches:ck_record_retention_batches_batch_ordinal_nonnegative:c" \
        "record_retention_batches:ck_record_retention_batches_maximum_records_supported:c" \
        "record_retention_batches:ck_record_retention_batches_affected_within_batch_maximum:c" \
        "record_retention_batches:ck_record_retention_batches_cumulative_count_consistent:c"; do
        grep -Fxq "$expected" <<<"$constraint_rows" || \
            fail "Frozen Record v4 source is missing validated constraint $expected."
    done
    foreign_key_rows="$(
        "${record_compose[@]}" exec -T c19-record-postgres psql \
            --username="$record_database_user" \
            --dbname="$record_database" \
            --tuples-only \
            --no-align \
            --set=ON_ERROR_STOP=1 \
            --command="select child_table.relname || ':' || constraint_record.conname || ':' || child_column.attname || ':' || parent_table.relname || ':' || parent_column.attname || ':' || constraint_record.confdeltype from pg_constraint as constraint_record join pg_class as child_table on child_table.oid = constraint_record.conrelid join pg_class as parent_table on parent_table.oid = constraint_record.confrelid join pg_namespace as schema_record on schema_record.oid = child_table.relnamespace join pg_attribute as child_column on child_column.attrelid = child_table.oid and child_column.attnum = constraint_record.conkey[1] join pg_attribute as parent_column on parent_column.attrelid = parent_table.oid and parent_column.attnum = constraint_record.confkey[1] where schema_record.nspname = 'public' and constraint_record.contype = 'f' and constraint_record.convalidated and array_length(constraint_record.conkey, 1) = 1 and child_table.relname in ('record_asset_deletion_outbox','record_retention_batches') order by child_table.relname, constraint_record.conname"
    )" || fail "Could not validate the frozen Record v4 foreign-key catalog."
    for expected in \
        "record_asset_deletion_outbox:fk_record_asset_deletion_outbox_retention_operation_id_record_retention_operations:retention_operation_id:record_retention_operations:operation_id:r" \
        "record_retention_batches:fk_record_retention_batches_operation_id_record_retention_operations:operation_id:record_retention_operations:operation_id:r"; do
        grep -Fxq "$expected" <<<"$foreign_key_rows" || \
            fail "Frozen Record v4 source has an invalid foreign key $expected."
    done
    index_rows="$(
        "${record_compose[@]}" exec -T c19-record-postgres psql \
            --username="$record_database_user" \
            --dbname="$record_database" \
            --tuples-only \
            --no-align \
            --set=ON_ERROR_STOP=1 \
            --command="select table_record.relname || ':' || index_record.relname from pg_index as index_state join pg_class as index_record on index_record.oid = index_state.indexrelid join pg_class as table_record on table_record.oid = index_state.indrelid join pg_namespace as schema_record on schema_record.oid = table_record.relnamespace where schema_record.nspname = 'public' and table_record.relname in ('record_asset_deletion_outbox','record_retention_operations') and index_state.indisvalid and index_state.indisready order by table_record.relname, index_record.relname"
    )" || fail "Could not validate the frozen Record v4 index catalog."
    for expected in \
        "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_state_created" \
        "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_retention_operation" \
        "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_asset_state" \
        "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_lease_until" \
        "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_authorized_at" \
        "record_retention_operations:ix_record_retention_operations_completed_at"; do
        grep -Fxq "$expected" <<<"$index_rows" || \
            fail "Frozen Record v4 source is missing ready index $expected."
    done
}

validate_record_source_catalog

validate_archive_tables() {
    local -n compose_ref=$1
    local service="$2"
    local archive="$3"
    shift 3
    local archive_list
    local table
    archive_list="$("${compose_ref[@]}" exec -T "$service" pg_restore --list <"$archive")" || \
        fail "Could not read a PostgreSQL custom archive during full backup validation."
    for table in "$@"; do
        grep -Eq "[[:space:]]TABLE([[:space:]]DATA)?[[:space:]]+public[[:space:]]+${table}([[:space:]]|$)" \
            <<<"$archive_list" || \
            fail "A coordinated database archive is missing required table $table."
    done
}

validate_archive_tables barong_compose console_postgres "$barong_archive" \
    alembic_version users auth_sessions
validate_archive_tables record_compose c19-record-postgres "$record_archive" \
    alembic_version chat_records record_idempotency_ledger moments moment_user_events \
    record_asset_coordination record_asset_deletion_outbox \
    record_retention_operations record_retention_batches
validate_archive_tables asset_compose c19-asset-postgres "$asset_database" \
    alembic_version asset_dataset_identity chat_assets asset_transfer_tickets

validate_archive_schema_tokens() {
    local -n compose_ref=$1
    local service="$2"
    local archive="$3"
    shift 3
    local archive_schema
    local token
    archive_schema="$(
        "${compose_ref[@]}" exec -T "$service" pg_restore --schema-only --file=- \
            <"$archive"
    )" || fail "Could not read a PostgreSQL archive schema during full backup validation."
    for token in "$@"; do
        grep -Eq "(^|[^A-Za-z0-9_])${token}([^A-Za-z0-9_]|$)" <<<"$archive_schema" || \
            fail "A coordinated database archive is missing required schema token $token."
    done
}

validate_archive_schema_tokens record_compose c19-record-postgres "$record_archive" \
    pk_record_asset_coordination pk_record_asset_deletion_outbox \
    pk_record_retention_operations pk_record_retention_batches \
    fk_record_asset_deletion_outbox_retention_operation_id_record_retention_operations \
    fk_record_retention_batches_operation_id_record_retention_operations \
    uq_record_asset_deletion_outbox_record_asset \
    ck_record_asset_deletion_outbox_attempt_count_nonnegative \
    ck_record_asset_deletion_outbox_state_supported \
    ck_record_asset_deletion_outbox_outcome_supported \
    ck_record_asset_deletion_outbox_lease_pair_consistent \
    ck_record_asset_deletion_outbox_completion_consistent \
    ck_record_asset_deletion_outbox_authorization_consistent \
    ck_record_retention_operations_approved_maximum_supported \
    ck_record_retention_operations_approved_asset_maximum_supported \
    ck_record_retention_operations_asset_jobs_enqueued_within_maximum \
    ck_record_retention_operations_asset_jobs_completed_within_enqueued \
    ck_record_retention_operations_affected_count_nonnegative \
    ck_record_retention_operations_affected_within_approved_maximum \
    ck_record_retention_operations_next_batch_ordinal_nonnegative \
    ck_record_retention_batches_batch_ordinal_nonnegative \
    ck_record_retention_batches_maximum_records_supported \
    ck_record_retention_batches_affected_within_batch_maximum \
    ck_record_retention_batches_cumulative_count_consistent \
    ix_record_asset_deletion_outbox_state_created \
    ix_record_asset_deletion_outbox_retention_operation \
    ix_record_asset_deletion_outbox_asset_state \
    ix_record_asset_deletion_outbox_lease_until \
    ix_record_asset_deletion_outbox_authorized_at \
    ix_record_retention_operations_completed_at

validate_archive_schema_tokens asset_compose c19-asset-postgres "$asset_database" \
    retention_operation_id retention_record_id retention_conversation_id \
    retention_prepared_at ck_chat_assets_retention_preparation_consistent \
    uq_chat_assets_retention_operation_id ix_chat_assets_retention_prepared_at
captured_at="$(date -u +%Y%m%dT%H%M%SZ)"

"$python_bin" scripts/c19_full_dr.py seal \
    --generation-dir "$generation_dir" \
    --generation-id "$generation_id" \
    --barong-dataset-id "$barong_dataset_id" \
    --record-dataset-id "$record_dataset_id" \
    --asset-dataset-id "$asset_dataset_id" \
    --barong-archive "$barong_archive" \
    --record-archive "$record_archive" \
    --asset-metadata "$asset_metadata" \
    --quiesced-at "$quiesced_at" \
    --captured-at "$captured_at" \
    --manifest "$manifest" \
    --hmac-key-file "$hmac_key_file"

"$python_bin" scripts/c19_full_dr.py verify \
    --manifest "$manifest" \
    --hmac-key-file "$hmac_key_file" \
    --expected-barong-dataset "$barong_dataset_id" \
    --expected-record-dataset "$record_dataset_id" \
    --expected-asset-dataset "$asset_dataset_id"

backup_complete=1
resume_sources || fail "Backup is sealed but one or more source services did not resume."
trap - EXIT INT TERM HUP

printf 'C19 full backup completed and verified\n'
printf 'manifest: %s\n' "$manifest"
printf 'manifest_signature: %s.hmac\n' "$manifest"
printf 'source_writers_running: yes\n'
