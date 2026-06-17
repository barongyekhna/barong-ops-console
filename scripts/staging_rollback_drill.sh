#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${PYTHON:-python3}"
if [[ -x ".venv/bin/python" ]]; then
    python_bin=".venv/bin/python"
fi

"$python_bin" scripts/staging_stabilization.py rollback
