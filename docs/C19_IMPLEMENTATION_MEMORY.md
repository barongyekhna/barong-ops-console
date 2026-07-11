# C19 Implementation Memory

- Decision date: `2026-07-11`
- Status: Stages 1, 2, and 3 completed; authoritative baseline for Stage 4 planning
- Scope: Barong Ops Console internal communication system
- Product position: a global internal communication capability shared by all active organization members

This document records the agreed product goal, the current source-code reality,
the target architecture, and the boundaries that future implementation must
preserve. If a later explicit user decision conflicts with this document, update
this document together with that decision before changing C19 behavior.

## 1. Agreed Product Goal

C19 is the internal "small WeChat" area of Barong Ops Console.

The target product must allow active members of every organization to:

- discover and communicate with active members of every other organization;
- start one-to-one conversations without treating organization boundaries as a
  business-data sharing grant;
- create cross-organization groups and manage group membership;
- send text, emoji, images, and ordinary files;
- publish and browse Moments, with explicit visibility rules;
- receive unread counts, delivery/read state, and real-time updates;
- use the experience on both desktop and mobile layouts.

Voice calls and video calls are explicitly out of scope. Existing C19H voice and
video schema reservations must not be activated, exposed in the UI, connected to
a provider, or used as acceptance criteria for this implementation.

All-member communication is the default product policy. Friendship is a social
relationship and contact-management capability; it must not be required merely
to send a text message to another active internal member. A user block, account
disablement, inactive organization membership, or an explicit security policy
must still override the open communication default.

## 2. Historical A-H Baseline Before Stages 1 and 2

The bullets in this section preserve the state of the original C19 A-H protocol
layer before Stages 1 and 2. The durable runtime described in Sections 6, 7,
and 9 supersedes its process-local and schema-only behavior. The historical
source remains useful design material but is not mounted as an application API.

### C19A - Contact Identity

- `ContactIdentity` separates communication identity from authentication.
- The current model includes `user_id`, display name, organization identity,
  title, role, and timestamps.
- Repository, service, read/update routes, and authorization rules exist.
- The managed Alembic chain does not yet provide the full durable C19 runtime
  migration expected by this model.
- Identity fields are snapshots for communication display; they are not login
  credentials and must never become an alternative authentication source.

### C19B - Global Contact Directory

- A global directory contract exists and groups contacts by `A-Z` and `#`.
- Chinese names use the existing pinyin-initial grouping logic.
- The directory joins contact identity with active C18 organization membership.
- Cross-organization visibility is already represented in the contract and is
  consistent with the agreed all-member communication policy.
- At that historical baseline, no C19 frontend consumed the directory.

### C19C - Message Contract

- The current message contract defines text/emoji messages and the forward-only
  `sent -> delivered -> read` state model.
- Message-to-conversation participant validation is designed.
- Current send behavior does not durably write a message record.
- History and read-state endpoints are schema-only/`501` boundaries.
- A successful-looking response without persistence is not an acceptable future
  implementation and must be removed before C19 is exposed.

### C19D - Conversation Contract

- Direct conversations use a deterministic ID derived from the canonical sorted
  participant pair, preventing duplicate direct threads.
- Direct conversation create/list/get logic currently uses process-local state.
- A group conversation type and minimum participant rule are reserved.
- Group creation currently returns a reserved/`501` result and has no durable
  membership or message fan-out behavior.

### C19E - Cross-Organization Policy

- The current decision chain validates authenticated actor identity, C19 contact
  identities, active C18 memberships, and cross-organization permission policy.
- Same-organization communication is allowed after identity and membership
  validation; cross-organization communication passes the C19E/C18 permission
  boundary.
- Cross-organization communication does not grant access to either
  organization's products, keys, workflows, files, or other business records.
- Policy decisions and security-relevant changes must remain auditable.

### C19F - Friendship and Messaging Permission

- Friend request and relationship contracts exist with
  `none/pending/accepted/rejected` states.
- The current runtime registry is process-local and is not authoritative.
- Existing rules permit text/emoji before friendship and reserve richer media
  capabilities for accepted friends.
- The final product keeps open text communication, but media and social-policy
  rules may be tightened independently. Blocking always overrides friendship and
  open communication.

### C19G - Attachment Contract

