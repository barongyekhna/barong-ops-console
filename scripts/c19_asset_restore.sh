#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

compose_file="${C19_ASSET_COMPOSE_FILE:-docker-compose.c19-asset.yml}"
project_name="${C19_ASSET_COMPOSE_PROJECT:-c19-asset-restore}"
env_file="${C19_ASSET_ENV_FILE:-.env.c19-asset.production}"
postgres_volume="${C19_ASSET_POSTGRES_VOLUME_NAME:-c19_asset_restore_postgres}"
incoming_volume="${C19_ASSET_INCOMING_VOLUME_NAME:-c19_asset_restore_incoming}"
quarantine_volume="${C19_ASSET_QUARANTINE_VOLUME_NAME:-c19_asset_restore_quarantine}"
active_volume="${C19_ASSET_ACTIVE_VOLUME_NAME:-c19_asset_restore_active}"
private_network="${C19_ASSET_PRIVATE_NETWORK_NAME:-c19-asset-restore-private}"
clam_egress_network="${C19_ASSET_CLAM_EGRESS_NETWORK_NAME:-c19-asset-restore-clam-egress}"
gateway_ingress_network="${C19_ASSET_GATEWAY_INGRESS_NETWORK_NAME:-c19-asset-restore-gateway-ingress}"
client_network="${BARONG_SHARED_NETWORK_NAME:-c19-asset-restore-client}"
metadata=""
mode="dry-run"
required_revision="c19_asset_20260712_03"

fail() {
    printf 'C19 asset restore failed: %s\n' "$1" >&2
    exit 1
}

usage() {
    printf '%s\n' \
        'Usage:' \
        '  ./scripts/c19_asset_restore.sh --metadata backups/c19-asset/c19_assets_YYYY.metadata --dry-run' \
        '  CONFIRM_C19_ASSET_RESTORE=<printed-value> ./scripts/c19_asset_restore.sh --metadata FILE --execute' \
        '' \
        'Execution is restricted to an isolated project/network and fresh,' \
        'dataset-labelled object volumes. It never connects a production writer.'
}

metadata_value() {
    local key="$1"
    awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2); exit}' "$metadata" | tr -d '\r'
}

env_value() {
    local key="$1"
    awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2); exit}' "$env_file" | tr -d '\r'
}

