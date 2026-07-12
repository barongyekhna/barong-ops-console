#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${C19_PYTHON_BIN:-$repo_root/.venv/bin/python}"
pytest_bin="${C19_PYTEST_BIN:-$repo_root/.venv/bin/pytest}"

fail() {
    printf 'C19 release readiness failed: %s\n' "$1" >&2
    exit 1
}

[[ -x "$python_bin" ]] || fail "Python virtual environment is unavailable."
[[ -x "$pytest_bin" ]] || fail "Pytest virtual environment is unavailable."
command -v npm >/dev/null 2>&1 || fail "npm is unavailable."
command -v git >/dev/null 2>&1 || fail "git is unavailable."
command -v rg >/dev/null 2>&1 || fail "ripgrep is unavailable."

printf 'C19 release gate: Barong runtime\n'
PYTHONPATH=. "$pytest_bin" -q tests/backend/test_c19_*

printf 'C19 release gate: native access policy and migration metadata\n'
PYTHONPATH=. "$pytest_bin" -q \
    tests/backend/test_permissions_service.py \
    tests/backend/test_alembic_config.py \
    tests/backend/test_session_cookie_policy.py \
    tests/backend/test_pre20_p_staging_stabilization.py

printf 'C19 release gate: independent stores\n'
PYTHONPATH=. "$pytest_bin" -q tests/c19_record_service tests/c19_asset_service

printf 'C19 release gate: deployment boundaries\n'
PYTHONPATH=. "$pytest_bin" -q tests/c19_asset_operations

printf 'C19 release gate: frontend\n'
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run verify
npm --prefix frontend run build

printf 'C19 release gate: static boundaries\n'
PYTHONPATH=. "$python_bin" -m compileall -q \
    backend/app/modules/c19 \
    c19_record_service \
    c19_asset_service \
    scripts/c19_full_dr.py \
    scripts/c19_record_retention.py

for script in scripts/c19_*.sh; do
    [[ "$script" == "scripts/c19_release_readiness.sh" ]] || bash -n "$script"
done
bash -n scripts/test_backend_db_docker.sh

git diff --check

if [[ -n "$(git ls-files backups archives)" ]] \
    || git ls-files | rg \
        '(^|/)stage[0-9]+-(rehearsal|restore)' >/dev/null; then
    fail "A private archive, runtime env file, or rehearsal artifact is tracked."
fi
if git ls-files '.env.c19-record*' '.env.c19-asset*' \
    | rg -v '\.example$' >/dev/null; then
    fail "A private C19 runtime environment file is tracked."
fi

git check-ignore -q .env.c19-record.production || \
    fail ".env.c19-record.production must remain ignored."
git check-ignore -q .env.c19-asset.production || \
    fail ".env.c19-asset.production must remain ignored."
git check-ignore -q backups/c19-record/example.dump || \
    fail "C19 Record backups must remain ignored."
git check-ignore -q backups/c19-asset/example.tar || \
    fail "C19 Asset backups must remain ignored."

printf 'C19 release readiness passed. No production activation was performed.\n'
