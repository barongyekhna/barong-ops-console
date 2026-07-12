#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

compose_file="${C19_ASSET_COMPOSE_FILE:-docker-compose.c19-asset.yml}"
project_name="${C19_ASSET_COMPOSE_PROJECT:-c19-asset}"
env_file="${C19_ASSET_ENV_FILE:-.env.c19-asset.production}"
output_dir="${C19_ASSET_BACKUP_DIR:-backups/c19-asset}"
postgres_volume="${C19_ASSET_POSTGRES_VOLUME_NAME:-c19_asset_postgres_data}"
incoming_volume="${C19_ASSET_INCOMING_VOLUME_NAME:-c19_asset_incoming_data}"
quarantine_volume="${C19_ASSET_QUARANTINE_VOLUME_NAME:-c19_asset_quarantine_data}"
active_volume="${C19_ASSET_ACTIVE_VOLUME_NAME:-c19_asset_active_data}"
private_network="${C19_ASSET_PRIVATE_NETWORK_NAME:-c19-asset-private}"
clam_egress_network="${C19_ASSET_CLAM_EGRESS_NETWORK_NAME:-c19-asset-clam-egress}"
gateway_ingress_network="${C19_ASSET_GATEWAY_INGRESS_NETWORK_NAME:-c19-asset-gateway-ingress}"
client_network="${BARONG_SHARED_NETWORK_NAME:-barong-ops-console-prod}"
mode="dry-run"
leave_stopped=0
drain_timeout_seconds="${C19_ASSET_BACKUP_DRAIN_TIMEOUT_SECONDS:-600}"
required_revision="c19_asset_20260712_03"

fail() {
    printf 'C19 asset backup failed: %s\n' "$1" >&2
    exit 1
}

usage() {
    printf '%s\n' \
        'Usage:' \
        '  ./scripts/c19_asset_backup.sh --dry-run' \
        '  CONFIRM_C19_ASSET_BACKUP=<printed-value> ./scripts/c19_asset_backup.sh --execute' \
        '  CONFIRM_C19_ASSET_BACKUP=<printed-value> ./scripts/c19_asset_backup.sh --execute --leave-stopped' \
        '' \
        'The default only validates identity and prints the confirmation value.' \
        'Execution stops gateway/API first, then lets the worker finish its current unit.' \
        '--leave-stopped is the fail-closed final-cutover mode and also applies on failure.'
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
        --leave-stopped)
            leave_stopped=1
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

for required_key in \
    C19_ASSET_DATASET_ID POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD \
    C19_ASSET_DATABASE_URL C19_ASSET_SERVICE_TOKEN C19_ASSET_GATEWAY_TOKEN \
    C19_ASSET_INCOMING_ROOT C19_ASSET_QUARANTINE_ROOT C19_ASSET_ACTIVE_ROOT; do
    require_unique_env_key "$required_key"
done

