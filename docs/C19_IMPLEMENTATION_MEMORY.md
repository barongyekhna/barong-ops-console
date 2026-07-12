# C19 Implementation Memory

- Decision date: `2026-07-11`
- Last verified: `2026-07-12`
- Status: Stages 1–6 completed; source and isolated acceptance verified
- Scope: Barong Ops Console internal communication system
- Product position: a basic global communication capability for every active authenticated user

This document records the agreed product goal, the current source-code reality,
the target architecture, and the boundaries that future implementation must
preserve. If a later explicit user decision conflicts with this document, update
this document together with that decision before changing C19 behavior.

## 1. Agreed Product Goal

C19 is the internal "small WeChat" area of Barong Ops Console.

The target product must allow every active authenticated platform user to:

- discover and communicate with every other active platform user, including
  across organizations and when either user has no organization;
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

Universal-user communication is the default product policy. C19 access is not
granted by RBAC, role, organization, membership or affiliation. A user has one
global communication card and may have zero, one or many affiliations. Friendship
is a social relationship and contact-management capability; it must not be
required merely to send a text message to another active internal member. A user
block, account disablement, revoked session, conversation membership or explicit
content privacy policy must still override the open communication default.
Losing an organization membership narrows explicit `org` Moment visibility but
does not remove C19 itself.

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

- The historical decision chain validated authenticated actor identity, C19
  contact identities, active C18 memberships, and a cross-organization
  permission policy. Stage 6 retired that admission model: an active
  authenticated user now has C19 regardless of permission, role, organization,
  membership, or affiliation.
- Same- and cross-organization communication now share the same universal-user
  admission rule. Explicit affiliation is descriptive context only.
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
organization. Any organization affiliations remain optional identity/display
context, while conversation access is determined by participant membership.

