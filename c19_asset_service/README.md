# C19 Asset Service

This package is the isolated metadata, byte gateway, and validation worker
runtime shared by Stage 4 chat assets and Stage 5 Moment images. It never uses
Barong's database and the API role never mounts object storage.

Metadata is tagged with `usage=chat_message|moment_image` and an immutable
`scope_id`. Existing chat JSON remains on `/v1`; Moment controls use
`/v1/moment-assets/*`. The rolling-compatible, provider-neutral transfer
inspection endpoint is `/v2/transfers/inspect`, while the old
`/v1/transfers/inspect` keeps its exact chat-only response.

Start one role explicitly:

```text
python -m c19_asset_service.start api
python -m c19_asset_service.start gateway
python -m c19_asset_service.start worker
```

The worker handles SIGTERM/SIGINT by finishing its current `run_once` transition
and then exiting. Backup and restore use the read-only consistency gate:

```text
python -m c19_asset_service.consistency
python -m c19_asset_service.consistency --database-name c19_restore_YYYYMMDD
```

It emits a deterministic manifest only when database original/thumbnail keys,
sizes and SHA-256 values exactly equal every file in the active root.

The `c19_asset_20260712_02` migration backfills every Stage 4 row and ticket as
`chat_message` without changing IDs, ticket hashes, versions, bindings, object
keys, or blob format. Downgrade is refused once any `moment_image` data exists.

Browser byte routes are fixed at `/api/backend/c19-assets/u/{ticket}` and
`/api/backend/c19-assets/d/{ticket}` so the narrow session-cookie
`Path=/api/backend` covers the body-free Nginx authorization subrequest. Nginx
streams the bytes directly to the gateway; neither Next nor Barong handles the
body. Production activation is intentionally outside the package and remains
fail-closed until the isolated acceptance suite passes.