dataset_id="$(env_value C19_ASSET_DATASET_ID)"
target_db="$(env_value POSTGRES_DB)"
target_user="$(env_value POSTGRES_USER)"
target_password="$(env_value POSTGRES_PASSWORD)"
[[ "$dataset_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$ ]] || \
    fail "C19_ASSET_DATASET_ID is missing or invalid."
[[ "$target_db" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || \
    fail "POSTGRES_DB is missing or invalid."
[[ "$target_user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || \
    fail "POSTGRES_USER is missing or invalid."
[[ -n "$target_password" && "${target_password^^}" != *CHANGE-ME* ]] || \
    fail "POSTGRES_PASSWORD is missing or still contains a placeholder."
[[ "$drain_timeout_seconds" =~ ^[0-9]+$ \
    && "$drain_timeout_seconds" -ge 30 \
    && "$drain_timeout_seconds" -le 3600 ]] || \
    fail "C19_ASSET_BACKUP_DRAIN_TIMEOUT_SECONDS must be between 30 and 3600."

for value in \
    "$project_name" "$postgres_volume" "$incoming_volume" \
    "$quarantine_volume" "$active_volume" "$private_network" \
    "$clam_egress_network" "$gateway_ingress_network" "$client_network"; do
    [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || \
        fail "A project, volume, or network name is invalid."
done

export C19_ASSET_ENV_FILE="$env_file"
export C19_ASSET_DATASET_ID="$dataset_id"
export C19_ASSET_POSTGRES_VOLUME_NAME="$postgres_volume"
export C19_ASSET_INCOMING_VOLUME_NAME="$incoming_volume"
export C19_ASSET_QUARANTINE_VOLUME_NAME="$quarantine_volume"
export C19_ASSET_ACTIVE_VOLUME_NAME="$active_volume"
export C19_ASSET_PRIVATE_NETWORK_NAME="$private_network"
export C19_ASSET_CLAM_EGRESS_NETWORK_NAME="$clam_egress_network"
export C19_ASSET_GATEWAY_INGRESS_NETWORK_NAME="$gateway_ingress_network"
export BARONG_SHARED_NETWORK_NAME="$client_network"
compose=("${compose_cli[@]}" -p "$project_name" -f "$compose_file")

verify_volume() {
    local volume="$1"
    local role="$2"
    local labels
    labels="$(
        docker volume inspect --format \
            '{{index .Labels "com.barong.c19.asset-dataset-id"}}{{printf "\t"}}{{index .Labels "com.barong.c19.asset-volume-role"}}' \
            "$volume"
    )" || fail "Required volume does not exist: $volume"
    local actual_dataset
    local actual_role
    IFS=$'\t' read -r actual_dataset actual_role <<<"$labels"
    [[ "$actual_dataset" == "$dataset_id" && "$actual_role" == "$role" ]] || \
        fail "Volume $volume does not match dataset $dataset_id and role $role."
}

verify_volume "$postgres_volume" metadata
verify_volume "$incoming_volume" incoming
verify_volume "$quarantine_volume" quarantine
verify_volume "$active_volume" active

postgres_container="$("${compose[@]}" ps -q c19-asset-postgres 2>/dev/null || true)"
api_container="$("${compose[@]}" ps -q c19-asset-api 2>/dev/null || true)"
worker_container="$("${compose[@]}" ps -q c19-asset-worker 2>/dev/null || true)"
gateway_container="$("${compose[@]}" ps -q c19-asset-gateway 2>/dev/null || true)"
[[ -n "$postgres_container" ]] || fail "The Asset PostgreSQL container does not exist."
[[ -n "$api_container" ]] || fail "The Asset API container does not exist."
[[ -n "$worker_container" ]] || fail "The Asset worker container does not exist."
[[ -n "$gateway_container" ]] || fail "The Asset gateway container does not exist."

verify_mount() {
    local container="$1"
    local destination="$2"
    local expected_volume="$3"
    local identity
    identity="$(
        docker inspect --format \
            "{{range .Mounts}}{{if eq .Destination \"${destination}\"}}{{printf \"%s\\t%s\" .Type .Name}}{{end}}{{end}}" \
            "$container"
    )" || fail "Could not inspect a required container mount."
    local mount_type
    local mounted_volume
    IFS=$'\t' read -r mount_type mounted_volume <<<"$identity"
    [[ "$mount_type" == volume && "$mounted_volume" == "$expected_volume" ]] || \
        fail "Container mount $destination is not the confirmed volume $expected_volume."
}

verify_mount "$postgres_container" /var/lib/postgresql/data "$postgres_volume"
verify_mount "$worker_container" /var/lib/c19-assets/active "$active_volume"

validate_asset_v3_catalog() {
    local retention_columns
    local retention_constraints
    local retention_indexes
    local column_name
    local constraint_identity
    revision="$(
        "${compose[@]}" exec -T c19-asset-postgres sh -ec \
            'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --tuples-only --no-align --command="select version_num from alembic_version limit 1"'
    )"
    [[ "$revision" =~ ^[A-Za-z0-9_.-]+$ ]] || fail "Could not read Asset Alembic revision."
    [[ "$revision" == "$required_revision" ]] || \
        fail "C19 Asset backup requires Alembic revision $required_revision."
    retention_columns="$(
        "${compose[@]}" exec -T c19-asset-postgres psql \
            --username="$target_user" \
            --dbname="$target_db" \
            --tuples-only \
            --no-align \
            --set=ON_ERROR_STOP=1 \
            --command="select column_name from information_schema.columns where table_schema = 'public' and table_name = 'chat_assets' order by column_name"
    )" || fail "Could not validate the C19 Asset v3 source columns."
    for column_name in retention_operation_id retention_record_id retention_conversation_id retention_prepared_at; do
        grep -Fxq "$column_name" <<<"$retention_columns" || \
            fail "C19 Asset v3 backup source is missing required column $column_name."
    done
    retention_constraints="$(
        "${compose[@]}" exec -T c19-asset-postgres psql \
            --username="$target_user" \
            --dbname="$target_db" \
            --tuples-only \
            --no-align \
            --set=ON_ERROR_STOP=1 \
            --command="select table_record.relname || ':' || constraint_record.conname || ':' || constraint_record.contype::text from pg_constraint as constraint_record join pg_class as table_record on table_record.oid = constraint_record.conrelid join pg_namespace as schema_record on schema_record.oid = table_record.relnamespace where schema_record.nspname = 'public' and table_record.relname = 'chat_assets' and constraint_record.convalidated order by constraint_record.conname"
    )" || fail "Could not validate the C19 Asset v3 source constraints."
    for constraint_identity in \
        "chat_assets:ck_chat_assets_retention_preparation_consistent:c" \
        "chat_assets:uq_chat_assets_retention_operation_id:u"; do
        grep -Fxq "$constraint_identity" <<<"$retention_constraints" || \
            fail "C19 Asset v3 backup source is missing validated constraint $constraint_identity."
    done
    retention_indexes="$(
        "${compose[@]}" exec -T c19-asset-postgres psql \
            --username="$target_user" \
            --dbname="$target_db" \
            --tuples-only \
            --no-align \
            --set=ON_ERROR_STOP=1 \
            --command="select table_record.relname || ':' || index_record.relname from pg_index as index_state join pg_class as index_record on index_record.oid = index_state.indexrelid join pg_class as table_record on table_record.oid = index_state.indrelid join pg_namespace as schema_record on schema_record.oid = table_record.relnamespace where schema_record.nspname = 'public' and table_record.relname = 'chat_assets' and index_state.indisvalid and index_state.indisready order by index_record.relname"
    )" || fail "Could not validate the C19 Asset v3 source indexes."
    grep -Fxq "chat_assets:ix_chat_assets_retention_prepared_at" <<<"$retention_indexes" || \
        fail "C19 Asset v3 backup source is missing ready index ix_chat_assets_retention_prepared_at."
}

validate_asset_v3_catalog

post_backup_state="resume-writers"
[[ "$leave_stopped" == 0 ]] || post_backup_state="leave-writers-stopped"
confirmation="${dataset_id}/${project_name}/${target_db}/${postgres_volume}/${active_volume}/${private_network}/${clam_egress_network}/${gateway_ingress_network}/${client_network}/${post_backup_state}"
printf 'C19 asset backup plan\n'
printf 'dataset_id: %s\n' "$dataset_id"
printf 'project: %s\n' "$project_name"
printf 'postgres_volume: %s\n' "$postgres_volume"
printf 'active_volume: %s\n' "$active_volume"
printf 'gateway_ingress_network: %s\n' "$gateway_ingress_network"
printf 'incoming_and_quarantine_included: no\n'
printf 'post_backup_writer_state: %s\n' "$post_backup_state"
printf 'required_confirmation: %s\n' "$confirmation"
if [[ "$mode" == dry-run ]]; then
    exit 0
fi
[[ "${CONFIRM_C19_ASSET_BACKUP:-}" == "$confirmation" ]] || \
    fail "CONFIRM_C19_ASSET_BACKUP does not match the printed plan."

[[ ! -L "$output_dir" ]] || fail "Backup output directory must not be a symlink."
mkdir -p "$output_dir"
chmod 700 "$output_dir"
lock_dir="${C19_ASSET_LOCK_DIR:-${output_dir}/.locks}"
[[ ! -L "$lock_dir" ]] || fail "Backup lock directory must not be a symlink."
mkdir -p "$lock_dir"
chmod 700 "$lock_dir"
lock_file="${lock_dir}/${dataset_id}.lock"
[[ ! -L "$lock_file" ]] || fail "Backup lock file must not be a symlink."
exec 9>"$lock_file"
chmod 600 "$lock_file"
flock -n 9 || fail "Another asset backup or restore owns dataset $dataset_id."

service_was_running() {
    local service="$1"
    local container
    container="$("${compose[@]}" ps -q "$service" 2>/dev/null || true)"
    [[ -n "$container" ]] || return 1
    [[ "$(docker inspect --format '{{.State.Running}}' "$container")" == true ]]
}

worker_running=0
api_running=0
gateway_running=0
service_was_running c19-asset-worker && worker_running=1
service_was_running c19-asset-api && api_running=1
service_was_running c19-asset-gateway && gateway_running=1
[[ "$worker_running" == 1 && "$api_running" == 1 && "$gateway_running" == 1 ]] || \
    fail "API, worker, and gateway must all be healthy/running before a coordinated backup."

services_quiesced=0
resume_services() {
    local result=0
    [[ "$services_quiesced" == 1 ]] || return 0
    [[ "$leave_stopped" == 0 ]] || return 0

    [[ "$api_running" == 0 ]] || "${compose[@]}" start c19-asset-api || result=1
    [[ "$worker_running" == 0 ]] || "${compose[@]}" start c19-asset-worker || result=1
    [[ "$gateway_running" == 0 ]] || "${compose[@]}" start c19-asset-gateway || result=1
    if [[ "$result" == 0 ]]; then
        for container in "$api_container" "$worker_container" "$gateway_container"; do
            [[ "$(docker inspect --format '{{.State.Running}}' "$container")" == true ]] || \
                result=1
        done
    fi
    [[ "$result" != 0 ]] || services_quiesced=0
    return "$result"
}

backup_exit_cleanup() {
    local exit_code=$?
    local shutdown_result=0
    trap - EXIT INT TERM HUP
    if [[ "$services_quiesced" == 1 && "$leave_stopped" == 0 ]]; then
        if ! resume_services; then
            printf '%s\n' \
                'C19 asset backup cleanup warning: one or more source services require manual restart.' \
                >&2
            [[ "$exit_code" != 0 ]] || exit_code=1
        fi
    elif [[ "$services_quiesced" == 1 && "$leave_stopped" == 1 && "$exit_code" != 0 ]]; then
        "${compose[@]}" stop -t 30 c19-asset-gateway c19-asset-api \
            >/dev/null 2>&1 || shutdown_result=1
        "${compose[@]}" stop -t 180 c19-asset-worker \
            >/dev/null 2>&1 || shutdown_result=1
        for container in "$api_container" "$worker_container" "$gateway_container"; do
            [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null || true)" == false ]] || \
                shutdown_result=1
        done
        if [[ "$shutdown_result" == 0 ]]; then
            printf '%s\n' \
                'C19 asset backup failed in --leave-stopped mode; source writers remain stopped by design.' \
                >&2
        else
            printf '%s\n' \
                'C19 asset backup failed and a source writer may still be running; keep ingress closed and intervene manually.' \
                >&2
        fi
    fi
    exit "$exit_code"
}
trap backup_exit_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

assert_container_stopped() {
    local container="$1"
    local service="$2"
    [[ "$(docker inspect --format '{{.State.Running}}' "$container")" == false ]] || \
        fail "$service is still running after the coordinated stop."
}

# Close both ingress paths before asking the worker to stop. The worker's
# SIGTERM handler completes its current run_once DB/filesystem transition.
services_quiesced=1
"${compose[@]}" stop -t 30 c19-asset-gateway c19-asset-api
assert_container_stopped "$gateway_container" c19-asset-gateway
assert_container_stopped "$api_container" c19-asset-api

drain_deadline=$((SECONDS + drain_timeout_seconds))
while true; do
    drain_blockers="$(
        "${compose[@]}" exec -T c19-asset-worker python \
            -m c19_asset_service.consistency --drain-blocker-count
    )" || fail "Could not read the worker drain state."
    [[ "$drain_blockers" =~ ^[0-9]+$ ]] || \
        fail "Worker drain state returned an invalid result."
    [[ "$drain_blockers" != 0 ]] || break
    [[ "$(docker inspect --format '{{.State.Running}}' "$worker_container")" == true ]] || \
        fail "Asset worker exited before the portable queue drained."
    (( SECONDS < drain_deadline )) || \
        fail "Asset worker did not drain portable transitions before the timeout."
    sleep 1