- Metadata contracts exist for image, file, video, and audio attachments.
- Current upload/fetch endpoints are schema-only/`501`; no object storage,
  transfer, malware scanning, or durable attachment lookup is implemented.
- For the agreed scope, only images and ordinary files are to be implemented.
  Audio/video call transport is out of scope, and video/audio attachment support
  is not part of the first implementation target.

### C19H - Communication Extensions

- Schema reservations exist for group chat, Moments, voice calls, and video
  calls.
- Group chat and Moments are now approved product scope and must be promoted from
  schema reservations into real domain/application capabilities in controlled
  phases.
- Voice and video calls remain reserved only.
- Current C19H routes are not mounted and no frontend exists.

## 3. Final Logical Architecture

C19 is a global C-system capability, not a child module owned by one
organization. A user's organization remains part of identity and policy context,
while conversation access is determined by participant membership.

```text
Barong authenticated member
  -> C19 frontend workspace
     -> C19 application API (/api/app)
        -> identity and active-membership validation (Auth + C18)
        -> C19 policy layer
           -> directory / friendship / block policy
           -> direct-conversation participant policy
           -> group role and membership policy
           -> Moments visibility policy
        -> C19 domain services
           -> contact identities
           -> relationships
           -> conversations and groups
           -> messages and read state
           -> attachments
           -> Moments, likes, and comments
        -> storage ports
           -> local C19 control-metadata repositories
           -> ChatRecordStore HTTP adapter
              -> independent C19 Record Service
                 -> independent C19 Record PostgreSQL
           -> ChatAssetStore (reserved and fail-closed)
        -> real-time event gateway
        -> C17 security/audit events and operational metrics
```

The frontend workspace is a global C19 capability:

```text
C19
  -> Messages
     -> direct conversations
     -> group conversations
  -> Contacts
     -> all active organization members
     -> friends and friend requests
     -> blocked users (private to the actor)
  -> Moments
     -> feed
     -> publish
     -> likes and comments
```

Desktop should use a three-pane layout where practical: list, active content,
and contact/group details. Mobile should use separate list, thread/feed, and
detail views while preserving the same API and state semantics.

## 4. Storage Decision and Current Deployment Boundary

The infrastructure decision is:

- chat records run initially on the current VPS, but in an independent
  `c19_record_service` deployment with its own PostgreSQL database, named
  volume, private network, schema migration chain, service token, and cursor
  signing secret;
- Barong reaches that service only through the `ChatRecordStore` HTTP adapter;
  the record database is never attached to Barong and neither the database nor
  service port is published on the host;
- `C19_RECORD_DATASET_ID` gives one logical record dataset a stable identity
  across backup, restore, and VPS migration. Moving it does not create a second
  writable authority;
- a future VPS move uses a logical PostgreSQL custom-format archive plus its
  SHA-256/revision/dataset metadata, followed by a record-service URL/token
  switch. No Barong schema or C19 application API changes during that move;
- image and file assets remain assigned to a later asset VPS. Stage 3 reserves
  only their provider-neutral interface and keeps all asset operations
  fail-closed;
- the main Barong database remains authoritative for identities, relationships,
  conversation/group control metadata, membership, and policy state. It never
  stores message bodies, record receipts/events, image bytes, or file bytes.

The following boundaries remain mandatory:

- no message body or chat asset may be written to the Barong database, ordinary
  application logs, Redis, the Barong filesystem, or browser persistence;
- no in-memory/local-file fallback may present itself as durable record or asset
  storage;
- a send succeeds only after the authoritative record service durably accepts
  it; store failure is a stable fail-closed response;
- application authorization is evaluated by Barong before every record-store
  operation. The service token is transport authentication, not conversation
  authorization;
- chat archives and their metadata are private content-bearing material and
  must remain outside Git and ordinary Docker build contexts.

The two dependency-inversion ports have distinct current states:

### ChatRecordStore

`ChatRecordStore` is the active authoritative port for message records and their
delivery/read timeline. Its implemented contract supports:

- appending a text/emoji record using a stable
  `client_message_id`/idempotency key;
- fetching bounded conversation pages by opaque cursor;
- advancing delivery/read positions monotonically;
- returning unread counters and resumable conversation/user event positions;
- applying retention or deletion commands under an explicit policy.

