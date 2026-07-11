#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

compose_file="${C19_RECORD_COMPOSE_FILE:-docker-compose.c19-record.yml}"
project_name="${C19_RECORD_COMPOSE_PROJECT:-c19-record}"
env_file="${C19_RECORD_ENV_FILE:-.env.c19-record.production}"
volume_name="${C19_RECORD_VOLUME_NAME:-c19_record_postgres_data}"
private_network_name="${C19_RECORD_PRIVATE_NETWORK_NAME:-c19-record-private}"
shared_network_name="${BARONG_SHARED_NETWORK_NAME:-barong-ops-console-prod}"
archive=""
mode="dry-run"

required_tables=(
    alembic_version
    chat_participant_positions
    chat_records
    chat_user_record_events
    record_conversation_sequences
    record_idempotency_ledger
    record_mutation_audits
    record_user_event_sequences
)

fail() {
    printf 'C19 record restore failed: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/c19_record_restore.sh --archive backups/c19-record/c19_records_YYYY.dump --dry-run
  CONFIRM_C19_RECORD_RESTORE=<dataset>/<archive-sha256>/<project>/<target-db>/<volume>/<private-network>/<client-network> ./scripts/c19_record_restore.sh --archive backup.dump --execute

The default is a non-mutating plan. Execution restores only the independent
C19 record database, temporarily stops only c19-record-service, validates the
archive checksum/schema/revision, and never runs `docker-compose down`.
USAGE
}