done

"${compose[@]}" stop -t 180 c19-asset-worker
assert_container_stopped "$worker_container" c19-asset-worker
"${compose[@]}" exec -T c19-asset-postgres sh -ec \
    'pg_isready --quiet --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' || \
    fail "Asset PostgreSQL is not ready after writers stopped."

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
base="$output_dir/c19_assets_${timestamp}"
dump="$base.dump"
objects="$base.objects.tar"
manifest="$base.manifest"
metadata="$base.metadata"
dump_tmp="$dump.tmp"
objects_tmp="$objects.tmp"
manifest_tmp="$manifest.tmp"
metadata_tmp="$metadata.tmp"
umask 077

validate_asset_v3_catalog

"${compose[@]}" exec -T c19-asset-postgres sh -ec \
    'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --compress=9 --no-owner --no-privileges' \
    >"$dump_tmp"

# This single read-only gate renders the manifest only after proving exact
# DB(active_object_key/thumbnail_object_key,size,SHA) <-> filesystem equality.
"${compose[@]}" run -T --rm --no-deps --entrypoint python c19-asset-worker \
    -m c19_asset_service.consistency >"$manifest_tmp"

archive_program=$'from pathlib import Path\nimport os, sys, tarfile\nroot=Path(os.environ["C19_ASSET_ACTIVE_ROOT"]).resolve()\nwith tarfile.open(fileobj=sys.stdout.buffer, mode="w|", format=tarfile.PAX_FORMAT) as archive:\n    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):\n        if path.is_symlink(): raise SystemExit("symlink in active root")\n        if path.is_dir(): continue\n        if not path.is_file(): raise SystemExit("non-file in active root")\n        rel=path.relative_to(root).as_posix()\n        info=archive.gettarinfo(str(path), arcname=rel)\n        info.uid=0; info.gid=0; info.uname=""; info.gname=""; info.mtime=0; info.mode=0o600\n        with path.open("rb") as handle: archive.addfile(info, handle)'
"${compose[@]}" run -T --rm --no-deps --entrypoint python c19-asset-worker \
    -c "$archive_program" >"$objects_tmp"