The concrete binding is an authenticated HTTP adapter to the independent Record
Service. Opaque history/event cursors, record ordering, idempotency tombstones,
participant positions, deletion/retention audit, and user event sequences belong
to the record database. The adapter has no local persistence fallback.

### ChatAssetStore

`ChatAssetStore` is the future authoritative port for image/file objects and
their immutable metadata. Its contract may reserve operations equivalent to:

- create a short-lived upload authorization after server-side policy checks;
- finalize and verify an uploaded object;
- resolve an authorized, short-lived download/preview locator;
- delete or quarantine an object under retention/security policy;
- expose metadata without exposing provider credentials or physical paths.

No concrete asset adapter, fallback adapter, remote configuration, signed URL
issuer, or network call is active. Attachment upload/download APIs remain
fail-closed until Stage 4 connects the approved asset store.

## 5. First-Stage Persistence Boundary

The first implementation stage persists control metadata in the existing Barong
PostgreSQL deployment. Exact names may follow repository naming conventions, but
the responsibility split is fixed.

### Tables in scope

1. `c19_profiles`
   - one global communication profile per internal user;
   - references the authoritative user but does not choose or duplicate a
     primary organization;
   - contains display metadata only, never credentials.

2. `c19_affiliations`
   - one projection for every authoritative C18 organization membership;
   - preserves multi-organization membership without guessing a primary
     organization, department, or title;
   - supplies the organization context captured when a user joins a
     conversation.

3. `c19_friend_requests`
   - requester, recipient, pending/accepted/rejected/cancelled state, timestamps;
   - prevents duplicate active requests for the same pair;
   - all actor fields are derived from the authenticated session.

4. `c19_relationships`
   - canonical user pair and lifecycle timestamps;
   - friendship does not grant organization data access;
   - removal is auditable and idempotent.

5. `c19_user_blocks`
   - blocker, blocked user, active state, timestamps;
   - block ownership and list visibility belong only to the blocker;
   - an active block prevents new communication and social interaction.

6. `c19_conversations`
   - conversation ID, `direct/group` type, creator, lifecycle state, timestamps;
   - direct IDs remain deterministic for a canonical participant pair;
   - contains no message body, latest-message body, attachment bytes, or remote
     storage secret.

7. `c19_conversation_members`
   - conversation, user, organization snapshot, member/admin/owner role,
     join/leave timestamps, and membership state;
   - a direct conversation has exactly two active participants;
   - a group has exactly one active owner and may have admins/members;
   - membership history is retained for authorization and audit.

8. `c19_conversation_user_settings`
   - per-user pin, mute, archive, and notification preferences;
   - contains no message record and does not claim a read cursor until a real
     `ChatRecordStore` exists.

Message records, idempotency state, record events, and delivery/read positions
are not part of this local Barong persistence boundary; Stage 3 stores them only
in the independent Record PostgreSQL deployment. Moment and attachment records
remain outside the Stage 1-3 Barong schema.

### Constraints and indexing

- All foreign keys reference durable user/conversation records where applicable.
- Direct conversation uniqueness is enforced by the database, not only service
  code.
- Canonical friendship pairs and active friend requests have database uniqueness
  constraints.
- Conversation-member lookup is indexed by both conversation and user.
- Group-owner uniqueness and membership lifecycle invariants are enforced in a
  transaction with row locking or an equivalent concurrency strategy.
- Fresh install and upgrade paths are both represented by Alembic migrations;
  ORM metadata alone is not deployment completion.

## 6. Durable Application API Boundary

All C19 product APIs are authenticated internal application APIs under
`/api/app/c19`. No public API is allowed. Stage 2 activated these durable
control-metadata routes:

- `GET /c19/directory`
- `GET /c19/profiles/{user_id}`
- `GET/POST /c19/friend-requests`
- `POST /c19/friend-requests/{request_id}/accept`
- `POST /c19/friend-requests/{request_id}/reject`
- `POST /c19/friend-requests/{request_id}/cancel`
- `GET /c19/friends`
- `DELETE /c19/friends/{user_id}`
- `GET /c19/blocks`
- `POST/DELETE /c19/blocks/{user_id}`
- `GET /c19/conversations`
- `POST /c19/conversations/direct`
- `GET /c19/conversations/{conversation_id}`
- `GET/PATCH /c19/conversations/{conversation_id}/settings`
- `POST /c19/groups`
- `PATCH/DELETE /c19/groups/{conversation_id}`
- `POST /c19/groups/{conversation_id}/members`
- `DELETE /c19/groups/{conversation_id}/members/{user_id}`
- `POST /c19/groups/{conversation_id}/leave`
- `POST /c19/groups/{conversation_id}/transfer-owner`

