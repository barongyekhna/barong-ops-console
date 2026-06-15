# C16-FIX-4 Production Security Hardening

Status: code-level hardening complete.

No C14/C15 architecture, business module routing, runtime execution, Docker
workflow, staging deployment, or production deployment was changed.

## Security Headers

Security headers are now defined at three layers:

- Backend middleware applies headers to API responses.
- Control-plane early 401/403 responses explicitly receive the same headers.
- Next.js and the reviewed Nginx template emit matching browser-facing headers.
- `upgrade-insecure-requests` is kept in the HTTPS Nginx template only, so
  local direct-HTTP development remains compatible.

Headers:

- `Content-Security-Policy`
- `Strict-Transport-Security`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy`

## Login Protection

Login now uses two controls:

- IP sliding-window attempt limiting.
- Per-user failed login counters with exponential backoff and lockout.

Defaults:

- 20 attempts per IP per 900 seconds.
- 5 failed attempts before account lockout.
- 2 second base backoff, capped at 60 seconds.
- 15 minute account lockout.

Rate-limited requests return `429` with `Retry-After`.

## Session Revocation

Owner-driven password reset now invalidates all active sessions for the target
user with `invalidation_reason=password_reset`. The target user must re-login
with the new password.

## Webhook Replay Protection

C15B and C15D now register replay keys in a TTL replay-protection store:

- C15B accepts an optional signed `nonce`.
- C15D accepts optional signed `nonce` and `idempotency_key`.
- Backward-compatible requests without those fields use a signed payload digest
  as the replay key.
- Duplicate keys within the TTL are rejected with `409`.

The current store is process-local and matches the existing no-new-service
architecture. It is shaped so a Redis/cache implementation can replace it
without changing C15B/C15D route contracts.

## Production FastAPI Lockdown

For `APP_ENV=production` or `APP_ENV=prod`:

- `/docs` is disabled.
- `/redoc` is disabled.
- `/openapi.json` is disabled.
- `debug` is forced off.

Development and staging keep existing docs behavior unless the environment is
promoted to production.

## C17 Readiness

C16-FIX-4 closes the C16 P0 findings and the requested P1 hardening items at
code level. Runtime verification remains intentionally unperformed under the
C16-FIX-4 no-runtime/no-Docker/no-pytest rule.
