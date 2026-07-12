# C19 Record Service

This is the independently deployable persistence boundary for C19 text, emoji,
image, ordinary-file records, and Moments. It owns its PostgreSQL schema and
never imports Barong's models or settings. Image/file bytes remain in the
independent C19 Asset Service; voice and video remain absent.

## Required environment

- `C19_RECORD_DATABASE_URL`: its own PostgreSQL database, normally using the
  `postgresql+psycopg://` driver.
- `C19_RECORD_SERVICE_TOKEN`: random service credential of at least 32
  characters.
- `C19_RECORD_CURSOR_SIGNING_SECRET`: independent random signing secret of at
  least 32 characters.
- `C19_RECORD_CURSOR_TTL_SECONDS`: optional; default `86400`.
- `C19_RECORD_MAX_MESSAGE_CHARS`: optional; default `10000`.

Do not reuse the Barong database, database user, service token, or signing
secret. The container listens on port 8090 inside its Docker network; do not
publish that port to the public interface.

## Run and migrate

From the repository root, a manual migration can be inspected or applied with:

```bash
alembic -c c19_record_service/alembic.ini upgrade head
```

The production container runs the same Alembic upgrade before starting:

```bash
python -m c19_record_service.start
```

For local development after applying the migration:

```bash
uvicorn c19_record_service.app:create_app_from_env --factory --port 8090
```

`GET /healthz` is the only unauthenticated route. Every `/v1` request requires
`Authorization: Bearer <C19_RECORD_SERVICE_TOKEN>`. Uvicorn access logging
contains method/path/status only; the service has no request-body logging and
does not put message content into its mutation audit rows or exceptions.

## Migration boundary

Records live only in this database. Conversation sequence allocation, sender
idempotency keys, user event cursors, and receipt positions are also local to
it. Back up this PostgreSQL database independently. Moving to another VPS is a
database dump/restore (or PostgreSQL logical replication) plus a change to the
Barong adapter URL; no Barong schema or chat API needs to change.

Stage 5 stores Moment and comment text here rather than in Barong's control
database. Barong remains authoritative for current accounts, affiliations,
friendships, and blocks. It sends a content-free current-policy context on every
feed, exact-read, interaction, and event query. The Record Service requires both
the immutable publish-time audience snapshot and that current context; neither
one can expand the other.

The Stage 5 Alembic downgrade is intentionally fail-closed: it refuses to drop
the Moment schema while any Moment, audience, asset reference, interaction,
event, or feed-sequence row remains. Export or explicitly remove that data
before attempting a downgrade.

Moment publication starts with a private server-reserved draft. Draft,
publication, and comment timestamps are generated on the first authoritative
write and are not accepted in retry bodies. Publication accepts zero to nine
immutable image snapshots, requires text or at least one image, and hashes only
stable business intent. Replays return the original Moment, payload reuse
conflicts, and deleted client IDs remain permanent body-free tombstones.

Deletion is two-phase. The first call changes the Moment to `delete_pending`,
hides it, clears Moment/comment text, and retains only the image snapshots needed
for idempotent Asset Service cleanup. The completion call clears those snapshots
and seals `deleted`. Likes use one lifecycle row per user/Moment, comments use a
per-author client idempotency key, and database transition claims prevent
duplicate counters or events under concurrent retries.

Moment feed, like, comment, and event cursors are signed and bound to a canonical
SHA-256 digest of the supplied current-policy context. Relationship changes make
old cursors invalid instead of continuing with stale visibility. Moment events
share the durable per-user event sequence with chat but use a distinct cursor
kind and contain only event/resource/actor IDs and timestamps—never Moment text,
comment text, visibility, audience, filenames, or asset locators.

`record_asset_references` contains only immutable provider-neutral snapshots:
asset/client IDs, image-or-file kind, normalized display filename, MIME type,
size, SHA-256, version, and ordinal. It never contains file bytes, object keys,
provider/VPS locations, upload tickets, or download locators. The first-release
append contract accepts at most one asset per record; the ordinal column and
ordered response shape leave room for a later multi-asset expansion.

Text and emoji requests without assets retain the original v1 immutable-intent
digest. Asset-bearing requests use a v2 digest that also covers every stable
asset snapshot field in ordinal order. The ledger stores `intent_version`, so a
retry can never replace an attachment while reusing `client_message_id`.

`maximum_records` on a retention command is a per-command deletion batch cap,
not a promise to retain that many records. Omitting it applies the explicit
`delete_before` cutoff to every matching record in the selected conversation
scope.

Sender idempotency keys are retained as permanent body-free tombstones after
record deletion. While a record is active its ledger contains a SHA-256 digest
of immutable user intent, but deletion clears that digest as well as the record
reference. A deleted key returns the same HTTP 410 response for every payload,
so it cannot become a short-message hash oracle and a delayed retry cannot undo
retention or privacy deletion.

`GET /v1/conversations/{conversation_id}/records/{record_id}?user_id=...`
returns a single record only when `chat_user_record_events` proves that the
specified user belonged to that record's original audience. Missing records,
wrong conversations, and users who joined after the record was created all
receive the same 404. Current conversation membership is checked separately by
Barong before it calls this private endpoint.

`GET /v1/users/{user_id}/events/tail` returns a body-free signed cursor at the
user's current event tail. It is only for a first-time client that deliberately
wants to begin at "now". Reconnecting clients must persist and reuse the cursor
returned by `/v1/users/{user_id}/events`; using `tail` for reconnect would skip
events produced while the client was offline.