The global directory filter is named `affiliation_org_id`; it is a filter, not
an authorization context. Actor identity always comes from the authenticated
session. An affiliation may be omitted only when the relevant user has exactly
one currently authorized affiliation. Multiple affiliations require an
explicit `affiliation_id`; the server never chooses the first one.

The old `/contacts`, `/friends`, `/conversations`, `/comm/cross-org`,
`/messages`, and `/attachments` C19 prototype routes are no longer mounted.
Their source remains historical protocol material only and cannot act as a
process-local or fabricated-success shadow runtime.

Stage 3 additionally activates these participant-scoped record APIs:

- `POST/GET /c19/conversations/{conversation_id}/messages`
- `POST /c19/conversations/{conversation_id}/delivered`
- `POST /c19/conversations/{conversation_id}/read`
- `GET /c19/conversations/{conversation_id}/unread`
- `GET /c19/conversations/{conversation_id}/resume`
- `GET /c19/events/tail`
- `GET /c19/events` as a JSON recovery page or bounded SSE page stream selected
  by the request `Accept` header

Actor identity comes only from the authenticated Barong session. Before every
record call, Barong revalidates the active user, authoritative C18 membership,
C19 affiliation, conversation membership, and the operation-specific block and
recipient policy. Administrators receive no implicit private-chat access.

The following content APIs remain deliberately reserved for their approved
stages:

- message search or user-facing recall;
- attachment upload, finalize, fetch, preview, or download;
- Moments publish/feed/like/comment operations;
- voice/video call routes of any kind.

No legacy schema-only content endpoint is mounted. Every active Stage 3 message
route is bound to the authoritative Record Service and fails closed if that
service is unavailable.

## 7. Implementation Stages

### Stage 1 - Durable Control Foundation

**Status: completed on `2026-07-11`.**

- add managed migrations for the first-stage tables;
- safely backfill one global profile per valid user and one affiliation per
  valid C18 membership without inventing a primary organization or title;
- register the global C19 module and its explicit permission catalog while
  keeping the user-facing module hidden/planned;
- reserve only the `ChatRecordStore` and `ChatAssetStore` interfaces;
- keep all record and asset operations fail-closed;
- create no message, receipt, attachment, Moment, or content-outbox table and
  introduce no remote endpoint, credential, provider, or fallback store.

### Stage 2 - Durable Control Runtime

**Status: completed on `2026-07-11`.**

- replace process-local friendship and conversation registries with
  repositories using the Stage 1 control schema;
- synchronize profile/affiliation state with user and C18 membership lifecycle;
- preserve the C19A-E directory, deterministic-direct-ID, block, cross-org, and
  permission concepts behind stable services;
- expose exact authenticated APIs for directory, friends/blocks,
  conversations, group membership, and conversation settings;
- add the hidden C19 frontend shell for control operations without exposing a
  message composer or fabricated message/upload success.

Implemented Stage 2 behavior includes authoritative User/C18/C19 active-state
validation, multi-affiliation directory projection, transactional lifecycle
sync, durable social/block state, deterministic direct conversations,
participant-scoped conversation access, cross-organization groups, exactly one
active group owner, group membership lifecycle, and durable per-user settings.
The frontend route exists at `/c19` but is deliberately absent from navigation.

### Stage 3 - Independent Chat Record Runtime

**Status: completed on `2026-07-11`.**

- implemented the independent FastAPI Record Service and its own PostgreSQL 17
  schema/Alembic chain for deployment on the current VPS;
- bound Barong through a static-token authenticated HTTP `ChatRecordStore`
  adapter with strict response validation and no local fallback;
- implemented durable text/emoji records for participant-authorized direct and
  group conversations, opaque cursor history, gap-free per-conversation order,
  stable idempotent retries, deletion tombstones, monotonic delivery/read state,
  unread positions, and deletion/retention audit commands;