object_count="$(awk 'END {print NR + 0}' "$manifest_tmp")"
object_bytes="$(awk -F '\t' '{total += $2} END {printf "%.0f", total + 0}' "$manifest_tmp")"
dump_sha256="$(sha256sum "$dump_tmp" | awk '{print $1}')"
objects_sha256="$(sha256sum "$objects_tmp" | awk '{print $1}')"
manifest_sha256="$(sha256sum "$manifest_tmp" | awk '{print $1}')"

{
    printf 'created_at=%s\n' "$timestamp"
    printf 'source_dataset_id=%s\n' "$dataset_id"
    printf 'alembic_revision=%s\n' "$revision"
    printf 'blob_format_revision=1\n'
    printf 'database_format=pg_dump_custom\n'
    printf 'object_archive_format=posix_tar\n'
    printf 'object_count=%s\n' "$object_count"
    printf 'object_bytes=%s\n' "$object_bytes"
    printf 'database_sha256=%s\n' "$dump_sha256"
    printf 'objects_sha256=%s\n' "$objects_sha256"
    printf 'manifest_sha256=%s\n' "$manifest_sha256"
} >"$metadata_tmp"

mv "$dump_tmp" "$dump"
mv "$objects_tmp" "$objects"
mv "$manifest_tmp" "$manifest"
mv "$metadata_tmp" "$metadata"
chmod 600 "$dump" "$objects" "$manifest" "$metadata"

if [[ "$leave_stopped" == 0 ]]; then
    resume_services || fail "Backup completed but one or more asset services did not restart."
fi
trap - EXIT INT TERM HUP

printf 'C19 asset backup completed\n'
printf 'database: %s\n' "$dump"
printf 'objects: %s\n' "$objects"
printf 'manifest: %s\n' "$manifest"
printf 'metadata: %s\n' "$metadata"
printf 'dataset_id: %s\n' "$dataset_id"
printf 'alembic_revision: %s\n' "$revision"
printf 'object_count: %s\n' "$object_count"
printf 'object_bytes: %s\n' "$object_bytes"
printf 'source_writers_running: %s\n' "$([[ "$leave_stopped" == 0 ]] && printf yes || printf no)"
