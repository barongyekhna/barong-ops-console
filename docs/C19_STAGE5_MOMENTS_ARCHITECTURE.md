# C19 Stage 5 — Moments Runtime

Status: implementation and isolated acceptance completed on `2026-07-12`.
Production activation is a separate explicitly approved operation.

## 1. Product contract

C19 Moments is an internal social feed for every active platform member. A user
has one global communication card and may hold multiple active C19
affiliations. No primary organization is guessed or persisted.

The first release supports:

- text with at most 4,000 characters;
- zero to nine ordered images, with text or at least one image required;
- `public`, `org`, `friends`, and `private` visibility;
- feed/detail reads, likes, comments, author deletion, bounded polling and SSE;
- desktop and mobile layouts inside the existing C19 workspace.

Voice and video calls remain outside this stage. Moment bodies, comments and
image bytes are never written to the Barong database, logs or browser
persistence.

## 2. Authority split

Barong owns current policy facts:

- authenticated global user identity and active account state;
- authoritative C18-backed C19 affiliations and organization status;
- current friendship and bilateral block state;
- resolution of browser affiliation IDs into organization IDs and audience
  users;
- public API profile and organization-name enrichment.

The independent Record Service owns content-bearing state:

- private draft IDs and author/client idempotency;
- Moment body, visibility and immutable publish-time audience ceiling;
- ordered immutable image references;
- likes, comments, tombstones, feed order and content-free user events;
- opaque cursors bound to a canonical hash of the current Barong context.

The independent Asset Service owns bytes and image lifecycle:

- upload intent, streaming gateway tickets and malware/format validation;
- original and safe thumbnail objects;
- owner, `moment_image` usage, server-reserved Moment scope and binding state;
- short-lived original/thumbnail download tickets and deletion lifecycle.

The same Record and Asset deployments continue to serve chat. Stage 5 adds
Moment domain tables and tagged asset scope without creating a second writer or
changing existing chat v1 wire contracts.

## 3. Audience invariant

Publication creates an immutable maximum audience:

- `public`: every currently active internal C19 user;
- `org`: the union of active users in the publishing user's explicitly selected
  active affiliations; the browser never submits a raw organization ID;
- `friends`: the publishing user's current active, unblocked friends;
- `private`: the author only.

Any user blocked in either direction is removed; the author is always retained.
For an organization Moment, the selected organization IDs are stored with the
snapshot. `author_org_id` is descriptive and nullable: it is set only when one
organization unambiguously describes the post, never by guessing a primary
affiliation.

Every read supplies a fresh context:

```text
viewer_user_id
active_user_ids
active_org_ids
friend_user_ids
blocked_user_ids
```

The Record Service requires both the immutable snapshot and current policy:

- viewer and author must remain active;
- a bilateral block denies access;
- `friends` still requires current friendship;
- `org` still requires a current affiliation in one snapshotted organization;
- `private` remains author-only.

Current state can therefore only narrow a stored audience. It can never expand
one. The relationship-context hash is part of every feed, interaction and event
cursor scope, so a stale cursor cannot be replayed after policy changes.

## 4. Publish and image state machine

The browser first reserves a private Record Service draft and receives a
server-generated `mom_<32 lowercase hex>` ID. Moment image intents are scoped to
that ID and to the authenticated global user.

```text
reserve draft
  -> upload each image sequentially through the byte gateway
  -> worker scan/decode/re-encode thumbnail
  -> poll until every image is active
  -> prepare each image binding in stable ordinal order
  -> durably publish Moment plus immutable references in Record Service
  -> commit every image binding to that same Moment ID
```

The browser keeps selected `File` objects, local preview URLs, progress and
short tickets only in component memory. It uploads sequentially to bound local
and server resource use. Cancel, replacement, page exit and unmount abort work
and revoke local object URLs.

Dynamic timestamps are generated only by the authoritative service. Draft,
publication and comment idempotency hashes contain stable business intent, not
Barong's retry time. If Record publication succeeds but its response or an
Asset commit is lost, owner lifecycle lookup returns the published draft. A
retry verifies the immutable public payload, reads the durable references and
idempotently commits every prepared asset without recomputing the audience.

## 5. Asset scope and byte authorization

Stage 5 generalizes internal Asset rows and tickets to:

```text
usage = chat_message | moment_image
scope_id
binding_client_id
bound_resource_id
```

Stage 4 chat rows are migrated in place with `usage=chat_message`; asset IDs,
versions, object keys, hashes, tickets and binding state are preserved. Existing
chat `/v1` responses remain exact. Moment control endpoints live below
`/v1/moment-assets`, and `/v2/transfers/inspect` returns the tagged scope used by
Barong's shared Nginx authorization endpoint.

Database checks require Moment usage to be an image and require a committed or
downloaded Moment asset's bound resource to equal its server-reserved scope.
Ticket inspection and gateway use cross-check ticket and Asset owner, usage,
scope, version and binding. A Moment ticket cannot be interpreted by the old
chat inspection contract.

