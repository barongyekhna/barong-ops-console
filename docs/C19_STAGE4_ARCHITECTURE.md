# C19 Stage 4 — External Image/File Asset Runtime

Status: implementation and isolated acceptance completed on `2026-07-12`.
Production activation and any future asset VPS cut-over remain separate,
explicitly approved operations.

## 1. Fixed ownership boundaries

- Barong owns identity, current C18/C19 affiliation validity, conversation
  membership, blocking and send/read authorization. Barong never stores file
  bytes, object keys or durable transfer URLs.
- C19 Record Service owns the durable statement that a record contains a given
  ordered set of assets. It stores only immutable provider-neutral snapshots.
- C19 Asset Service owns upload idempotency, metadata, validation state,
  quarantine, object bytes, short transfer tickets and asset lifecycle.
- The browser stores a selected `File`, upload progress, blob preview URL and
  short transfer locator in memory only. It never persists them in Web Storage,
  IndexedDB, Cache Storage or a service worker.
- A global `user_id` owns an upload. Organization and affiliation are immutable
  audit snapshots only. Record visibility and current conversation membership,
  not an organization bucket ACL, determine access.

The Barong database must not gain a message or attachment content table. The
historical C19G attachment schema and generic media store remain unmounted.

## 2. Runtime topology

`docker-compose.c19-asset.yml` is an isolated deployment unit:

- `c19-asset-postgres`: PostgreSQL 17 metadata database; no published port.
- `c19-asset-api`: authenticated JSON control plane; no object-volume mount.
- `c19-asset-worker`: the only writer to the active object volume; validates,
  scans, creates safe thumbnails, promotes, quarantines and deletes.
- `c19-asset-clamd`: private malware scanner with its own signature volume; it
  alone joins a dedicated, unshared update-egress network for FreshClam while
  port 3310 remains unpublished.
- `c19-asset-gateway`: streaming byte plane; incoming volume RW, active volume
  RO, no database credentials; attached to the internal data plane plus a
  single-member, non-masquerading ingress bridge and published only on loopback
  for Nginx.

The current VPS can run this unit with independent networks and labelled named
volumes. Moving it later changes the Barong control URL and Nginx byte-plane
upstream only; record payloads, asset IDs and browser paths remain unchanged.

## 3. Supported first-release product shape

- One asset per message in the UI and API. Database ordinals support expansion.
- Images: JPEG, PNG, WebP and GIF.
- Files: PDF, plain text, CSV, DOCX, XLSX, PPTX and ZIP.
- Explicitly unsupported: SVG, HTML, JavaScript, executable content, legacy
  binary Office documents, macro-enabled Office documents, audio and video.
- Default image limit: 20 MiB. Default file limit: 50 MiB. Compiled hard limit:
  64 MiB regardless of environment configuration.
- Image messages and file messages may have an optional caption of at most 4,000
  characters. A message must have text/emoji content or exactly one asset.

Client extension and MIME are declarations only. The worker must also verify
magic/format, fully decode images within pixel/dimension/frame limits, inspect
ZIP/OOXML members and expansion limits, and complete malware scanning. Scanner
or parser failure is fail-closed.

## 4. Provider-neutral record contract

Each record returns `assets: []`. An entry is:

```json
{
  "asset_id": "att_<32 lowercase hex>",
  "client_asset_id": "client-generated id",
  "kind": "image",
  "filename": "normalized-display-name.jpg",
  "media_type": "image/jpeg",
  "size_bytes": 12345,
  "sha256_hex": "<64 lowercase hex>",
  "version": 1,
  "ordinal": 0
}
```

The Record Service stores this in `record_asset_references`, with a foreign key
to `chat_records`, unique `(record_id, ordinal)` and unique
`(record_id, asset_id)`. It never stores object keys, provider/VPS locations,
upload handles or download locators.

Content types become `text | emoji | image | file`. Existing text/emoji calls
with no assets keep the exact v1 idempotency hash. An asset-bearing call uses a
v2 hash containing the existing immutable user intent plus the ordered stable
asset snapshot. Dynamic audience/org metadata, URLs, scan timestamps and object
state never enter the hash. Deleted idempotency keys remain permanent 410
tombstones.

The private Record Service adds an exact visibility endpoint:

```text
GET /v1/conversations/{conversation_id}/records/{record_id}?user_id=...
```

It returns 404 unless `chat_user_record_events` proves that the user was in that
record's audience. Current group membership alone must never reveal a record
created before that user joined.

## 5. Asset state and idempotency

Logical IDs are server-generated `att_<uuid4 hex>`. Physical keys are random
and never leave the Asset Service. The upload idempotency key is
`(owner_user_id, client_asset_id)`.

State machine:

```text
pending_upload -> uploaded -> scanning -> active
                                |          |
                                +-> rejected/quarantined
active/rejected/quarantined -> delete_pending -> deleted
pending_upload -> expired
```

The database keeps a body-free permanent tombstone after deletion. It clears
object key, original filename and SHA-256. Reusing the same deleted client asset
ID returns 410. Reusing an active key with a different immutable upload intent
returns 409. Finalize, bind, quarantine and delete operations are idempotent.
There is no cross-user content-hash deduplication.

## 6. Private Asset Service JSON API

All `/v1` calls require the Barong-to-Asset service token.

```text
POST /v1/upload-intents
GET  /v1/assets/{asset_id}
POST /v1/assets/{asset_id}/finalize
POST /v1/assets/{asset_id}/bindings/prepare
POST /v1/assets/{asset_id}/bindings/commit
POST /v1/assets/{asset_id}/download-intents
POST /v1/assets/{asset_id}/quarantine
POST /v1/assets/{asset_id}/delete
```

Upload intent input binds owner, conversation, client asset ID, normalized
display filename, declared MIME, declared size and declared SHA-256. The result
contains asset metadata plus a short opaque upload ticket, never a provider URL.
Finalize is safe to poll and returns the current state. Only `active` assets may
be placed in a message.

Prepare binding locks an active, unbound asset to owner, conversation and
`client_message_id`. Commit records the returned `record_id`. A retry between
Record append and commit must be repairable without duplicating either object or
record. The Record Service remains the authority for record-to-asset references.

Download intent input binds owner/reader, conversation, record, asset, variant,
disposition and asset version. It is issued only after Barong has performed both
current conversation authorization and exact Record Service visibility/ref
validation. The database stores only a SHA-256 of the 256-bit ticket.

Private gateway-to-API endpoints authorize and complete uploads and authorize
downloads. The gateway receives an internal object key only after authorization;
that key is never returned to the browser or Barong.

## 7. Public Barong/browser flow

Small JSON control requests use the existing strict Next allowlist:

```text
POST /api/backend/c19/conversations/{conversation_id}/assets/upload-intents
POST /api/backend/c19/conversations/{conversation_id}/assets/{asset_id}/finalize
GET  /api/backend/c19/conversations/{conversation_id}/assets/{asset_id}
POST /api/backend/c19/conversations/{conversation_id}/records/{record_id}/assets/{asset_id}/access-intents
POST /api/backend/c19/conversations/{conversation_id}/messages
```

Large bytes never pass through Next or Barong:

```text
PUT      /api/backend/c19-assets/u/{opaque_ticket}
GET|HEAD /api/backend/c19-assets/d/{opaque_ticket}
```

The byte locators deliberately remain below `/api/backend`, so the normal
session cookie's narrow `Path=/api/backend` scope covers both transfer routes.
Nginx's exact ticket regex locations intercept them before the catch-all Next
upstream: only the body-free authorization subrequest reaches Barong, and only
the byte stream reaches the Asset gateway. The Next catch-all rejects
`c19-assets` paths if it is reached in a misconfigured deployment. Nginx also
returns 404 for malformed new-prefix paths and every legacy
`/api/c19-assets/...` path; stale clients must request a fresh intent.

Nginx performs a body-free `auth_request` to a Barong transfer-authorization
endpoint on every byte request, forwards current session cookies and original
method/path, disables token-bearing access logs, disables request buffering for
uploads, and applies a location-specific 64 MiB ceiling. The gateway separately
enforces method, ticket, actual streamed byte count and one single-byte Range.