- implemented content-free durable user events, an event-tail bootstrap,
  bounded authenticated SSE delivery, reconnect/resume, and HTTP recovery;
- activated the hidden C19 chat workspace with a real composer, bounded history
  recovery, retry semantics, receipt advancement, unread display, and no
  fabricated optimistic success. Latest and older history use explicit,
  contiguous bounded-window modes; hidden new records cannot advance read
  receipts, and receipt safety is scoped to the exact user plus conversation;
- isolated record data in its own volume/private network and documented logical
  backup/restore migration so the same dataset can move to another VPS without
  changing application APIs or the Barong schema.

PostgreSQL 17 migration evidence used an isolated source and fresh target. The
source contained 25 visible records with latest sequence 26; backup metadata
bound dataset identity, Alembic revision, archive format, and SHA-256. Restore
validated required schema, restored to a temporary database, atomically swapped
databases, health-checked the service, and reproduced the same record/event
state after a service restart. A second restore against that populated target
created and checksum-verified its pre-restore archive before the atomic swap.
The original target database was retained under a timestamped
`c19_rollback_*` name for the rollback window. A separate post-swap fault
injection made the Record Service exit during startup; the script atomically
restored the original database and isolated the failed restored dataset under
`c19_failed_*`. The final rehearsal used a dataset-labelled fresh volume and
verified the env identity, existing container identity, actual mounted volume,
and archive dataset together. A deliberate revision mismatch also proved that
the fully restored but unaccepted `c19_restore_*` database is removed before
exit.

### Stage 4 - External Image/File Asset Runtime

**Status: interface reserved and fail-closed; asset data remains assigned to the
later asset VPS.**

- implement and bind a real `ChatAssetStore` adapter;
- support images and ordinary files only;
- enforce size, extension, MIME signature, authorization, malware/quarantine,
  retention, and short-lived access rules;
- bind asset metadata to durably stored messages without leaking physical paths
  or provider credentials.

### Stage 5 - Moments

- define durable post, visibility, like, and comment ownership models;
- implement text/image publishing, feed pagination, delete, likes, and comments;
- enforce public/all-members, organization-only, friend-scoped if approved, and
  private/self visibility as explicit server-side policies;
- reuse `ChatAssetStore` for Moment images only after Stage 4 is operational;
- generate notifications without leaking hidden post content.

### Stage 6 - Product Hardening and Release

- complete responsive desktop/mobile UI and global unread indicators;
- extend the Stage 3 record runbook into full-system backup/restore and disaster
  recovery, and add distributed rate limiting, abuse controls, observability,
  retention jobs, and release operations;
- run multi-user, multi-organization, multi-worker, restart, reconnect, and
  concurrency acceptance suites;
- promote through staging with explicit evidence before production enablement.

Voice and video calls are not a later step in this plan. Adding them requires a
new explicit product decision and a separate architecture/security review.

## 8. Non-Negotiable Security and Data-Ownership Principles

1. **Session identity is authoritative.** Never trust frontend-supplied sender,
   owner, organization, role, or membership claims.

2. **Active internal membership is required.** Disabled users and users without
   an active organization membership cannot use C19. Session revocation must
   close real-time access as well as HTTP access.

3. **Cross-org chat is not cross-org business access.** A conversation permits
   only access to that conversation's authorized communication resources.

4. **Participant membership is the conversation boundary.** Only active members
   may list, read, send, or retrieve assets for a conversation. Historical access
   after leaving a group must follow an explicit, tested policy.

5. **Group roles are server-controlled.** Owner transfer, admin assignment,
   member removal, dissolution, and concurrent updates must be transactional and
   auditable.

6. **Blocking is fail-closed.** A block overrides open communication,
   friendship, group invitations, direct sends, and Moment interaction as defined
   by policy. The blocked party must not receive the blocker's private block-list
   metadata.

7. **No fabricated success.** A message is not `sent`, an upload is not
   `uploaded`, and a read state is not advanced unless the authoritative store
   confirms the operation. Store unavailability returns a stable failure.

8. **Idempotency and monotonic state are mandatory.** Duplicate retries must not
   duplicate messages, memberships, requests, likes, or comments. Delivery/read
   state may only advance.