metadata_value() {
    local key="$1"
    local file="$2"
    [[ -f "$file" ]] || return 0
    awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2); exit}' "$file"
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
    [[ "$count" == "1" ]] || fail "$key must appear exactly once in $env_file."
    canonical_count="$(awk -v key="$key" '$0 ~ ("^" key "=") {count += 1} END {print count + 0}' "$env_file")"
    [[ "$canonical_count" == "1" ]] || \
        fail "$key must use the exact KEY=value form without export or surrounding whitespace."
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --archive)
            [[ $# -ge 2 ]] || fail "--archive requires a value."
            archive="$2"
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

[[ -n "$archive" ]] || fail "--archive is required."
[[ -f "$archive" ]] || fail "Archive does not exist: $archive"
[[ -f "$compose_file" ]] || fail "Compose file does not exist: $compose_file"
[[ -f "$env_file" ]] || fail "Environment file does not exist: $env_file"
command -v docker >/dev/null 2>&1 || fail "docker is required."
if command -v docker-compose >/dev/null 2>&1; then
    compose_cli=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
    compose_cli=(docker compose)
else
    fail "Docker Compose v1 or v2 is required."
fi
command -v flock >/dev/null 2>&1 || fail "flock is required."
command -v python3 >/dev/null 2>&1 || fail "python3 is required."
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required."

metadata="$archive.metadata"
[[ -f "$metadata" ]] || fail "Archive metadata does not exist: $metadata"
expected_sha256="$(metadata_value archive_sha256 "$metadata")"
expected_revision="$(metadata_value alembic_revision "$metadata")"
source_dataset_id="$(metadata_value source_dataset_id "$metadata")"
archive_format="$(metadata_value format "$metadata")"
[[ "$expected_sha256" =~ ^[0-9a-f]{64}$ ]] || \
    fail "Archive metadata has no valid SHA-256."
[[ "$expected_revision" =~ ^[A-Za-z0-9_.-]+$ ]] || \
    fail "Archive metadata has no valid Alembic revision."
[[ "$source_dataset_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$ ]] || \
    fail "Archive metadata has no valid source dataset identity."
[[ "$archive_format" == "pg_dump_custom" ]] || \
    fail "Archive metadata format must be pg_dump_custom."
actual_sha256="$(sha256sum "$archive" | awk '{print $1}')"
if [[ "$actual_sha256" != "$expected_sha256" ]]; then
    fail "Archive checksum does not match its metadata."
fi

for required_key in C19_RECORD_DATASET_ID POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD C19_RECORD_DATABASE_URL C19_RECORD_SERVICE_TOKEN C19_RECORD_CURSOR_SIGNING_SECRET C19_RECORD_CURSOR_TTL_SECONDS C19_RECORD_MAX_MESSAGE_CHARS; do
    require_unique_env_key "$required_key"
done
target_db="$(env_value POSTGRES_DB)"
target_dataset_id="$(env_value C19_RECORD_DATASET_ID)"
target_user="$(env_value POSTGRES_USER)"
target_password="$(env_value POSTGRES_PASSWORD)"
database_url="$(env_value C19_RECORD_DATABASE_URL)"
service_token="$(env_value C19_RECORD_SERVICE_TOKEN)"
cursor_signing_secret="$(env_value C19_RECORD_CURSOR_SIGNING_SECRET)"
cursor_ttl_seconds="$(env_value C19_RECORD_CURSOR_TTL_SECONDS)"
max_message_chars="$(env_value C19_RECORD_MAX_MESSAGE_CHARS)"
[[ "$target_db" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || \
    fail "POSTGRES_DB in the target environment file is missing or invalid."
[[ "$target_dataset_id" == "$source_dataset_id" ]] || \
    fail "Archive source dataset does not match C19_RECORD_DATASET_ID."
[[ "$target_user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || \
    fail "POSTGRES_USER in the target environment file is missing or invalid."
[[ -n "$target_password" && -n "$database_url" ]] || \
    fail "The target PostgreSQL password and record database URL are required."
[[ "${database_url^^}" != *CHANGE-ME* ]] || \
    fail "C19_RECORD_DATABASE_URL still contains a deployment placeholder."
[[ ${#service_token} -ge 32 && "${service_token^^}" != *CHANGE-ME* ]] || \
    fail "C19_RECORD_SERVICE_TOKEN must be at least 32 characters and contain no placeholder."
[[ ${#cursor_signing_secret} -ge 32 && "${cursor_signing_secret^^}" != *CHANGE-ME* ]] || \
    fail "C19_RECORD_CURSOR_SIGNING_SECRET must be at least 32 characters and contain no placeholder."
[[ "$cursor_ttl_seconds" =~ ^[1-9][0-9]*$ ]] || \
    fail "C19_RECORD_CURSOR_TTL_SECONDS must be a positive integer."
[[ "$max_message_chars" =~ ^[1-9][0-9]*$ ]] || \
    fail "C19_RECORD_MAX_MESSAGE_CHARS must be a positive integer."
connection_identity="$(
    printf '%s' "$database_url" | python3 -c 'import sys; from urllib.parse import unquote, urlsplit; u=urlsplit(sys.stdin.read()); print("\t".join((u.scheme, u.hostname or "", str(u.port or 5432), unquote(u.username or ""), unquote(u.password or ""), u.path.lstrip("/"), u.query, u.fragment)))'
)" || fail "C19_RECORD_DATABASE_URL could not be parsed."
IFS=$'\t' read -r url_scheme url_host url_port url_user url_password url_database url_query url_fragment \
    <<<"$connection_identity"
[[ "$url_scheme" == "postgresql+psycopg" \
    && "$url_host" == "c19-record-postgres" \
    && "$url_port" == "5432" \
    && "$url_user" == "$target_user" \
    && "$url_password" == "$target_password" \
    && "$url_database" == "$target_db" \
    && -z "$url_query" \
    && -z "$url_fragment" ]] || \
    fail "C19_RECORD_DATABASE_URL must identify this stack's PostgreSQL host, user, password, and database."
[[ "$volume_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || \
    fail "C19_RECORD_VOLUME_NAME is invalid."
[[ "$private_network_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || \
    fail "C19_RECORD_PRIVATE_NETWORK_NAME is invalid."
[[ "$shared_network_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || \
    fail "BARONG_SHARED_NETWORK_NAME is invalid."
if [[ "$project_name" != "c19-record" || "$volume_name" != "c19_record_postgres_data" ]] \
    && { [[ "$private_network_name" == "c19-record-private" ]] \
        || [[ "$shared_network_name" == "barong-ops-console-prod" ]]; }; then
    fail "A rehearsal/alternate stack must isolate both private and client networks."
fi
restore_identity="${source_dataset_id}/${actual_sha256}/${project_name}/${target_db}/${volume_name}/${private_network_name}/${shared_network_name}"

verify_postgres_volume() {
    local container_id="$1"
    local mount_identity
    local mount_type
    local mounted_volume
    mount_identity="$(
        docker inspect --format \
            '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{printf "%s\t%s" .Type .Name}}{{end}}{{end}}' \
            "$container_id"
    )" || fail "Could not inspect the target C19 record PostgreSQL data mount."
    IFS=$'\t' read -r mount_type mounted_volume <<<"$mount_identity"
    [[ "$mount_type" == "volume" && "$mounted_volume" == "$volume_name" ]] || \
        fail "The target PostgreSQL container is not attached to the confirmed C19_RECORD_VOLUME_NAME."
}

verify_volume_dataset_label() {
    local volume_dataset_id
    volume_dataset_id="$(
        docker volume inspect --format \
            '{{index .Labels "com.barong.c19.dataset-id"}}' \
            "$volume_name"
    )" || fail "Could not inspect the target C19 record volume."
    [[ "$volume_dataset_id" == "$target_dataset_id" ]] || \
        fail "The target volume dataset label does not match C19_RECORD_DATASET_ID."
}

container_config_value() {
    local container_id="$1"
    local key="$2"
    docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container_id" \
        | awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2); exit}'
}

verify_existing_postgres_identity() {
    local container_id="$1"
    local existing_db
    local existing_user
    local existing_dataset_id
    existing_db="$(container_config_value "$container_id" POSTGRES_DB)"
    existing_user="$(container_config_value "$container_id" POSTGRES_USER)"
    existing_dataset_id="$(container_config_value "$container_id" C19_RECORD_DATASET_ID)"
    [[ "$existing_db" == "$target_db" \
        && "$existing_user" == "$target_user" \
        && "$existing_dataset_id" == "$target_dataset_id" ]] || \
        fail "The existing PostgreSQL container identity does not match the confirmed env file."
}

printf 'C19 record restore plan\n'
printf 'mode: %s\n' "$mode"
printf 'archive: %s\n' "$archive"
printf 'archive_sha256: %s\n' "$actual_sha256"
printf 'expected_revision: %s\n' "${expected_revision:-not_recorded}"
printf 'source_dataset_id: %s\n' "$source_dataset_id"
printf 'compose_file: %s\n' "$compose_file"
printf 'project_name: %s\n' "$project_name"
printf 'target_volume: %s\n' "$volume_name"
printf 'private_network: %s\n' "$private_network_name"
printf 'client_network: %s\n' "$shared_network_name"
printf 'target_env_file: %s\n' "$env_file"
printf 'required_confirmation: %s\n' "$restore_identity"

if [[ "$mode" == "dry-run" ]]; then
    printf '%s\n' 'No containers or databases were changed.'
    printf '%s\n' 'Execution will: start only target PostgreSQL; validate the archive; stop only the record service; restore transactionally; verify schema/revision; restart and health-check the service.'
    exit 0
fi

export C19_RECORD_ENV_FILE="$env_file"
export C19_RECORD_VOLUME_NAME="$volume_name"
export C19_RECORD_PRIVATE_NETWORK_NAME="$private_network_name"
export BARONG_SHARED_NETWORK_NAME="$shared_network_name"
export C19_RECORD_DATASET_ID="$target_dataset_id"
compose=("${compose_cli[@]}" -p "$project_name" -f "$compose_file")
[[ "${CONFIRM_C19_RECORD_RESTORE:-}" == "$restore_identity" ]] || \
    fail "Set CONFIRM_C19_RECORD_RESTORE=$restore_identity to execute this restore."

existing_postgres_container="$("${compose[@]}" ps -q c19-record-postgres 2>/dev/null || true)"
if [[ -n "$existing_postgres_container" ]]; then
    verify_postgres_volume "$existing_postgres_container"
    verify_existing_postgres_identity "$existing_postgres_container"
fi
if docker volume inspect "$volume_name" >/dev/null 2>&1; then
    verify_volume_dataset_label
fi

lock_dir="${C19_RECORD_LOCK_DIR:-${repo_root}/backups/c19-record/.locks}"
[[ ! -L "$lock_dir" ]] || fail "C19_RECORD_LOCK_DIR must not be a symbolic link."
mkdir -p "$lock_dir"
chmod 700 "$lock_dir"
lock_file="${lock_dir}/${volume_name}.lock"
[[ ! -L "$lock_file" ]] || fail "The C19 record lock file must not be a symbolic link."
exec 9>"$lock_file"
chmod 600 "$lock_file"
flock -n 9 || fail "Another backup or restore is already using volume $volume_name."

"${compose[@]}" up -d c19-record-postgres

postgres_ready="no"
for _ in $(seq 1 30); do
    if "${compose[@]}" exec -T c19-record-postgres sh -ec \
        'pg_isready --quiet --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
        >/dev/null 2>&1
    then
        postgres_ready="yes"
        break
    fi
    postgres_container="$("${compose[@]}" ps -q c19-record-postgres 2>/dev/null || true)"
    if [[ -n "$postgres_container" ]]; then
        postgres_state="$(docker inspect --format '{{.State.Status}}' "$postgres_container" 2>/dev/null || true)"
        if [[ "$postgres_state" == "exited" || "$postgres_state" == "dead" ]]; then
            fail "Target C19 record PostgreSQL exited during startup."
        fi
    fi
    sleep 2
done
[[ "$postgres_ready" == "yes" ]] || fail "Target C19 record PostgreSQL is not ready."
postgres_container="$("${compose[@]}" ps -q c19-record-postgres 2>/dev/null || true)"
[[ -n "$postgres_container" ]] || fail "Target C19 record PostgreSQL container is missing."
verify_postgres_volume "$postgres_container"
verify_volume_dataset_label
runtime_identity="$(
    "${compose[@]}" exec -T c19-record-postgres sh -ec \
        'printf "%s\t%s\t%s" "$POSTGRES_DB" "$POSTGRES_USER" "$C19_RECORD_DATASET_ID"'
)" || fail "Could not read the running target PostgreSQL identity."
IFS=$'\t' read -r runtime_db runtime_user runtime_dataset_id <<<"$runtime_identity"
[[ "$runtime_db" == "$target_db" \
    && "$runtime_user" == "$target_user" \
    && "$runtime_dataset_id" == "$target_dataset_id" ]] || \
    fail "The running target PostgreSQL identity does not match the confirmed env file."

archive_list="$(mktemp)"
restore_phase="preflight"
record_service_was_running="no"
database_swap_timestamp="$(date -u +%Y%m%d%H%M%S)"
restore_database="c19_restore_${database_swap_timestamp}"
rollback_database="c19_rollback_${database_swap_timestamp}"
failed_database="c19_failed_${database_swap_timestamp}"

drop_temporary_restore_database() {
    "${compose[@]}" exec -T c19-record-postgres psql \
        --username="$target_user" \
        --dbname=postgres \
        --set=ON_ERROR_STOP=1 \
        --command="drop database if exists \"$restore_database\" with (force)" \
        >/dev/null 2>&1
}

rollback_database_swap() {
    restore_phase="rollback_in_progress"
    "${compose[@]}" stop c19-record-service >/dev/null 2>&1 || true
    "${compose[@]}" exec -T c19-record-postgres psql \
        --username="$target_user" \
        --dbname=postgres \
        --command="select pg_terminate_backend(pid, 5000) from pg_stat_activity where datname in ('$target_db', '$rollback_database') and pid <> pg_backend_pid()" \
        >/dev/null 2>&1 || true
    if ! "${compose[@]}" exec -T c19-record-postgres psql \
        --username="$target_user" \
        --dbname=postgres \
        --set=ON_ERROR_STOP=1 \
        --command="begin; alter database \"$target_db\" rename to \"$failed_database\"; alter database \"$rollback_database\" rename to \"$target_db\"; commit" \
        >/dev/null 2>&1
    then
        restore_phase="rollback_failed"
        return 1
    fi
    restore_phase="rolled_back"
    if [[ "${record_service_was_running:-no}" == "yes" ]]; then
        "${compose[@]}" up -d c19-record-service >/dev/null 2>&1 || true
    fi
    return 0
}

database_exists() {
    local database_name="$1"
    "${compose[@]}" exec -T c19-record-postgres psql \
        --username="$target_user" \
        --dbname=postgres \
        --tuples-only \
        --no-align \
        --set=ON_ERROR_STOP=1 \
        --command="select exists(select 1 from pg_database where datname = '$database_name')::text"
}

resolve_uncertain_swap() {
    local target_exists
    local rollback_exists
    local temporary_exists
    target_exists="$(database_exists "$target_db")" || return 1
    rollback_exists="$(database_exists "$rollback_database")" || return 1
    temporary_exists="$(database_exists "$restore_database")" || return 1

    if [[ "$target_exists" == "true" \
        && "$rollback_exists" == "false" \
        && "$temporary_exists" == "true" ]]; then
        drop_temporary_restore_database || return 1
        restore_phase="rolled_back"
        if [[ "${record_service_was_running:-no}" == "yes" ]]; then
            "${compose[@]}" up -d c19-record-service >/dev/null 2>&1 || true
        fi
        return 0
    fi

    if [[ "$target_exists" == "true" \
        && "$rollback_exists" == "true" \
        && "$temporary_exists" == "false" ]]; then
        restore_phase="swapped"
        rollback_database_swap
        return $?
    fi

    restore_phase="rollback_failed"
    return 1
}

fail_after_swap() {
    local reason="$1"
    if rollback_database_swap; then
        fail "$reason Original database was automatically restored."
    fi
    fail "$reason Automatic database rollback also failed; manual recovery is required."
}

restore_exit_cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM HUP
    rm -f "${archive_list:-}"
    if [[ "$exit_code" -ne 0 ]]; then
        case "${restore_phase:-}" in
            restore_database_created|restored_validated|stopped_before_swap)
                if ! drop_temporary_restore_database; then
                    printf '%s\n' \
                        "C19 record restore cleanup warning: temporary database $restore_database requires manual removal." \
                        >&2
                fi
                if [[ "${record_service_was_running:-no}" == "yes" ]]; then
                    "${compose[@]}" up -d c19-record-service >/dev/null 2>&1 || true
                fi
                ;;
            swapped)
                if rollback_database_swap; then
                    printf '%s\n' \
                        'C19 record restore failed unexpectedly after swap; original database was automatically restored.' \
                        >&2
                else
                    printf '%s\n' \
                        'C19 record restore failed unexpectedly after swap and automatic rollback failed; manual recovery is required.' \
                        >&2
                fi
                ;;
            swap_in_progress)
                if resolve_uncertain_swap; then
                    printf '%s\n' \
                        'C19 record restore exited while swap status was uncertain; the original database is active.' \
                        >&2
                else
                    printf '%s\n' \
                        'C19 record restore exited while swap status was uncertain; service remains stopped and manual recovery is required.' \
                        >&2
                fi
                ;;
            rollback_in_progress|rollback_failed)
                printf '%s\n' \
                    'C19 record restore exited during rollback; manual database recovery is required.' \
                    >&2
                ;;
        esac
    fi
    exit "$exit_code"
}
trap restore_exit_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
"${compose[@]}" exec -T c19-record-postgres pg_restore --list \
    <"$archive" >"$archive_list"
for table_name in "${required_tables[@]}"; do
    grep -Eq "[[:space:]]TABLE([[:space:]]DATA)?[[:space:]]+public[[:space:]]+${table_name}([[:space:]]|$)" "$archive_list" \
        || fail "Archive is missing required table: $table_name"
done

create_pre_restore_backup() {
    local target_has_records
    target_has_records="$(
        "${compose[@]}" exec -T c19-record-postgres sh -ec \
            'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --tuples-only --no-align --command="select (to_regclass('\''public.chat_records'\'') is not null)::text"'
    )"
    if [[ "$target_has_records" != "true" ]]; then
        return
    fi
    pre_restore_dir="${C19_RECORD_PRE_RESTORE_BACKUP_DIR:-backups/c19-record/pre-restore}"
    pre_restore_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    pre_restore_archive="${pre_restore_dir}/c19_records_before_restore_${pre_restore_timestamp}.dump"
    pre_restore_metadata="${pre_restore_archive}.metadata"
    mkdir -p "$pre_restore_dir"
    umask 077
    target_revision="$(
        "${compose[@]}" exec -T c19-record-postgres sh -ec \
            'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --tuples-only --no-align --command="select version_num from alembic_version limit 1"'
    )"
    [[ -n "$target_revision" ]] || fail "Could not read the pre-restore target revision."
    "${compose[@]}" exec -T c19-record-postgres sh -ec \
        'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --compress=9 --no-owner --no-privileges' \
        >"$pre_restore_archive"
    pre_restore_sha256="$(sha256sum "$pre_restore_archive" | awk '{print $1}')"
    cat >"$pre_restore_metadata" <<EOF
created_at=${pre_restore_timestamp}
source_dataset_id=${target_dataset_id}
alembic_revision=${target_revision}
format=pg_dump_custom
archive_sha256=${pre_restore_sha256}
EOF
    chmod 600 "$pre_restore_archive" "$pre_restore_metadata"
    printf 'pre_restore_archive: %s\n' "$pre_restore_archive"
}

"${compose[@]}" exec -T c19-record-postgres psql \
    --username="$target_user" \
    --dbname=postgres \
    --set=ON_ERROR_STOP=1 \
    --command="create database \"$restore_database\" owner \"$target_user\" template template0"
restore_phase="restore_database_created"
"${compose[@]}" exec -T c19-record-postgres pg_restore \
    --clean \
    --if-exists \
    --exit-on-error \
    --single-transaction \
    --no-owner \
    --no-privileges \
    --username="$target_user" \
    --dbname="$restore_database" \
    <"$archive"

restored_revision="$(
    "${compose[@]}" exec -T c19-record-postgres psql \
        --username="$target_user" \
        --dbname="$restore_database" \
        --tuples-only \
        --no-align \
        --command="select version_num from alembic_version limit 1"
)"
[[ -n "$restored_revision" ]] || fail "Restored database has no Alembic revision."
if [[ -n "$expected_revision" && "$restored_revision" != "$expected_revision" ]]; then
    fail "Restored revision does not match archive metadata; record service remains stopped."
fi
ledger_columns="$(
    "${compose[@]}" exec -T c19-record-postgres psql \
        --username="$target_user" \
        --dbname="$restore_database" \
        --tuples-only \
        --no-align \
        --command="select column_name from information_schema.columns where table_schema = 'public' and table_name = 'record_idempotency_ledger' order by column_name"
)"
for column_name in sender_user_id client_message_id intent_sha256 record_id status deleted_at; do
    grep -Fxq "$column_name" <<<"$ledger_columns" || \
        fail "Restored idempotency ledger is missing column $column_name; record service remains stopped."
done
restore_phase="restored_validated"

record_service_container="$("${compose[@]}" ps -q c19-record-service 2>/dev/null || true)"
if [[ -n "$record_service_container" ]]; then
    record_service_state="$(docker inspect --format '{{.State.Status}}' "$record_service_container" 2>/dev/null || true)"
    if [[ "$record_service_state" == "running" || "$record_service_state" == "restarting" ]]; then
        record_service_was_running="yes"
        "${compose[@]}" stop c19-record-service >/dev/null \
            || fail "Could not stop the target C19 record service."
        record_service_state="$(docker inspect --format '{{.State.Status}}' "$record_service_container" 2>/dev/null || true)"
        [[ "$record_service_state" != "running" && "$record_service_state" != "restarting" ]] || \
            fail "Target C19 record service is still running."
        restore_phase="stopped_before_swap"
    fi
fi

create_pre_restore_backup

restore_phase="swap_in_progress"
if ! "${compose[@]}" exec -T c19-record-postgres psql \
    --username="$target_user" \
    --dbname=postgres \
    --set=ON_ERROR_STOP=1 \
    --command="select pg_terminate_backend(pid, 5000) from pg_stat_activity where datname in ('$target_db', '$restore_database') and pid <> pg_backend_pid()"
then
    fail "Could not terminate target database connections; original database remains active."
fi
if ! "${compose[@]}" exec -T c19-record-postgres psql \
    --username="$target_user" \
    --dbname=postgres \
    --set=ON_ERROR_STOP=1 \
    --command="begin; alter database \"$target_db\" rename to \"$rollback_database\"; alter database \"$restore_database\" rename to \"$target_db\"; commit"
then
    if resolve_uncertain_swap; then
        fail "Could not confirm the atomic activation result; the original database is active."
    fi
    fail "Could not confirm or safely reverse the atomic activation result; service remains stopped and manual recovery is required."
fi
restore_phase="swapped"

if ! "${compose[@]}" up -d c19-record-service; then
    fail_after_swap "Record service could not be started after restore."
fi
healthy="no"
for _ in $(seq 1 30); do
    if "${compose[@]}" exec -T c19-record-service python -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2).read()" \
        >/dev/null 2>&1
    then
        healthy="yes"
        break
    fi
    service_container="$("${compose[@]}" ps -q c19-record-service 2>/dev/null || true)"
    if [[ -n "$service_container" ]]; then
        service_state="$(docker inspect --format '{{.State.Status}}' "$service_container" 2>/dev/null || true)"
        if [[ "$service_state" == "exited" || "$service_state" == "dead" ]]; then
            fail_after_swap "Record service exited during startup after restore."
        fi
    fi
    sleep 2
done
[[ "$healthy" == "yes" ]] || \
    fail_after_swap "Record service did not become healthy after restore."
restore_phase="complete"

printf 'C19 record restore completed\n'
printf 'target_database: %s\n' "$target_db"
printf 'rollback_database: %s\n' "$rollback_database"
printf 'restored_revision: %s\n' "$restored_revision"