require_unique_key() {
    local file="$1"
    local key="$2"
    local count
    local canonical_count
    count="$(awk -v key="$key" '$0 ~ "^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=" {count += 1} END {print count + 0}' "$file")"
    canonical_count="$(awk -v key="$key" '$0 ~ ("^" key "=") {count += 1} END {print count + 0}' "$file")"
    [[ "$count" == 1 && "$canonical_count" == 1 ]] || \
        fail "$key must appear once in $file using exact KEY=value syntax."
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --metadata)
            [[ $# -ge 2 ]] || fail "--metadata requires a value."
            metadata="$2"
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

[[ -n "$metadata" ]] || fail "--metadata is required."
[[ "$metadata" == *.metadata ]] || fail "Metadata path must end in .metadata."
[[ -f "$metadata" && ! -L "$metadata" ]] || fail "Metadata must be a regular non-symlink file."
base="${metadata%.metadata}"
dump="$base.dump"
objects="$base.objects.tar"
manifest="$base.manifest"
for file in "$dump" "$objects" "$manifest"; do
    [[ -f "$file" && ! -L "$file" ]] || fail "Backup member is missing or unsafe: $file"
done
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
command -v cmp >/dev/null 2>&1 || fail "cmp is required."

metadata_keys=(
    created_at source_dataset_id alembic_revision blob_format_revision
    database_format object_archive_format object_count object_bytes
    database_sha256 objects_sha256 manifest_sha256
)
for key in "${metadata_keys[@]}"; do
    require_unique_key "$metadata" "$key"
done

source_dataset="$(metadata_value source_dataset_id)"
expected_revision="$(metadata_value alembic_revision)"
blob_revision="$(metadata_value blob_format_revision)"
database_format="$(metadata_value database_format)"
object_format="$(metadata_value object_archive_format)"
expected_count="$(metadata_value object_count)"
expected_bytes="$(metadata_value object_bytes)"
expected_dump_sha="$(metadata_value database_sha256)"
expected_objects_sha="$(metadata_value objects_sha256)"
expected_manifest_sha="$(metadata_value manifest_sha256)"

[[ "$source_dataset" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$ ]] || \
    fail "Backup metadata has an invalid dataset ID."
[[ "$expected_revision" =~ ^[A-Za-z0-9_.-]+$ ]] || \
    fail "Backup metadata has an invalid Alembic revision."
[[ "$expected_revision" == "$required_revision" ]] || \
    fail "Asset restore requires Alembic revision $required_revision."
[[ "$blob_revision" == 1 ]] || fail "Unsupported blob format revision."
[[ "$database_format" == pg_dump_custom ]] || fail "Unsupported database archive format."
[[ "$object_format" == posix_tar ]] || fail "Unsupported object archive format."
[[ "$expected_count" =~ ^[0-9]+$ && "$expected_bytes" =~ ^[0-9]+$ ]] || \
    fail "Backup metadata has invalid object totals."
for value in "$expected_dump_sha" "$expected_objects_sha" "$expected_manifest_sha"; do
    [[ "$value" =~ ^[0-9a-f]{64}$ ]] || fail "Backup metadata has an invalid SHA-256."
done
[[ "$(sha256sum "$dump" | awk '{print $1}')" == "$expected_dump_sha" ]] || \
    fail "Database archive checksum does not match metadata."
[[ "$(sha256sum "$objects" | awk '{print $1}')" == "$expected_objects_sha" ]] || \
    fail "Object archive checksum does not match metadata."
[[ "$(sha256sum "$manifest" | awk '{print $1}')" == "$expected_manifest_sha" ]] || \
    fail "Object manifest checksum does not match metadata."

validation="$(python3 - "$manifest" "$objects" <<'PY'
import hashlib
import pathlib
import re
import sys
import tarfile

manifest_path = pathlib.Path(sys.argv[1])
archive_path = pathlib.Path(sys.argv[2])
manifest = {}
count = 0
total = 0
for raw in manifest_path.read_text(encoding="utf-8").splitlines():
    parts = raw.split("\t")
    if len(parts) != 3 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
        raise SystemExit("invalid manifest row")
    if not parts[1].isdigit():
        raise SystemExit("invalid manifest size")
    path = pathlib.PurePosixPath(parts[2])
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise SystemExit("unsafe manifest path")
    if any("\x00" in item or "\r" in item or "\n" in item or "\t" in item for item in path.parts):
        raise SystemExit("unsafe manifest path")
    normalized = path.as_posix()
    if re.fullmatch(r"[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{28}", normalized) is None:
        raise SystemExit("invalid manifest object key")
    if normalized in manifest:
        raise SystemExit("duplicate manifest path")
    size = int(parts[1])
    manifest[normalized] = (parts[0], size)
    count += 1
    total += size

archive_files = {}
with tarfile.open(archive_path, mode="r:") as archive:
    for member in archive.getmembers():
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
            raise SystemExit("unsafe archive path")
        normalized = path.as_posix()
        if re.fullmatch(r"[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{28}", normalized) is None:
            raise SystemExit("invalid archive object key")
        if member.isdir():
            continue
        if not member.isfile() or member.issym() or member.islnk() or member.isdev():
            raise SystemExit("unsupported archive member")
        if normalized in archive_files:
            raise SystemExit("duplicate archive path")
        archive_files[normalized] = member.size
if set(archive_files) != set(manifest):
    raise SystemExit("archive and manifest paths differ")
for path, size in archive_files.items():
    if manifest[path][1] != size:
        raise SystemExit("archive and manifest sizes differ")
print(f"{count}\t{total}")
PY
)" || fail "Object archive or manifest validation failed."
IFS=$'\t' read -r actual_count actual_bytes <<<"$validation"
[[ "$actual_count" == "$expected_count" && "$actual_bytes" == "$expected_bytes" ]] || \
    fail "Object totals do not match metadata."

env_keys=(
    C19_ASSET_DATASET_ID POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
    C19_ASSET_DATABASE_URL C19_ASSET_SERVICE_TOKEN C19_ASSET_GATEWAY_TOKEN
    C19_ASSET_INCOMING_ROOT C19_ASSET_QUARANTINE_ROOT C19_ASSET_ACTIVE_ROOT
)
for key in "${env_keys[@]}"; do
    require_unique_key "$env_file" "$key"
done
target_dataset="$(env_value C19_ASSET_DATASET_ID)"
target_db="$(env_value POSTGRES_DB)"
target_user="$(env_value POSTGRES_USER)"
target_password="$(env_value POSTGRES_PASSWORD)"
database_url="$(env_value C19_ASSET_DATABASE_URL)"
service_token="$(env_value C19_ASSET_SERVICE_TOKEN)"
gateway_token="$(env_value C19_ASSET_GATEWAY_TOKEN)"
[[ "$target_dataset" == "$source_dataset" ]] || \
    fail "Target dataset ID does not match the backup dataset ID."
[[ "$target_db" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail "Target POSTGRES_DB is invalid."
[[ "$target_user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail "Target POSTGRES_USER is invalid."
[[ -n "$target_password" && "${target_password^^}" != *CHANGE-ME* ]] || \
    fail "Target PostgreSQL password is missing or a placeholder."
for secret in "$service_token" "$gateway_token"; do
    [[ ${#secret} -ge 32 && "${secret^^}" != *CHANGE-ME* ]] || \
        fail "Every target service secret must be at least 32 characters and contain no placeholder."
done

url_identity="$(
    printf '%s' "$database_url" | python3 -c 'import sys; from urllib.parse import unquote, urlsplit; u=urlsplit(sys.stdin.read()); print("\t".join((u.scheme, u.hostname or "", str(u.port or 5432), unquote(u.username or ""), unquote(u.password or ""), u.path.lstrip("/"), u.query, u.fragment)))'
)" || fail "C19_ASSET_DATABASE_URL could not be parsed."
IFS=$'\t' read -r url_scheme url_host url_port url_user url_password url_db url_query url_fragment <<<"$url_identity"
[[ "$url_scheme" == postgresql+psycopg \
    && "$url_host" == c19-asset-postgres \
    && "$url_port" == 5432 \
    && "$url_user" == "$target_user" \
    && "$url_password" == "$target_password" \
    && "$url_db" == "$target_db" \
    && -z "$url_query" && -z "$url_fragment" ]] || \
    fail "C19_ASSET_DATABASE_URL must identify this stack's PostgreSQL service exactly."

for value in \
    "$project_name" "$postgres_volume" "$incoming_volume" "$quarantine_volume" \
    "$active_volume" "$private_network" "$clam_egress_network" \
    "$gateway_ingress_network" "$client_network"; do
    [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || \
        fail "A project, volume, or network name is invalid."
done
[[ "$project_name" != c19-asset ]] || fail "Restore execution requires an isolated project name."
[[ "$private_network" != c19-asset-private ]] || fail "Restore requires an isolated private network."
[[ "$clam_egress_network" != c19-asset-clam-egress ]] || \
    fail "Restore requires an isolated ClamAV update-egress network."
[[ "$gateway_ingress_network" != c19-asset-gateway-ingress ]] || \
    fail "Restore requires an isolated gateway loopback-ingress network."
[[ "$client_network" != barong-ops-console-prod ]] || fail "Restore must not join the production client network."
for value in "$postgres_volume" "$incoming_volume" "$quarantine_volume" "$active_volume"; do
    [[ "$value" == *restore* || "$value" == *rehearsal* ]] || \
        fail "Restore volume names must explicitly contain restore or rehearsal."
done

confirmation="${source_dataset}/${expected_dump_sha}/${expected_objects_sha}/${project_name}/${target_db}/${postgres_volume}/${active_volume}/${private_network}/${clam_egress_network}/${gateway_ingress_network}/${client_network}"
printf 'C19 asset restore plan\n'
printf 'source_dataset_id: %s\n' "$source_dataset"
printf 'alembic_revision: %s\n' "$expected_revision"
printf 'object_count: %s\n' "$expected_count"
printf 'object_bytes: %s\n' "$expected_bytes"
printf 'target_project: %s\n' "$project_name"
printf 'target_active_volume: %s\n' "$active_volume"
printf 'target_clam_egress_network: %s\n' "$clam_egress_network"
printf 'target_gateway_ingress_network: %s\n' "$gateway_ingress_network"
printf 'target_client_network: %s\n' "$client_network"
printf 'required_confirmation: %s\n' "$confirmation"
if [[ "$mode" == dry-run ]]; then
    exit 0
fi
[[ "${CONFIRM_C19_ASSET_RESTORE:-}" == "$confirmation" ]] || \
    fail "CONFIRM_C19_ASSET_RESTORE does not match the printed plan."

export C19_ASSET_ENV_FILE="$env_file"
export C19_ASSET_DATASET_ID="$target_dataset"
export C19_ASSET_POSTGRES_VOLUME_NAME="$postgres_volume"
export C19_ASSET_INCOMING_VOLUME_NAME="$incoming_volume"
export C19_ASSET_QUARANTINE_VOLUME_NAME="$quarantine_volume"
export C19_ASSET_ACTIVE_VOLUME_NAME="$active_volume"
export C19_ASSET_PRIVATE_NETWORK_NAME="$private_network"
export C19_ASSET_CLAM_EGRESS_NETWORK_NAME="$clam_egress_network"
export C19_ASSET_GATEWAY_INGRESS_NETWORK_NAME="$gateway_ingress_network"
export BARONG_SHARED_NETWORK_NAME="$client_network"
compose=("${compose_cli[@]}" -p "$project_name" -f "$compose_file")

lock_dir="${C19_ASSET_LOCK_DIR:-${repo_root}/backups/c19-asset/.locks}"
[[ ! -L "$lock_dir" ]] || fail "Restore lock directory must not be a symlink."
mkdir -p "$lock_dir"
chmod 700 "$lock_dir"
lock_file="${lock_dir}/${target_dataset}.lock"
[[ ! -L "$lock_file" ]] || fail "Restore lock file must not be a symlink."
exec 9>"$lock_file"
chmod 600 "$lock_file"
flock -n 9 || fail "Another backup or restore owns dataset $target_dataset."

for service in c19-asset-api c19-asset-worker c19-asset-gateway; do
    container="$("${compose[@]}" ps -q "$service" 2>/dev/null || true)"
    if [[ -n "$container" && "$(docker inspect --format '{{.State.Running}}' "$container")" == true ]]; then
        fail "Target $service is already running; restore requires no target writers."
    fi
done

"${compose[@]}" up -d c19-asset-postgres
postgres_container="$("${compose[@]}" ps -q c19-asset-postgres 2>/dev/null || true)"
[[ -n "$postgres_container" ]] || fail "Target PostgreSQL container did not start."
for attempt in $(seq 1 40); do
    if "${compose[@]}" exec -T c19-asset-postgres sh -ec \
        'pg_isready --quiet --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"'; then
        break
    fi
    [[ "$attempt" != 40 ]] || fail "Target PostgreSQL did not become ready."
    sleep 1
done
"${compose[@]}" run -T --rm --no-deps c19-asset-volume-init || \
    fail "Target object-volume ownership initialization failed."

verify_volume() {
    local volume="$1"
    local role="$2"
    local labels
    labels="$(docker volume inspect --format '{{index .Labels "com.barong.c19.asset-dataset-id"}}{{printf "\t"}}{{index .Labels "com.barong.c19.asset-volume-role"}}' "$volume")" || \
        fail "Could not inspect target volume $volume."
    local actual_dataset
    local actual_role
    IFS=$'\t' read -r actual_dataset actual_role <<<"$labels"
    [[ "$actual_dataset" == "$target_dataset" && "$actual_role" == "$role" ]] || \
        fail "Target volume $volume has the wrong dataset or role label."
}
verify_volume "$postgres_volume" metadata
verify_volume "$incoming_volume" incoming
verify_volume "$quarantine_volume" quarantine
verify_volume "$active_volume" active

empty_check=$'from pathlib import Path\nimport os\nfor key in ("C19_ASSET_INCOMING_ROOT","C19_ASSET_QUARANTINE_ROOT","C19_ASSET_ACTIVE_ROOT"):\n p=Path(os.environ[key]); p.mkdir(parents=True, exist_ok=True)\n if any(p.iterdir()): raise SystemExit(f"{key} is not empty")'
"${compose[@]}" run -T --rm --no-deps --entrypoint python c19-asset-worker -c "$empty_check" || \
    fail "Incoming, quarantine, and active target volumes must all be empty."

target_asset_schema="$(
    "${compose[@]}" exec -T c19-asset-postgres psql \
        --username="$target_user" --dbname="$target_db" --tuples-only --no-align \
        --set=ON_ERROR_STOP=1 \
        --command="select (to_regclass('public.chat_assets') is not null)::text"
)"
[[ "$target_asset_schema" == false ]] || \
    fail "Restore requires a fresh target PostgreSQL database with no Asset schema."

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
restore_db="c19_restore_${timestamp//[^0-9]/}"
rollback_db="c19_rollback_${timestamp//[^0-9]/}"
failed_db="c19_failed_${timestamp//[^0-9]/}"
"${compose[@]}" exec -T c19-asset-postgres psql \
    --username="$target_user" --dbname=postgres --set=ON_ERROR_STOP=1 \
    --command="CREATE DATABASE \"$restore_db\" OWNER \"$target_user\" TEMPLATE template0"
"${compose[@]}" exec -T c19-asset-postgres pg_restore \
    --username="$target_user" --dbname="$restore_db" --exit-on-error \
    --no-owner --no-privileges <"$dump"
restored_revision="$(
    "${compose[@]}" exec -T c19-asset-postgres psql \
        --username="$target_user" --dbname="$restore_db" --tuples-only --no-align \
        --set=ON_ERROR_STOP=1 --command='select version_num from alembic_version limit 1'
)"
[[ "$restored_revision" == "$expected_revision" ]] || \
    fail "Restored database revision does not match backup metadata."
retention_columns="$(
    "${compose[@]}" exec -T c19-asset-postgres psql \
        --username="$target_user" --dbname="$restore_db" --tuples-only --no-align \
        --set=ON_ERROR_STOP=1 \
        --command="select column_name from information_schema.columns where table_schema = 'public' and table_name = 'chat_assets' order by column_name"
)"
for column_name in retention_operation_id retention_record_id retention_conversation_id retention_prepared_at; do
    grep -Fxq "$column_name" <<<"$retention_columns" || \
        fail "Restored Asset retention fence is missing column $column_name."
done
retention_constraints="$(
    "${compose[@]}" exec -T c19-asset-postgres psql \
        --username="$target_user" --dbname="$restore_db" --tuples-only --no-align \
        --set=ON_ERROR_STOP=1 \
        --command="select table_record.relname || ':' || constraint_record.conname || ':' || constraint_record.contype from pg_constraint as constraint_record join pg_class as table_record on table_record.oid = constraint_record.conrelid join pg_namespace as schema_record on schema_record.oid = table_record.relnamespace where schema_record.nspname = 'public' and table_record.relname = 'chat_assets' and constraint_record.convalidated order by constraint_record.conname"
)"
for constraint_identity in \
    "chat_assets:ck_chat_assets_retention_preparation_consistent:c" \
    "chat_assets:uq_chat_assets_retention_operation_id:u"; do
    grep -Fxq "$constraint_identity" <<<"$retention_constraints" || \
        fail "Restored Asset retention fence is missing validated constraint $constraint_identity."
done
retention_indexes="$(
    "${compose[@]}" exec -T c19-asset-postgres psql \
        --username="$target_user" --dbname="$restore_db" --tuples-only --no-align \
        --set=ON_ERROR_STOP=1 \
        --command="select table_record.relname || ':' || index_record.relname from pg_index as index_state join pg_class as index_record on index_record.oid = index_state.indexrelid join pg_class as table_record on table_record.oid = index_state.indrelid join pg_namespace as schema_record on schema_record.oid = table_record.relnamespace where schema_record.nspname = 'public' and table_record.relname = 'chat_assets' and index_state.indisvalid and index_state.indisready order by index_record.relname"
)"
grep -Fxq "chat_assets:ix_chat_assets_retention_prepared_at" <<<"$retention_indexes" || \
    fail "Restored Asset retention fence is missing index ix_chat_assets_retention_prepared_at."

# Incoming/quarantine bytes and raw transfer locators are deliberately not
# portable. Keep pending destination keys so clients may re-upload, clear only
# absent quarantine locations, and revoke every pre-move ticket hash.
"${compose[@]}" exec -T c19-asset-postgres psql \
    --username="$target_user" --dbname="$restore_db" --set=ON_ERROR_STOP=1 <<'SQL'
BEGIN;
UPDATE chat_assets
SET quarantine_object_key = NULL
WHERE quarantine_object_key IS NOT NULL;
UPDATE asset_transfer_tickets
SET revoked_at = CURRENT_TIMESTAMP
WHERE revoked_at IS NULL;
COMMIT;
SQL

extract_program=$'from pathlib import Path, PurePosixPath\nimport os, shutil, sys, tarfile, uuid\nroot=Path(os.environ["C19_ASSET_ACTIVE_ROOT"]).resolve()\nwith tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as archive:\n for member in archive:\n  rel=PurePosixPath(member.name)\n  if rel.is_absolute() or not rel.parts or ".." in rel.parts or "." in rel.parts: raise SystemExit("unsafe path")\n  if member.isdir(): continue\n  if not member.isfile() or member.issym() or member.islnk() or member.isdev(): raise SystemExit("unsafe member")\n  target=root.joinpath(*rel.parts)\n  target.parent.mkdir(parents=True, exist_ok=True)\n  if target.exists(): raise SystemExit("duplicate target")\n  temp=target.with_name(target.name+".restore-"+uuid.uuid4().hex)\n  source=archive.extractfile(member)\n  if source is None: raise SystemExit("missing member stream")\n  with temp.open("xb") as output: shutil.copyfileobj(source, output, 1024*1024)\n  os.chmod(temp, 0o600); os.replace(temp, target)'
"${compose[@]}" run -T --rm --no-deps --entrypoint python c19-asset-worker \
    -c "$extract_program" <"$objects"

verify_manifest="$(mktemp "${TMPDIR:-/tmp}/c19-asset-manifest.XXXXXX")"
database_swapped=0
swap_in_progress=0

database_exists() {
    local database_name="$1"
    "${compose[@]}" exec -T c19-asset-postgres psql \
        --username="$target_user" --dbname=postgres --tuples-only --no-align \
        --set=ON_ERROR_STOP=1 \
        --command="select exists(select 1 from pg_database where datname = '$database_name')::text"
}

resolve_swap_state() {
    local target_state
    local rollback_state
    local restore_state
    target_state="$(database_exists "$target_db")" || return 1
    rollback_state="$(database_exists "$rollback_db")" || return 1
    restore_state="$(database_exists "$restore_db")" || return 1
    if [[ "$target_state" == true && "$rollback_state" == true && "$restore_state" == false ]]; then
        database_swapped=1
        swap_in_progress=0
        return 0
    fi
    if [[ "$target_state" == true && "$rollback_state" == false && "$restore_state" == true ]]; then
        database_swapped=0
        swap_in_progress=0
        return 0
    fi
    return 1
}

rollback_database_swap() {
    "${compose[@]}" stop -t 30 c19-asset-api >/dev/null 2>&1 || true
    if ! "${compose[@]}" exec -T c19-asset-postgres psql \
        --username="$target_user" --dbname=postgres --set=ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$target_db', '$rollback_db') AND pid <> pg_backend_pid();
BEGIN;
ALTER DATABASE "$target_db" RENAME TO "$failed_db";
ALTER DATABASE "$rollback_db" RENAME TO "$target_db";
COMMIT;
SQL
    then
        return 1
    fi
    database_swapped=0
    swap_in_progress=0
    return 0
}

restore_exit_cleanup() {
    local exit_code=$?
    local rollback_required="$database_swapped"
    trap - EXIT INT TERM HUP
    rm -f "$verify_manifest"
    if [[ "$exit_code" != 0 && "$swap_in_progress" == 1 ]]; then
        if resolve_swap_state; then
            rollback_required="$database_swapped"
        else
            printf '%s\n' \
                'C19 asset restore cleanup warning: database swap state is ambiguous; API remains stopped for manual recovery.' \
                >&2
            exit "$exit_code"
        fi
    fi
    if [[ "$exit_code" != 0 && "$rollback_required" == 1 ]]; then
        if rollback_database_swap; then
            printf '%s\n' \
                'C19 asset restore failed after activation; the pristine target database name was restored automatically.' \
                >&2
        else
            printf '%s\n' \
                'C19 asset restore rollback failed; API remains stopped and manual database recovery is required.' \
                >&2
        fi
    fi
    exit "$exit_code"
}
trap restore_exit_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# Verify the restored temporary DB against the restored active volume before
# any database name can be switched. The emitted manifest is already the exact
# DB<->filesystem intersection, so comparing it also proves source equivalence.
"${compose[@]}" run -T --rm --no-deps --entrypoint python c19-asset-worker \
    -m c19_asset_service.consistency --database-name "$restore_db" >"$verify_manifest"
cmp --silent "$manifest" "$verify_manifest" || \
    fail "Restored DB/object manifest does not match the accepted source set."

target_exists="$(
    "${compose[@]}" exec -T c19-asset-postgres psql \
        --username="$target_user" --dbname=postgres --tuples-only --no-align \
        --command="select 1 from pg_database where datname = '$target_db'"
)"
[[ "$target_exists" == 1 ]] || fail "Initialized target database is missing."
swap_in_progress=1
if ! "${compose[@]}" exec -T c19-asset-postgres psql \
    --username="$target_user" --dbname=postgres --set=ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$target_db', '$restore_db') AND pid <> pg_backend_pid();
BEGIN;
ALTER DATABASE "$target_db" RENAME TO "$rollback_db";
ALTER DATABASE "$restore_db" RENAME TO "$target_db";
COMMIT;
SQL
then
    fail "Atomic database activation failed."
fi
swap_in_progress=0
database_swapped=1

health_failed=0
"${compose[@]}" up -d --no-deps c19-asset-api
api_container="$("${compose[@]}" ps -q c19-asset-api 2>/dev/null || true)"
[[ -n "$api_container" ]] || health_failed=1
if [[ "$health_failed" == 0 ]]; then
    for attempt in $(seq 1 40); do
        health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$api_container" 2>/dev/null || true)"
        [[ "$health" == healthy ]] && break
        if [[ "$health" == unhealthy || "$attempt" == 40 ]]; then
            health_failed=1
            break
        fi
        sleep 1
    done
fi
"${compose[@]}" stop -t 30 c19-asset-api >/dev/null 2>&1 || true
if [[ -n "$api_container" ]]; then
    [[ "$(docker inspect --format '{{.State.Running}}' "$api_container" 2>/dev/null || true)" == false ]] || \
        health_failed=1
fi

if [[ "$health_failed" == 1 ]]; then
    if rollback_database_swap; then
        fail "Restored API health failed; pristine DB name was restored and failed data remains isolated."
    fi
    fail "Restored API health failed and automatic rollback requires manual recovery."
fi

# API startup may have advanced Alembic. Re-run the same read-only gate against
# the activated database before accepting the isolated restore.
"${compose[@]}" run -T --rm --no-deps --entrypoint python c19-asset-worker \
    -m c19_asset_service.consistency >"$verify_manifest"
cmp --silent "$manifest" "$verify_manifest" || \
    fail "Post-migration DB/object manifest no longer matches the source set."

rm -f "$verify_manifest"
trap - EXIT INT TERM HUP
printf 'C19 asset restore accepted in isolation\n'
printf 'dataset_id: %s\n' "$target_dataset"
printf 'database: %s\n' "$target_db"
printf 'rollback_database: %s\n' "$rollback_db"
printf 'active_volume: %s\n' "$active_volume"
printf 'object_count: %s\n' "$expected_count"
printf 'object_bytes: %s\n' "$expected_bytes"
printf 'api_running: no\n'
printf 'gateway_running: no\n'
printf 'worker_running: no\n'
printf 'production_connected: no\n'
