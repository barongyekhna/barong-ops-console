#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

manifest=""
hmac_key_file="${C19_FULL_MANIFEST_HMAC_KEY_FILE:-}"
barong_dataset="${C19_FULL_BARONG_DATASET_ID:-}"
record_dataset="${C19_FULL_RECORD_DATASET_ID:-}"
asset_dataset="${C19_FULL_ASSET_DATASET_ID:-}"
barong_revision="${C19_FULL_EXPECTED_BARONG_REVISION:-}"
record_revision="${C19_FULL_EXPECTED_RECORD_REVISION:-}"
asset_revision="${C19_FULL_EXPECTED_ASSET_REVISION:-}"
required_record_revision="c19_record_20260712_04"
required_asset_revision="c19_asset_20260712_03"

fail() {
    printf 'C19 full restore verification failed: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
Usage:
  C19_FULL_MANIFEST_HMAC_KEY_FILE=/secure/key \
  ./scripts/c19_full_restore_verify.sh \
    --manifest backups/c19-full/GEN/c19-full-GEN.json \
    --barong-dataset-id ID --record-dataset-id ID --asset-dataset-id ID \
    --barong-revision REV --record-revision REV --asset-revision REV

This is a non-mutating restore admission gate, not a restore command. It checks
the HMAC, exact SHA-256/size of every component, dataset and revision identity,
the all-writers-stopped attestation, PostgreSQL archive magic, and exact Asset
tar/member hashes. It never invokes Docker, pg_restore, or a production API.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --manifest)
            [[ $# -ge 2 ]] || fail "--manifest requires a value."
            manifest="$2"
            shift 2
            ;;
        --hmac-key-file)
            [[ $# -ge 2 ]] || fail "--hmac-key-file requires a value."
            hmac_key_file="$2"
            shift 2
            ;;
        --barong-dataset-id)
            [[ $# -ge 2 ]] || fail "--barong-dataset-id requires a value."
            barong_dataset="$2"
            shift 2
            ;;
        --record-dataset-id)
            [[ $# -ge 2 ]] || fail "--record-dataset-id requires a value."
            record_dataset="$2"
            shift 2
            ;;
        --asset-dataset-id)
            [[ $# -ge 2 ]] || fail "--asset-dataset-id requires a value."
            asset_dataset="$2"
            shift 2
            ;;
        --barong-revision)
            [[ $# -ge 2 ]] || fail "--barong-revision requires a value."
            barong_revision="$2"
            shift 2
            ;;
        --record-revision)
            [[ $# -ge 2 ]] || fail "--record-revision requires a value."
            record_revision="$2"
            shift 2
            ;;
        --asset-revision)
            [[ $# -ge 2 ]] || fail "--asset-revision requires a value."
            asset_revision="$2"
            shift 2
            ;;
        --dry-run|--verify)
            shift
            ;;
        --execute)
            fail "Automatic full-system restore is intentionally unsupported; verify the bundle, then use the component restore runbooks in an isolated target."
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

[[ -n "$manifest" && -f "$manifest" && ! -L "$manifest" ]] || \
    fail "--manifest must identify a regular non-symlink file."
[[ -n "$hmac_key_file" && -f "$hmac_key_file" && ! -L "$hmac_key_file" ]] || \
    fail "A regular HMAC key file is required."
for value in "$barong_dataset" "$record_dataset" "$asset_dataset"; do
    [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$ ]] || \
        fail "All three restore target dataset IDs are required."
done
for value in "$barong_revision" "$record_revision" "$asset_revision"; do
    [[ "$value" =~ ^[A-Za-z0-9_.-]+$ ]] || \
        fail "All three expected target revisions are required."
done
[[ "$record_revision" == "$required_record_revision" ]] || \
    fail "Full restore admission requires Record revision $required_record_revision."
[[ "$asset_revision" == "$required_asset_revision" ]] || \
    fail "Full restore admission requires Asset revision $required_asset_revision."
if [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
else
    command -v python3 >/dev/null 2>&1 || fail "python3 is required."
    python_bin=python3
fi
command -v flock >/dev/null 2>&1 || fail "flock is required."

manifest_dir="$(cd "$(dirname "$manifest")" && pwd)"
lock_dir="${C19_FULL_LOCK_DIR:-${manifest_dir}/.locks}"
[[ ! -L "$lock_dir" ]] || fail "Restore verification lock directory must not be a symlink."
mkdir -p "$lock_dir"
chmod 700 "$lock_dir"
lock_file="${lock_dir}/full-system.lock"
[[ ! -L "$lock_file" ]] || fail "Restore verification lock file must not be a symlink."
exec 8>"$lock_file"
chmod 600 "$lock_file"
flock -n 8 || fail "Another full C19 backup or restore verification is running."

verify_args=(
    verify
    --manifest "$manifest"
    --hmac-key-file "$hmac_key_file"
    --expected-barong-dataset "$barong_dataset"
    --expected-record-dataset "$record_dataset"
    --expected-asset-dataset "$asset_dataset"
)
verify_args+=(--expected-barong-revision "$barong_revision")
verify_args+=(--expected-record-revision "$record_revision")
verify_args+=(--expected-asset-revision "$asset_revision")

"$python_bin" scripts/c19_full_dr.py "${verify_args[@]}"

readarray -t identity < <(
    "$python_bin" - "$manifest" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
document = json.loads(path.read_text(encoding="utf-8"))
print(document["generation_id"])
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
)
[[ "${#identity[@]}" == 2 ]] || fail "Could not derive the verified restore identity."
confirmation="RESTORE/${identity[0]}/${identity[1]}/${barong_dataset}/${record_dataset}/${asset_dataset}"

printf 'C19 full restore admission evidence\n'
printf 'generation_id: %s\n' "${identity[0]}"
printf 'manifest_sha256: %s\n' "${identity[1]}"
printf 'required_manual_restore_confirmation: %s\n' "$confirmation"
printf '%s\n' 'Bundle verification passed; no restore, Docker, database, volume, or API operation was executed.'
printf '%s\n' 'Restore order: isolate target writers; restore Barong control DB; restore Record; restore Asset metadata+objects; run each component health/consistency gate; then enable exactly one writer set.'
