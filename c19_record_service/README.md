# C19 Record Service

This is the independently deployable persistence boundary for C19 text and
emoji records. It owns its PostgreSQL schema and never imports Barong's models
or settings. Images, files, voice, video, and Moments are deliberately absent.

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

`GET /v1/users/{user_id}/events/tail` returns a body-free signed cursor at the
user's current event tail. It is only for a first-time client that deliberately
wants to begin at "now". Reconnecting clients must persist and reuse the cursor
returned by `/v1/users/{user_id}/events`; using `tail` for reconnect would skip
events produced while the client was offline.