```text
Barong authenticated active user
  -> C19 frontend workspace
     -> C19 application API (/api/app)
        -> active session/user validation (Auth)
        -> optional affiliation resolution (C18, never a C19 admission gate)
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
           -> ChatAssetStore HTTP adapter
              -> independent C19 Asset API / gateway / worker / ClamAV
                 -> independent C19 Asset PostgreSQL and object volumes
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
     -> all active platform users
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
- image and file assets run initially on the current VPS as a separate,
  dataset-labelled Asset Service deployment with independent PostgreSQL,
  object volumes, networks, gateway, worker and malware scanner;
- a future asset VPS move restores the same dataset into fresh isolated volumes,
  preserves the single-writer rule, and changes only the Barong Asset API URL
  and Nginx gateway upstream;
- the main Barong database remains authoritative for identities, relationships,
  conversation/group control metadata, membership, and policy state. It never
  stores message or Moment bodies, comments, record/Moment events, image bytes,
  or file bytes;
- Moment bodies, immutable publish-audience ceilings, likes, comments, ordered
  image references and content-free Moment events share the portable Record
  Service, while Moment image bytes share the tagged portable Asset Service.

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

`ChatAssetStore` is the active authoritative port for image/file objects and
their immutable metadata. Its implemented contract supports:

- creating a short-lived upload authorization after server-side policy checks;
- polling finalize/status while the gateway, worker and scanner own promotion;
- preparing and committing an asset binding around the authoritative Record
  Service append, including exact-record repair after a lost commit response;
- issuing authorized, short-lived original/thumbnail transfer tickets;
- deleting or quarantining an object under retention/security policy;
- exposing provider-neutral metadata without provider credentials or physical
  paths.

The concrete binding is a strict authenticated HTTP adapter to the independent
Asset Service. There is no local fallback. If the URL/token is absent, the port
remains fail-closed; production activation is a separate reviewed configuration
operation and was not performed during isolated Stage 4 acceptance.

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
   - conversation, user, optional affiliation/organization snapshot,
     member/admin/owner role, join/leave timestamps, and membership state;
   - a direct conversation has exactly two active participants;
   - a group has exactly one active owner and may have admins/members;
   - membership history is retained for authorization and audit.

8. `c19_conversation_user_settings`
   - per-user pin, mute, archive, and notification preferences;
   - contains no message record and does not claim a read cursor until a real
     `ChatRecordStore` exists.

Message records, idempotency state, record events, and delivery/read positions
are not part of this local Barong persistence boundary; Stage 3 stores them only
in the independent Record PostgreSQL deployment. Stage 5 likewise stores Moment
drafts/content, immutable audience ceilings, likes, comments, image references
and content-free events only in that Record deployment. Stage 4/5 attachment
bytes and immutable object metadata live only in the independent Asset Service;
provider-neutral references live only with authoritative records.

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
session. An affiliation is always optional for base C19 use. Omission persists
as no affiliation even when the user has exactly one; the server never guesses
one. A supplied affiliation must belong to that user and is used only as an
explicit descriptive snapshot or `org` Moment audience selection.

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

Stage 4 additionally activates these participant-scoped asset controls:

- `POST /c19/conversations/{conversation_id}/assets/upload-intents`
- `POST /c19/conversations/{conversation_id}/assets/{asset_id}/finalize`
- `GET /c19/conversations/{conversation_id}/assets/{asset_id}`
- `POST /c19/conversations/{conversation_id}/records/{record_id}/assets/{asset_id}/access-intents`
- internal Nginx `auth_request` validation at
  `GET /c19/assets/transfers/authorize`

Stage 5 additionally activates these authenticated Moment controls:

- draft reservation and text/zero-to-nine-image publication;
- bounded feed/detail, like lists, comments and author deletion;
- desired-state like/unlike and idempotent comment creation/deletion;
- bounded content-free Moment events over HTTP recovery or SSE;
- Moment-scoped image upload/finalize/access controls through the shared Asset
  authorization boundary.

Actor identity comes only from the authenticated Barong session. Before every
record call, Barong revalidates the active user, conversation membership, and
the operation-specific block and recipient policy. C18/C19 affiliation is
validated only when the user explicitly invokes an organization-scoped display
or Moment rule; it is never required for base access. Administrators receive no
implicit private-chat access.

The following content APIs remain deliberately reserved for their approved
stages:

- message search or user-facing recall;
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
- register the global C19 module metadata and exact control-table boundary while
  keeping the interim user-facing module out of navigation until its runtime
  stages were ready;
- reserve only the `ChatRecordStore` and `ChatAssetStore` interfaces;
- keep all record and asset operations fail-closed;
- create no message, receipt, attachment, Moment, or content-outbox table and
  introduce no remote endpoint, credential, provider, or fallback store.

### Stage 2 - Durable Control Runtime

**Status: completed on `2026-07-11`.**

- replace process-local friendship and conversation registries with
  repositories using the Stage 1 control schema;
- synchronize profile/affiliation state with user and C18 membership lifecycle;
- preserve the C19A-E directory, deterministic-direct-ID, block, and cross-org
  concepts behind stable services while leaving admission policy replaceable;
- expose exact authenticated APIs for directory, friends/blocks,
  conversations, group membership, and conversation settings;
- add the interim C19 frontend shell for control operations without exposing a
  message composer or fabricated message/upload success.

Implemented Stage 2 behavior includes authoritative User/C19 active-state
validation, optional multi-affiliation directory projection, transactional
lifecycle sync, durable social/block state, deterministic direct conversations,
participant-scoped conversation access, cross-organization groups, exactly one
active group owner, group membership lifecycle, and durable per-user settings.
At that milestone the frontend route existed at `/c19` without navigation;
Stage 6 now exposes it globally to every authenticated active user.

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
- activated the interim C19 chat workspace with a real composer, bounded history
  recovery, retry semantics, receipt advancement, unread display, and no
  fabricated optimistic success. Latest and older history use explicit,
  contiguous bounded-window modes; records outside the visible history window
  cannot advance read receipts, and receipt safety is scoped to the exact user
  plus conversation;
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

**Status: completed on `2026-07-12` after isolated acceptance.**

- implemented and bound the authenticated HTTP `ChatAssetStore` adapter with no
  local persistence fallback;
- implemented images and ordinary files only, with provider-neutral immutable
  references stored by the Record Service;
- enforced stream/size, extension, MIME/magic, strict parser, image/archive bomb,
  malware/quarantine, lifecycle, ticket and authorization controls;
- implemented the browser upload/scan/bind/thumbnail/download flow and exact
  Nginx streaming boundary without exposing storage credentials or paths;
- deployed the initial portable runtime on the current VPS in isolated rehearsal
  resources and proved dataset-bound backup/restore into a second fresh stack.

### Stage 5 - Moments

**Status: completed on `2026-07-12` after isolated acceptance.**

- implemented durable drafts/posts, immutable publication-audience ceilings,
  ordered image references, likes, comments, tombstones and content-free events
  in the independent Record Service;
- implemented text and zero-to-nine-image publication, bounded feed/detail,
  deletion, likes, like lists, comments, pagination, polling recovery and SSE;
- enforced `public`, `org`, `friends`, and `private` visibility as explicit
  server-side policies: every read must satisfy both the immutable publication
  ceiling and current user/session, optional organization membership,
  C19/friend/block state, so access only narrows;
- generalized the portable Asset Service with tagged `moment_image` scope while
  preserving the exact Stage 4 chat v1 contract, and implemented short-ticket
  upload, scan, thumbnail, download and deletion authorization;
- implemented recoverable draft → prepare → publish → commit and
  delete-pending → asset-delete → deleted workflows without recomputing an
  already-published audience or exposing a partially deleted post;
- implemented responsive Moments UI without persisting post content, selected
  files, previews, tickets or cursors in browser storage.

### Stage 6 - Product Hardening and Release

**Status: completed on `2026-07-12` after source and isolated acceptance.**

- made C19 a native capability of every authenticated active user, independent
  of RBAC permissions, roles, organizations, memberships, or affiliations;
- made affiliation optional everywhere, removed implicit sole-affiliation
  selection, and migrated conversation affiliation snapshots to accept an exact
  null pair without weakening non-null ownership validation;
- registered the C19 manifest as globally active, release-ready and visible by
  default with no required permission manifest, while retiring old `c19.*`
  permission registry entries as inert historical audit data;
- completed responsive desktop/mobile behavior and a content-free global unread
  indicator backed by the exact batched Record Service summary API;
- added shared database-backed, hash-keyed write and SSE abuse controls, private
  aggregate operational snapshots, bounded default-dry-run retention, and
  coordinated Barong + Record + Asset disaster-recovery tooling;
- completed loading, empty, error, retry, reconnect, focus/visibility,
  keyboard-focus and reduced-motion behavior without browser-persisted C19
  content;
- verified the focused backend, external-store, deployment/DR and frontend
  suites plus TypeScript, build, compilation, shell and Git hygiene gates;
- left live protected production configuration, live bindings, and any new VPS
  untouched. Production activation remains a separate reviewed operation.

Voice and video calls are not a later step in this plan. Adding them requires a
new explicit product decision and a separate architecture/security review.

## 8. Non-Negotiable Security and Data-Ownership Principles

1. **Session identity is authoritative.** Never trust frontend-supplied sender,
   owner, organization, role, or membership claims.

2. **An active authenticated user is sufficient.** No role, permission,
   organization, organization membership or affiliation grants C19. Disabled
   users and revoked sessions cannot use it; session revocation must close
   real-time and asset access as well as ordinary HTTP access.

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
    - User/Auth owns authentication and active account state; C18 separately
      owns optional organization memberships.
    - C19 identity is one global communication profile plus zero or more
      descriptive affiliation projections.
    - Friendship is jointly scoped to a user pair; a block is private state owned
      by the blocker.
    - Direct conversations are participant-scoped; groups are governed by their
      owner/admin/member lifecycle.
    - A message is authored by its sender and accessible only under conversation
      membership policy; the independent service behind `ChatRecordStore` is
      its storage authority.
    - An asset is owned by its uploader and attached resource; the independent
      service behind `ChatAssetStore` is its storage authority.
    - A Moment is owned by its author and constrained by its server-side
      visibility policy.

12. **Record and asset storage are private infrastructure.** The current-VPS
    Record and Asset Services use isolated networks and authenticated
    service-to-service requests; neither PostgreSQL port is published. The Asset
    gateway is loopback-only and ClamAV is private. A later cross-VPS link must
    use private networking or HTTPS with a comparably strong identity boundary,
    encryption in transit and at rest, scoped credentials, rotation, and no
    public bucket/path trust.

13. **Media is untrusted input.** Filename and browser MIME are insufficient.
    Asset handling performs byte-signature/strict-format validation, bounded
    decoding and archive expansion, malware scanning, quarantine, safe rendering
    headers, and authorized short-lived retrieval.

14. **Privacy, retention, deletion, and recovery are product behavior.** They must
    be documented, testable, and consistent across Barong metadata, the Record
    Service, the Asset Service, caches, backups, and replicas.

## 9. Completion and Acceptance Standards

### Stage 1 acceptance

Stage 1 remains complete within the final Stage 6 contract because:

- a fresh database and an upgraded database both contain the managed C19 control
  schema through Alembic;
- one global profile per existing valid user and every valid multi-org
  membership are backfilled without guessing a primary organization or title;
- database constraints represent pair uniqueness, directed block ownership,
  direct conversation uniqueness, optional paired participant affiliation, and
  control-only conversation settings;
- the C19 module is globally registered with exact control-table boundaries;
  Stage 6 makes it active and visible by default with no required C19 permission
  and retires the interim `c19.*` registry entries;
- `ChatRecordStore` and `ChatAssetStore` were introduced as unbound, fail-closed
  ports at this foundation boundary and were bound only in their approved later
  stages;
- no record/asset VPS connection, configuration, credential, data write, or
  substitute local store was introduced at this foundation boundary;
- no local message, receipt, attachment, Moment, or content-outbox table exists;
- model, migration upgrade/downgrade, manifest, access-policy, storage-boundary,
  and static checks pass.

### Stage 2 acceptance

Stage 2 is complete because:

- directory/profile reads require an active User and global C19 profile, then
  left-load zero or more valid affiliations without making organization state an
  admission gate;
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
- the Stage 2 frontend shell provided directory, relationship, conversation,
  group, membership, and setting controls without fabricating later-stage
  message, upload, or Moments success; Stage 6 now exposes the completed route
  globally;
- backend control-runtime tests, frontend proxy/workspace tests, TypeScript
  checks, static checks, and the Stage 1 storage/migration boundary tests pass;
- no message body, receipt/read cursor, attachment, Moment, content outbox,
  external endpoint, VPS address, credential, provider adapter, or local
  fallback store was introduced.

### Stage 3 acceptance

Stage 3 is complete because:

- Barong message routes are participant-scoped and invoke only the authenticated
  HTTP Record Store adapter after active-user, session, block and conversation
  membership authorization;
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

### Stage 4 acceptance

Stage 4 is complete because:

- the Record Service stores ordered, typed, provider-neutral asset snapshots,
  preserves the exact text/emoji v1 idempotency hash, uses v2 for asset-bearing
  intent, and authorizes against immutable per-user record events;
- the Asset API, PostgreSQL 17, worker, streaming gateway and ClamAV are split by
  credentials, volumes and networks. Only the gateway is loopback-published;
  ClamAV alone has signature-update egress and its port is not published;
- 256-bit transfer tickets are stored only as hashes and enforce scope, expiry,
  bounded upload issuance, bounded download use, replay and lifecycle revocation;
- image, PDF, OOXML and ZIP processing is strict and bounded. Real PNG bytes
  passed scan/decode/thumbnail promotion; a real EICAR upload became
  `quarantined|malware_detected`, and a clean upload with ClamAV stopped became
  `quarantined|scanner_unavailable` with no active object;
- message persistence uses prepare → authoritative Record append → commit, and
  the exact durable record repairs a lost commit response without granting
  access to a different record, version or audience;
- current conversation membership, exact historical record audience and asset
  snapshot/version are all required for access. Administrative role is not a
  private-chat bypass;
- the browser keeps selected files, progress, preview URLs and short tickets in
  memory; it uses direct XHR byte upload, explicit scan state, lazy thumbnails
  and explicit downloads without persistent browser storage;
- Nginx accepts only exact opaque upload/download paths, authenticates every
  transfer through Barong, strips browser credentials before the gateway, and
  supports safe GET/HEAD/Range responses;
- the isolated runtime survived a PostgreSQL/API/worker/gateway restart and the
  original image SHA-256 remained identical after a newly authorized download;
- the coordinated backup produced a PostgreSQL custom dump, exact two-object
  manifest and deterministic object archive whose SHA-256 values matched the
  metadata. A second fresh isolated stack restored the same dataset/revision,
  revoked all old tickets and reproduced the exact manifest;
- a real PostgreSQL 17 Record Service migration from
  `c19_record_20260711_01` to `c19_record_20260711_02` preserved an existing v1
  record/hash, defaulted `intent_version=1`, installed the asset-reference
  constraints and started the real service healthy;
- final automated evidence passed 59 Asset Service tests, 71 Barong C19 backend
  tests, 29 Record Service tests, 166 frontend tests, 22 focused frontend C19
  tests, 9 asset deployment/Nginx tests, TypeScript checking, Python compilation,
  Bash syntax, Compose rendering and Git diff checks;
- every runtime rehearsal used explicitly named `stage4-rehearsal` or
  `stage4-restore` resources. Production containers/configuration and any future
  asset VPS were not changed or connected.

### Stage 5 acceptance

Stage 5 is complete because:

- Barong derives identity, affiliations, organizations, friends and bilateral
  blocks from current authoritative state; a browser cannot submit user IDs or
  raw organization IDs as an authorization grant, and no admin role bypasses
  private Moment access;
- Record publication freezes a maximum audience and every feed/detail,
  interaction, event and image authorization rechecks current policy, so an old
  cursor, friendship, affiliation or ticket cannot expand access;
- drafts, publications and comments use stable business-intent idempotency;
  lost publish/commit responses recover from the exact durable Record snapshot
  without recomputing audience or rebinding a different asset;
- author deletion hides and clears content first, durably requests every Asset
  deletion, then clears Record references; retries resume from any of the four
  lifecycle states and Asset tickets are revoked immediately;
- Moment events carry IDs, sequence and timestamps only. Application logs,
  validation errors, browser persistence and notification payloads do not carry
  Moment or comment text;
- the responsive workspace supports the composer, all four visibility modes,
  sequential upload of at most nine images, feed/detail, lazy image access,
  likes, comments, deletion, bounded HTTP/SSE recovery and failed-page latching;
- final automated evidence passed 72 Asset Service tests, 52 Record Service
  tests, 86 Barong C19 backend tests, 171 frontend tests and 9 deployment/
  Nginx/restore-boundary tests, with 1 environment-only Nginx runtime test
  skipped because the binary is absent; TypeScript, production build, Python
  compilation, Bash syntax and diff checks also passed;
- an isolated PostgreSQL/HTTP rehearsal published an image Moment, proved
  immutable-snapshot allow/deny plus current-block narrowing, persisted
  like/comment/events, authorized only the tagged Moment asset, completed the
  recoverable deletion workflow, and preserved the tombstone across restarts;
- a checksummed Record backup at revision `c19_record_20260712_03` restored into
  a second fresh isolated stack with the deleted Moment, six content-free events
  and zero surviving references, then passed health and dataset gates;
- all explicitly named Stage 5 containers, volumes, networks, temporary env
  files and backup artifacts were removed after acceptance. No new VPS was
  connected and no Stage 5 command activated the live production binding.

### Stage 6 acceptance

Stage 6 is complete because:

- every authenticated active user can reach C19 and use applicable directory,
  social, direct/group conversation, chat, asset, Moment and unread flows without
  an RBAC permission, role, organization, membership, or affiliation;
- zero-affiliation users are first-class: affiliations are left-loaded optional
  display/filter context, exact conversation snapshots may be a null pair, and
  `org` Moment publication requires a deliberate valid selection rather than an
  inferred sole affiliation;
- conversation membership, group role, bilateral block state, immutable plus
  current Moment visibility, active session state and exact Asset scope remain
  fail-closed privacy boundaries;
- all C19 write routes and SSE reconnects use shared database-backed limits keyed
  by content-free user/IP hashes and return explicit retry timing;
- private Record and Asset operational snapshots expose aggregate state only;
  retention is bounded and dry-run by default; coordinated full-system backup
  and restore-admission tooling binds Barong, Record and Asset evidence without
  creating a second writer;
- the focused Barong C19 suite passed `120` tests, combined Record and Asset
  suites passed `180`, deployment/DR/schema-admission/Nginx suites passed all
  `20` tests, and the frontend passed all `172` tests;
- supplemental permission/migration/config-lock checks passed `19` tests with `5`
  environment-dependent skips; TypeScript checking, Foundation verification,
  the production frontend build, Python compilation, Bash syntax and Git
  hygiene checks passed;
- the native-access migration upgraded an isolated PostgreSQL database through
  `20260712_01_c19_native_access`; focused tests also covered backfill and
  downgrade behavior;
- fresh isolated PostgreSQL 17 databases upgraded Record to
  `c19_record_20260712_04` and Asset to `c19_asset_20260712_03` with zero
  metadata drift, passed previous-revision downgrade/re-upgrade, exact
  retention replay/two-phase deletion, real blocking coordination and dataset
  locks, and a concurrent quota race with exactly one accepted reservation;
- live protected production configuration was not edited or activated, no new VPS
  was connected, and no live production restart or release was performed.

### Full C19 acceptance

C19's approved text/image/file/group/Moments product scope is complete because
Stages 1–6 collectively prove:

- two active users in the same organization and in different organizations can
  exchange persisted text/emoji messages and retrieve them after restart;
- duplicate sends are idempotent, message order is stable, history uses bounded
  cursor pagination, and delivery/read/unread state is monotonic;
- real-time reconnect resumes from a durable position without message loss or
  duplicate display;
- cross-organization groups support creation, owner/admin/member management,
  leave/removal/dissolution, concurrent changes, and durable group messages;
- images and files remain durably stored and authorized through the portable
  Asset Service whether it is on the current VPS or later moved intact;
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

As of `2026-07-12`, Stages 1–6 are implemented and verified at the source and
isolated-acceptance boundary. C19 is a globally visible native capability for
every authenticated active user; RBAC permissions, roles, organizations,
organization memberships and affiliations neither grant nor remove it. It has a
durable global directory and social runtime, participant-scoped direct chats,
cross-organization groups, membership/settings, durable text/emoji messages,
real image/file upload and retrieval, and Moments with four visibility modes,
zero-to-nine images, feed/detail, likes, comments, deletion and resumable
content-free events. The old process-local and fabricated-content routes are not
mounted.

The Record Service and Asset Service are independent portable deployment units.
Both run initially on the current VPS with their own PostgreSQL databases,
dataset identities, credentials, networks and backup/restore contracts; the
Asset Service additionally owns isolated object volumes, a streaming gateway,
worker and ClamAV. A later asset VPS move restores the unchanged dataset and
switches only the Asset control URL and Nginx byte upstream while enforcing one
writer.

Universal product admission does not weaken content privacy. Active conversation
membership, group roles, bilateral blocks, Moment audience/current-state rules,
active sessions and exact Asset scope remain mandatory. Affiliations are
optional descriptive context and an `org` Moment audience is always explicitly
selected.

Stage completion records implementation and non-production acceptance. The work
did not edit or activate live protected production configuration, connect a new VPS,
or issue a live production activation/restart command. Production rollout
remains a separate reviewed operation with generated secrets. Voice and video
calls remain outside the product scope.