Every upload byte request revalidates active actor, exact draft owner and
`draft` state. Every download/HEAD revalidates current Moment visibility, exact
durable reference, owner, scope and asset version. Platform or organization
admin roles have no bypass.

## 6. Interactions and events

Likes are a desired-state mutation: repeated like/unlike calls are idempotent
and generate an event only on a real transition. Comments use an
`(author_user_id, client_comment_id)` idempotency key, immutable intent hash and
content-clearing tombstone after deletion. A comment may be deleted by its
author or the Moment author.

Moment event types are:

```text
published
deleted
liked
unliked
commented
comment_deleted
```

Events contain only IDs, sequence and timestamp, never a Moment body or comment
text. Moment and chat allocate from the same per-user monotonic event sequence
while using separate signed cursor kinds. Feed/history must be fetched through
the normal authorized endpoint after an event.

SSE is a bounded convenience transport over durable event pages. It repeatedly
revalidates the authenticated Barong session and current relationship context,
then closes at the configured lifetime so ordinary authenticated HTTP recovery
remains authoritative. Deleted events receive the same live public/org/friend/
private and block checks as visible Moments.

## 7. Deletion recovery

Author deletion is a recoverable three-part workflow:

1. Record Service changes `published -> delete_pending`, clears body/comments
   and hides the Moment while retaining immutable asset references.
2. Barong records an idempotent delete request for every referenced Asset. The
   Asset Service revokes tickets immediately and its worker owns physical
   cleanup.
3. After every Asset Service has durably accepted deletion, Record Service
   changes `delete_pending -> deleted` and clears its asset references.

Owner lifecycle lookup returns all four states so a retry can continue after
any lost response. Upload endpoints independently require `draft`; publish
requires `draft|published`; delete requires `published|delete_pending|deleted`.
Thus exposing recovery state to the trusted Barong adapter never broadens a
browser operation.

## 8. Public application API

All endpoints are authenticated and mounted below `/api/app/c19/moments`:

```text
POST   /drafts
GET    /feed
GET    /events
GET    /events/tail
POST   /{moment_id}/assets/upload-intents
GET    /{moment_id}/assets/{asset_id}
POST   /{moment_id}/assets/{asset_id}/finalize
POST   /{moment_id}/assets/{asset_id}/access-intents
POST   /{moment_id}/publish
GET    /{moment_id}
DELETE /{moment_id}
PUT    /{moment_id}/like
DELETE /{moment_id}/like
GET    /{moment_id}/likes
GET    /{moment_id}/comments
POST   /{moment_id}/comments
DELETE /{moment_id}/comments/{comment_id}
```

The Next proxy uses an exact method/path/ID allowlist and a 16 KiB streaming
JSON limit. It does not proxy image bytes. Nginx disables buffering for the
exact Moment SSE path and reuses the opaque asset byte locations.

## 9. Persistence and migration

Record revision `c19_record_20260712_03` adds:

- `moment_feed_sequence`;
- `moments`;
- `moment_audience_snapshots`;
- `moment_asset_references`;
- `moment_likes`;
- `moment_comments`;
- `moment_user_events`.

Asset revision `c19_asset_20260712_02` adds tagged scope columns and backfills
all Stage 4 data without changing logical identity. Downgrade refuses to discard
Moment data.

Record backup remains one PostgreSQL custom dump with dataset/revision/checksum
metadata. Its restore gate now requires the complete Moment schema and safety
columns before an atomic database swap. Asset backup continues to use one
checksummed PostgreSQL dump, active-object archive and exact manifest; the
generic manifest includes both chat and Moment objects.

No production store, network, URL, token or VPS is activated by this stage's
isolated acceptance.

## 10. Acceptance evidence

Final automated evidence passed:

- 72 Asset Service tests;
- 52 Record Service tests;
- 86 Barong C19 backend tests;
- 171 frontend tests, TypeScript checking, foundation verification and the
  production frontend build;
- 9 deployment/Nginx/restore-boundary tests, with 1 environment-only Nginx
  runtime test skipped because the binary is not installed.

An explicitly named isolated Record/Asset rehearsal reserved and published an
image Moment, verified the immutable audience ceiling and live block narrowing,
persisted a like and comment, emitted content-free events, rejected the tagged
Moment ticket through the legacy chat v1 inspection contract, and completed the
three-part deletion flow. Record revision `c19_record_20260712_03` ended with a
deleted content-cleared tombstone, six events and zero asset references; Asset
revision `c19_asset_20260712_02` ended with the bound Moment image in durable
delete-pending state and no active ticket.

The Record dataset was backed up as a checksummed PostgreSQL custom archive and
restored into a second fresh isolated deployment. Dataset/revision gates,
service health and the deleted tombstone/event/reference counts matched after
restore. Every rehearsal container, volume, network, temporary environment file
and backup artifact was then removed.
