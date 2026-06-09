#!/usr/bin/env bash
set -euo pipefail

base_url="${1:-https://ops.barongyekhna.com}"

fail() {
    printf 'Production smoke check failed: %s\n' "$1" >&2
    exit 1
}

case "$base_url" in
    http://*|https://*) ;;
    *) fail "Base URL must start with http:// or https://." ;;
esac

curl --fail --silent --show-error --location --max-time 10 \
    "$base_url/login" >/dev/null
curl --fail --silent --show-error --location --max-time 10 \
    "$base_url/api/backend/auth/me" >/dev/null ||
    printf '%s\n' "Unauthenticated /auth/me rejected or unavailable; verify manually after login."

printf 'Production smoke check completed for %s\n' "$base_url"
