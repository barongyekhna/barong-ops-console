#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root/frontend"

created_tests_link=0
created_frontend_link=0

cleanup() {
    if [[ "$created_tests_link" == "1" ]]; then
        rm -f tests
    fi
    if [[ "$created_frontend_link" == "1" ]]; then
        rm -f frontend
    fi
}
trap cleanup EXIT

if [[ ! -e tests ]]; then
    ln -s ../tests tests
    created_tests_link=1
fi

if [[ ! -e frontend ]]; then
    ln -s . frontend
    created_frontend_link=1
fi

npm ci
npm run test
cleanup
trap - EXIT

npm run typecheck
npm run verify