9. **Content is excluded from ordinary audit logs.** Audit events may record
   actor, resource ID, policy decision, timestamp, and outcome, but not message
   bodies, private Moment text, attachment bytes, credentials, or signed URLs.

10. **Administrative role is not blanket content access.** Owners and organization
    administrators do not automatically receive the right to read private chats.
    Any future compliance access requires an explicit, narrowly scoped, audited
    policy and a separate approval.

11. **Data ownership is explicit.**
    - C18/User owns authentication and active organization membership.
    - C19 identity is a communication snapshot of that authoritative identity.
    - Friendship is jointly scoped to a user pair; a block is private state owned
      by the blocker.
    - Direct conversations are participant-scoped; groups are governed by their
      owner/admin/member lifecycle.
    - A message is authored by its sender and accessible only under conversation
      membership policy; the independent service behind `ChatRecordStore` is
      its storage authority.
    - An asset is owned by its uploader and attached resource; `ChatAssetStore`
      is its future storage authority.
    - A Moment is owned by its author and constrained by its server-side
      visibility policy.

12. **Record and asset storage are private infrastructure.** The current-VPS
    Record Service uses an internal network and authenticated service-to-service
    requests; PostgreSQL has no host-published port. A later cross-VPS link and
    the asset VPS must use private networking or HTTPS with a comparably strong
    identity boundary, encryption in transit and at rest, scoped credentials,
    rotation, and no public bucket/path trust.

13. **Media is untrusted input.** Filename and browser MIME are insufficient.
    Future asset handling requires byte-signature validation, size limits,
    quarantine/malware controls, safe rendering headers, and authorized
    short-lived retrieval.

14. **Privacy, retention, deletion, and recovery are product behavior.** They must
    be documented, testable, and consistent across Barong metadata, the Record
    Service, the future asset store, caches, backups, and replicas.

## 9. Completion and Acceptance Standards

### Stage 1 acceptance

Stage 1 is complete only when:

- a fresh database and an upgraded database both contain the managed C19 control
  schema through Alembic;
- one global profile per existing valid user and every valid multi-org
  membership are backfilled without guessing a primary organization or title;
- database constraints represent pair uniqueness, directed block ownership,
  direct conversation uniqueness, participant affiliation, and control-only
  conversation settings;
- the C19 module is registered as global, planned, and hidden with explicit
  `c19.*` permissions and exact control-table boundaries;
- `ChatRecordStore` and `ChatAssetStore` exist only as unbound ports, with tests
  proving message/asset actions fail closed;
- no record/asset VPS connection, configuration, credential, data write, or
  substitute local store has been introduced;
- no local message, receipt, attachment, Moment, or content-outbox table exists;
- model, migration upgrade/downgrade, manifest, permission, storage-boundary,
  and static checks pass.

### Stage 2 acceptance

Stage 2 is complete because:

- directory/profile reads require an active User, an active C19 affiliation, an
  active authoritative source C18 membership, and an active organization;
- user, organization-owner, and membership create/enable/disable/add/remove
  lifecycle paths synchronize profiles and affiliations before the original
  transaction commits;
- friendship, friend-request, directed block, direct-conversation, group,
  participant, and user-setting state is database-backed rather than
  process-local;
- direct conversations use deterministic IDs and database uniqueness, social
  pairs use canonical serialization, and group ownership changes use locked
  transactions with exactly one active owner;
- blocks are private to their owner, override new social/conversation/group
  interaction in either direction, and return non-disclosing denial errors;
- only active conversation participants can read or change their conversation
  control metadata; platform and organization administrators receive no
  implicit private-conversation access;
- the exact authenticated `/api/app/c19` control routes and strict frontend
  proxy allowlist are mounted while all legacy process-local/fake-content routes
  are unmounted;
- the hidden frontend provides directory, relationship, conversation, group,
  membership, and setting controls, but contains no message composer, file
  picker, upload action, or Moments publisher;
- backend control-runtime tests, frontend proxy/workspace tests, TypeScript
  checks, static checks, and the Stage 1 storage/migration boundary tests pass;
- no message body, receipt/read cursor, attachment, Moment, content outbox,
  external endpoint, VPS address, credential, provider adapter, or local
  fallback store was introduced.

### Stage 3 acceptance

Stage 3 is complete because:

- Barong message routes are participant-scoped and invoke only the authenticated
  HTTP Record Store adapter after active User/C18/C19 authorization;
- the independent Record Service owns message bodies, order, idempotency ledger
  and tombstones, participant positions, unread state, durable user events, and
  deletion/retention audit without adding content tables to Barong;
- text/emoji sends become successful only after durable append; identical
  retries return the same record, conflicting intent is rejected, and a deleted
  idempotency key cannot recreate or disclose the original content;
- history and event APIs use bounded opaque cursors; SSE is bounded and
  session-revalidated, while tail/bootstrap and HTTP recovery preserve a
  resumable durable position;
- delivery and read positions advance monotonically, `read` never exceeds
  `delivered`, and unread state is derived by the authoritative store;
- the frontend composer, history paging, retry handling, unread/receipt state,
  SSE reconnect, and bounded recovery are wired to the real APIs without a fake
  success path or browser-persisted message cache;
- the service and PostgreSQL are isolated from the Barong database and host
  ports, secrets are split by process, content logs are suppressed, and asset
  routes/storage remain fail-closed;
- the independent test suite, Barong adapter/API suite, frontend C19 suite, and
  an actual PostgreSQL 17 backup/restore/restart rehearsal pass;
- the rehearsal restored 25 visible records with latest sequence 26 to a fresh
  target, with matching dataset identity, archive SHA-256, schema revision,
  idempotency/receipt state, health checks, and post-restart verification;
- restore activates a validated temporary database through an atomic rename and
  retains the prior database as `c19_rollback_<UTC timestamp>` for an explicit
  rollback window;
- a populated-target rehearsal checksum-verified the pre-restore archive, and a
  post-swap service-start failure rehearsal proved automatic restoration of the
  original target database without leaving the configured database name on the
  failed dataset;
- the final scripts reject mismatched volume/container/dataset identity, and a
  revision-mismatch rehearsal proved that pre-swap temporary chat data is
  cleaned instead of accumulating outside retention.

### Full C19 acceptance

C19 as a product is complete only after separately approved later stages also
prove:

- two active users in the same organization and in different organizations can
  exchange persisted text/emoji messages and retrieve them after restart;
- duplicate sends are idempotent, message order is stable, history uses bounded
  cursor pagination, and delivery/read/unread state is monotonic;
- real-time reconnect resumes from a durable position without message loss or
  duplicate display;
- cross-organization groups support creation, owner/admin/member management,
  leave/removal/dissolution, concurrent changes, and durable group messages;
- images and files are durably stored on the approved asset VPS, safely
  validated, authorized, previewed/downloaded, quarantined, and deleted;
- Moments publishing, visibility, feed pagination, likes, comments, deletion,
  blocking, and notification privacy pass multi-user tests;
- inactive/disabled members lose access promptly and cannot continue through an
  existing real-time connection or stale asset link;
- content does not leak into logs, traces, metrics, error messages, browser
  storage, or unauthorized notification payloads;
- backup, restore, retention, deletion, and disaster-recovery exercises cover
  Barong control metadata plus both independent content stores;
- desktop and mobile flows meet accessibility, empty/loading/error/reconnect, and
  large-history performance expectations;
- staging evidence covers multiple users, organizations, workers, restarts,
  rate limits, failures, and recovery before production activation;
- no voice-call or video-call capability has been enabled.

## 10. Decision Summary

As of `2026-07-11`, Stages 1, 2, and 3 are implemented. C19 has a durable global
control runtime and hidden workspace for directory, social state,
participant-scoped direct conversations, cross-organization groups, membership,
settings, and durable text/emoji chat. The old process-local and
fabricated-content routes are not mounted.

The Stage 3 deployment unit is an independent Record Service and PostgreSQL
stack for the current VPS. Its boundary has been proven portable through a
dataset- and SHA-bound PostgreSQL 17 backup/restore/restart rehearsal, so a later
VPS move changes only infrastructure and the Barong service binding. Stage
completion here records implementation and isolated acceptance; this work did
not silently rewrite protected production env files or switch the live Barong
backend. Production activation follows the reviewed first-deployment procedure
with generated secrets. Image/file assets remain represented only by the
fail-closed `ChatAssetStore` interface for Stage 4. Voice and video calls remain
outside the product scope.