Download/thumbnail responses use `Cache-Control: private, no-store`,
`X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. Safe
re-encoded image thumbnails may be inline; originals and every ordinary file
are attachment downloads. PDF/Office/ZIP are never embedded in an iframe,
object or embed element.

## 8. Authorization invariant

Upload, finalize, prepare and message send require the existing
`authorize_conversation(..., for_send=True)` chain. Access intent requires:

1. a currently active authenticated user and valid C18/C19 affiliation;
2. current active membership in the conversation;
3. exact Record Service proof that this user can see `record_id`;
4. exact record snapshot proof that `record_id` references `asset_id`;
5. Asset Service proof that the binding, conversation and version match and the
   asset is still active.

Platform owner/admin and organization owner/admin status grant no implicit
private-chat asset read. Blocking prevents new sends. Affiliation is never
automatically selected when a choice is required.

## 9. Browser lifecycle

The composer uses one explicit file picker and a dedicated XHR streaming helper
for progress. Image selection uses `URL.createObjectURL`; replace, cancel,
conversation switch, `pagehide` and unmount abort in-flight requests and revoke
the URL. Uploading 100 percent is not success: the UI separately displays
upload, scanning, active, record persistence and failure states.

History renders only typed `assets[]`. It obtains thumbnail/download locators
on demand and keeps them in bounded component memory. Images use ordinary
`<img loading="lazy" decoding="async">`; no Next image optimizer or persistent
cache is allowed. Delivery/read positions continue to follow record sequence,
not asset-byte download completion.

## 10. Migration and release gate

`C19_ASSET_DATASET_ID` binds metadata DB and active-object volume. A backup set
contains a PostgreSQL custom dump, active-object archive, object manifest and a
checksummed metadata document with dataset ID, Alembic revision and blob format
revision. Quarantine bytes are excluded from normal backup. After byte ingress
closes, a read-only drain gate settles confirmed transitions and SIGTERM lets
the worker finish its current atomic unit. The backup manifest is emitted only
when all DB original/thumbnail keys, sizes and hashes exactly equal the active
volume. Restore repeats that gate against the temporary DB before an atomic
name swap and after API migrations. Final cut-over uses `--leave-stopped` so the
source cannot resume writes implicitly.

The isolated release gate passed format/MIME mismatch, malware sample, scanner
failure, archive/image bomb limits, over-limit stream, ticket expiry/replay,
Range behavior, revoked member, pre-join history, idempotency
conflicts/tombstones, bind crash recovery, delete invalidation, restart,
PostgreSQL 17 plus object-volume backup/restore, and single-writer migration
coverage. Passing this gate does not configure or activate production; blank
production Asset Store credentials continue to fail closed.

## 11. Isolated acceptance evidence

The acceptance used only explicitly named `stage4-rehearsal` and
`stage4-restore` resources on the current VPS:

- PostgreSQL, API, worker, gateway and ClamAV were healthy in separated networks;
  the gateway alone used a single-member, non-masquerading ingress bridge bound
  to `127.0.0.1:18092`, and ClamAV port 3310 was not published.
- A real PNG completed upload, ClamAV scan, strict decode, safe thumbnail,
  prepare/commit binding, original/thumbnail GET, HEAD and 100-byte Range. Its
  SHA-256 remained identical after PostgreSQL/API/worker/gateway restart.
- A real EICAR upload ended `quarantined` with `malware_detected`; a clean upload
  while ClamAV was stopped ended `quarantined` with `scanner_unavailable`. Neither
  produced an active object.
- A download ticket allowed exactly its configured total uses and then returned
  the indistinguishable 404 response.
- The coordinated backup emitted a PostgreSQL custom dump, deterministic active
  object archive and exact DB↔object manifest. All metadata checksums matched.
  Restore into fresh isolated PostgreSQL/object volumes preserved dataset ID and
  revision, revoked old tickets and reproduced the exact two-line manifest.
- PostgreSQL 17 also migrated the Record Service from
  `c19_record_20260711_01` to `c19_record_20260711_02` while preserving a v1
  message/hash and then started healthy.
- Automated evidence passed 59 Asset Service, 71 Barong C19 backend, 29 Record
  Service, 166 frontend and 9 asset deployment/Nginx tests, plus TypeScript,
  Python compilation, Bash syntax, Compose rendering and diff checks.

No production container, production network/configuration or new VPS was
modified or connected during acceptance.
