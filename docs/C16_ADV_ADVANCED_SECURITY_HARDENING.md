# C16-ADV Advanced Security Hardening

Status: code-level hardening complete.

No business workflow behavior, runtime execution, Docker workflow, staging
deployment, or production deployment was changed.

## API Surface Reduction

- Production-like environments now default to disabled FastAPI docs, ReDoc, and
  OpenAPI schema exposure.
- `APP_DOCS_ENABLED` is an explicit opt-in override for non-hostile controlled
  environments.
- Control-plane authentication failures use stealth `404` responses in
  production-like environments through `CONTROL_PLANE_STEALTH_MODE`.
- Public webhook/n8n bypass paths return `404` at backend, frontend proxy, and
  reviewed Nginx template layers.
- Production HTTP, validation, and unhandled error responses are sanitized to
  stable generic messages.

## Distributed Rate Limiting

Login rate limiting now uses shared database state instead of process memory.

Rate limit buckets are written to `security_rate_limit_buckets` with only hashed
identifiers:

- `ip` bucket
- `user` bucket
- `endpoint` bucket

This supports multi-instance deployments where every backend instance shares the
same database. Account-level backoff and lockout still remain in the `users`
table.

## Replay Attack Hardening

C15B and C15D replay protection now persists nonce/idempotency state in
`security_replay_nonces`.

The persistent replay record stores:

- hashed global deduplication key
- hashed nonce/idempotency key
- payload digest
- first-seen timestamp
- expiry timestamp

C15B registers one global key. C15D registers both nonce and idempotency keys.
Duplicate keys inside the TTL window are rejected with replay errors, and unique
database constraints provide cross-instance deduplication.

## Fingerprint Reduction

Production-like responses avoid exposing control-plane authorization state,
validation details, direct webhook blocking rationale, and internal stage
markers in operation-log details.

Route names remain stable for authenticated console functionality. A full opaque
control-plane URL redesign is intentionally out of scope for C16-ADV because it
would be an architecture refactor.

## Logging Security

Operation-log details now strip or redact:

- password/token/secret/authorization/api-key/private-key/credential fields
- session, cookie, signature, nonce, and idempotency fields
- runtime endpoint/webhook URL fields
- internal API surface strings
- C09/C10/C13/C14/C15/C16 stage markers in details strings

Structured audit actions remain available for forensic correlation without
recording request secrets or full internal paths.

## Residual Notes

- Persistent replay and distributed rate limiting require the C16-ADV migration
  to be applied before production traffic relies on them.
- Production deployments must set `WEBHOOK_GATEWAY_SIGNING_SECRET`.
- Edge-level rate limiting remains recommended in Nginx/CDN/WAF for volumetric
  attacks before requests reach the application.
