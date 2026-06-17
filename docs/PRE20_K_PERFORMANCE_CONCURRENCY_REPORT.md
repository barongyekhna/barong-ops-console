# PRE20-K Performance & Concurrency Risk Report

Audit date: 2026-06-17

Scope covered: `backend/app/`, `backend/app/services/`, `backend/app/middleware/`, `backend/app/sandbox/`, `backend/app/core/`, C17 observability, C18 multi-tenant layer, C19 IM system, database models and repositories, and frontend API consumption patterns.

Constraint honored: this audit only assesses risk. No code, index, deployment, or runtime behavior was changed.

## 1. Concurrency Risk Map

| Area | Shared or concurrent state | Current control | High-concurrency risk |
| --- | --- | --- | --- |
| C17 event collector | `DEFAULT_EVENT_EMITTER` uses an in-memory `Queue`, `deque`, counters, and daemon worker in `backend/app/services/event_collector.py:60-138`. | Local `threading.Lock` around buffer/counters. | P0 data loss under event flood: `put_nowait()` drops events on queue full and callers ignore the `False` result in `emit_event()` (`event_collector.py:88-100`, `214-249`). Per-worker buffers diverge. |
| C17D storage layer | `InMemoryStorageAdapter._records` is a mutable list in `backend/app/services/storage_layer.py:350-377`. | No lock and no persistence. | P0/P1 memory growth and inconsistent reads while records are appended, archived, filtered, or sorted (`storage_layer.py:420-470`). |
| C17E audit query engine | Mutable `_snapshot` and `_candidate_cache` in `backend/app/services/audit_query_engine.py:455-467`. | No lock around snapshot rebuild or cache mutation. | P1 stale/racy cache and O(N) rebuild cost on concurrent writes/queries (`audit_query_engine.py:658-730`). |
| C18D module bindings | Process-local `_MODULE_BINDINGS` in `backend/app/services/module_binding_service.py:33-34`. | Local `RLock`. | P0 multi-worker state divergence and restart loss. Reads scan all bindings (`module_binding_service.py:110-146`). |
| C18I shared modules | Process-local `_SHARED_MODULES` in `backend/app/services/shared_module_registry.py:49-50`; syncs directly into C18D private registry (`shared_module_registry.py:115-126`). | Local `RLock`, then separate C18D lock. | P0 state divergence between workers and between C18I/C18D if a process dies after one update path. |
| C13D emergency kill switch | Module globals `_global_kill_switch_*` in `backend/app/services/emergency_kill_switch.py:17-20`. | No lock, no DB/distributed state. | P0 inconsistent safety gate: one worker can block while another allows (`emergency_kill_switch.py:93-124`). |
| C19 conversations | Process-local `_DIRECT_CONVERSATION_REGISTRY` in `backend/app/services/conversation_service.py:41-42`. | Local `RLock`. | P0 accepted conversation state is not durable or shared across workers; list scans the whole registry (`conversation_service.py:126-200`). |
| C19 friend requests | Process-local `_FRIEND_REQUESTS` in `backend/app/services/messaging_permission.py:52-53`. | Local `RLock`. | P0 friend state diverges by worker and is lost on restart; list scans all requests (`messaging_permission.py:320-432`). |
| C19 message send | API accepts send through permission and cross-org checks (`backend/app/api/routes/messages.py:55-85`). | No durable message write in service path. | P0 accepted send is not persisted; event explicitly marks `persistence_implemented: False` and `websocket_implemented: False` (`cross_org_communication.py:420-443`, `469-543`). |
| C15 callback store | `CallbackExecutionStore` has `_bindings` and `_records` dicts in `backend/app/services/callback_handler.py:206-313`. | No lock, no durable backend. | P0 callback status races, lost `callbacks_received` increments, worker-local 404s, restart loss. |
| C15 DLQ | `DeadLetterQueueStore._records` dict in `backend/app/services/failure_handling.py:202-272`. | No lock, no durable retry queue. | P0 failure events and replay state lost; concurrent replay count updates race (`failure_handling.py:255-268`). |
| Auth/rate limit | DB-backed buckets in `backend/app/repositories/security.py:65-120`; login flow commits in `auth_service.py:210-337`. | Unique key plus transaction flush; no row lock or atomic increment. | P1 undercount or contention during brute-force bursts; account lockout counters also read-modify-write (`users.py:105-117`). |
| Middleware | Multiple layers validate the same session and commit `last_seen` writes (`main.py:249-290`, `api/deps.py:91-96`, `org_context.py:329-335`, `permission.py:212-248`, `data_isolation.py:181-190`). | Separate DB sessions per layer. | P1 high write amplification and row contention on `auth_sessions` under normal page/API load. |
| Sandbox/core | Sandbox models are frozen/mock-only and deny shared execution state (`sandbox/execution_context.py:85-115`, `205-261`, `430-455`). Core registries are mostly static tuples; settings use `lru_cache` (`core/config.py:155-157`). | Mostly immutable/local. | Low shared-state race risk, but execution provider concurrency/rate-limit policies are declared only, not enforced (`core/execution_providers.py:300-319`); sandbox resource control is mock-only (`sandbox/runner.py:45-60`, `sandbox/resource.py:142-190`). |
| Frontend API access | Client and proxy force `cache: "no-store"` (`frontend/src/lib/api.ts:32-39`, `frontend/src/app/api/backend/[...path]/route.ts:397-402`). | No client dedupe/cache. | P1 repeated auth, registry, permission, and provider calls amplify backend load. |

## 2. Race Condition Report

| ID | Risk | Evidence | Impact |
| --- | --- | --- | --- |
| RC-01 | Callback result update is non-atomic. | `CallbackExecutionStore.update_status_from_callback()` reads a record, validates transition, builds a copy, increments `callbacks_received` with `record.callbacks_received + 1`, then writes dict entries with no lock (`callback_handler.py:258-310`). | Concurrent callbacks for the same `context_id` can lose increments, accept invalid interleavings, or overwrite terminal state. |
| RC-02 | DLQ replay state is non-atomic. | `DeadLetterQueueStore.record_failure()` and `mark_replayed()` read/replace dict entries with no lock (`failure_handling.py:219-268`). | Replay count and terminal DLQ state can be overwritten under simultaneous failures/manual replays. |
| RC-03 | Distributed login rate limit increments can undercount. | `register_rate_limit_attempt()` loads a bucket, mutates `attempt_count += 1`, then flushes (`repositories/security.py:65-120`). There is no `FOR UPDATE`, optimistic version, or atomic SQL increment. | Multiple concurrent login attempts can observe the same count and write back a smaller total, delaying or bypassing rate limiting. |
| RC-04 | Account failed-login lockout can undercount. | `record_failed_login()` mutates `user.failed_login_count += 1` (`repositories/users.py:105-117`) after `auth_service.login()` reads the user (`auth_service.py:241-286`). | Concurrent invalid passwords against one account can lose increments and delay lockout. |
| RC-05 | Approval request check-then-create is not protected by a DB uniqueness invariant for active execution. | `request_approval()` checks `find_active_by_execution_id()` before creating (`approval_service.py:386-410`), while the model only declares unique IDs, not a partial unique pending approval by `execution_id` (`models/approval.py:13-53`). | Two workers can create duplicate pending approvals for the same execution. |
| RC-06 | Manual approval decisions and review decisions can race. | `apply_manual_decision()` loads workflow, applies a decision, saves workflow and decision without a row lock/version (`approval_service.py:307-344`). `decide_review()` overwrites review state directly (`repositories/reviews.py:55-68`). | Last writer wins; conflicting approvals/reviews can be accepted without deterministic conflict detection. |
| RC-07 | Job status can race with job events. | `create_job_event()` derives `from_status = job.status`, adds event, and mutates `job.status` (`repositories/jobs.py:69-90`). | Concurrent events can produce incorrect `from_status` and final job status. |
| RC-08 | Replay nonce commit is outside callback state transaction. | `verify_callback_signature()` registers nonce and idempotency keys (`callback_handler.py:132-181`). `register_replay_key()` commits immediately when DB is supplied (`replay_protection.py:75-93`). Callback store update occurs afterward (`callback_handler.py:371-386`). | A crash or store failure after nonce commit but before callback state update can permanently consume the callback retry key while no business state is recorded. |
| RC-09 | Emergency kill switch globals can be read mid-update and are process-local. | `set_global_kill_switch()` writes four globals with no lock (`emergency_kill_switch.py:106-124`). | Metadata can be inconsistent within a worker; safety state is inconsistent across workers. |

## 3. Locking & Deadlock Risk Report

No obvious hard deadlock cycle was found, but the lock model is insufficient for production concurrency.

| Area | Observation | Risk |
| --- | --- | --- |
| C18D/C19 local registries | `RLock` protects individual process-local dicts in conversation, friend request, and module binding services (`conversation_service.py:126-137`, `messaging_permission.py:320-338`, `module_binding_service.py:160-181`). | Protects threads inside one process only. It does not protect gunicorn/uvicorn multi-worker deployments or restart recovery. |
| C18I to C18D sync | `create_shared_module()` writes `_SHARED_MODULES` under one lock, releases it, then `_sync_c18d_binding()` writes C18D under the C18D private lock (`shared_module_registry.py:171-193`, `212-235`, `115-126`). | Current code avoids nested lock deadlock, but cross-module private state coupling creates partial-sync failure risk. |
| Callback and DLQ stores | Mutable dicts are not locked (`callback_handler.py:206-313`, `failure_handling.py:202-272`). | Race risk is higher than deadlock risk. |
| C17 event emitter | Uses a single `threading.Lock` for counters/buffer and `queue.Queue` for the drain path (`event_collector.py:60-138`). | Lock contention is bounded, but durability is absent and `queue.Full` causes loss. |
| C17 audit query engine | `_snapshot` and `_candidate_cache` have no lock (`audit_query_engine.py:455-467`, `724-730`). | Concurrent cache rebuilds can interleave; memory can grow as cache keys grow. |
| C18G data isolation | Request/org state uses `ContextVar`, which is appropriate for async request isolation (`data_isolation.py:59-78`). Event installation uses a process global `_events_installed` with no lock (`data_isolation.py:487-496`). | Context isolation is sound for request-local state. Event installer race is low likelihood at import/startup but not a distributed control. |
| Sandbox | Execution context models are frozen and transitions return copied models (`sandbox/execution_context.py:107-115`, `227-261`). | Low lock risk. It is not a real concurrent executor. |

Deadlock rating: Low to Medium. There is no detected cyclic lock chain, but shared private registries and unsynchronized dicts mean the dominant risk is race/data loss rather than deadlock.

Lock contention rating: Medium. Registry list operations copy/scan under locks, and C19/C18 registries can become hot if used as production state.

## 4. Multi-worker Consistency Failures

The system is not safe for multi-worker runtime state unless all process-local stores are treated as non-authoritative mock state.

| Failure | Evidence | Result |
| --- | --- | --- |
| C19 conversations split by worker | `_DIRECT_CONVERSATION_REGISTRY` is a module dict (`conversation_service.py:41-42`), and `/conversations/user/{user_id}` reads only that worker's registry (`api/routes/conversations.py:85-98`). | A conversation created on worker A can be invisible on worker B. |
| C19 friend state split by worker | `_FRIEND_REQUESTS` is a module dict (`messaging_permission.py:52-53`), and `/friends/list` has no DB source (`api/routes/friends.py:107-110`). | Friend acceptance/rejection may differ by request routing. |
| C19 accepted messages not durable | `send_message_after_cross_org_check()` builds schema objects and returns allowed without DB insert (`cross_org_communication.py:469-543`). Fetch/read endpoints are schema-only 501 (`api/routes/messages.py:118-141`). | Successful sends cannot be reliably fetched, replicated, or recovered. |
| C18 module visibility split by worker | `_MODULE_BINDINGS` is process-local (`module_binding_service.py:33-34`), with direct in-memory sync from shared module registry (`shared_module_registry.py:115-126`). | Module availability can differ per worker. |
| Kill switch split by worker | `is_global_kill_switch_enabled()` returns a module global (`emergency_kill_switch.py:102-124`). | Emergency stop cannot be trusted system-wide. |
| Callback bindings/results split by worker | Context binding endpoint writes `DEFAULT_CALLBACK_EXECUTION_STORE`; result endpoint reads the same local store (`api/routes/callback_handler.py:190-230`). | Callback routed to another worker may fail as "not bound"; restart loses pending results. |
| DLQ split by worker | `DEFAULT_DEAD_LETTER_QUEUE` is an in-memory store (`failure_handling.py:202-272`). | Failed jobs and manual replay state are not globally visible. |
| C17 buffers split by worker | `DEFAULT_EVENT_EMITTER` holds process-local recent buffer/stats (`event_collector.py:138`, `470-479`). | Observability views underreport and disagree by worker. |
| Replay fallback split by worker | `ReplayProtectionStore` is process-local if DB is omitted (`replay_protection.py:24-63`, `95-101`). | Replay protection is not distributed in fallback mode. |

Restart loss: C18D bindings, C18I modules, C19 conversations, C19 friend requests, C15 callback records, C15 DLQ records, and C17 in-memory observability state are lost on process restart.

## 5. Database Performance Risks

| Area | Evidence | Risk |
| --- | --- | --- |
| DB connection pool | Engine uses `create_engine(settings.database_url, pool_pre_ping=True)` only (`backend/app/db/session.py:14-17`). | Default pool sizing may be unsuitable for high-concurrency API plus middleware write amplification. |
| Message table | `messages` has indexes on `conversation_id`, `from_user_id`, `to_user_id` only and no `org_id` (`models/message.py:9-47`). | Conversation timeline queries need `(conversation_id, created_at)`; tenant scoping cannot rely on `org_id`. |
| Automation jobs/events | `automation_jobs` lacks explicit indexes on `module_id`, `agent_id`, `workflow_id`, `parent_job_id`, `requested_by_user_id`, `status`, `idempotency_key`, and `correlation_id`; `job_events.job_id` has no explicit index (`models/job.py:16-87`). Queries filter/list by job fields and events (`repositories/jobs.py:8-90`). | Large job/event tables will degrade; event listing can scan by FK. |
| Operation logs | Only `operation_id` is unique; common fields such as actor/action/target/job/result/request_id are not indexed (`models/operation_log.py:10-44`). List endpoint orders by id with offset (`repositories/operation_logs.py:116-140`). | Audit log growth will make offset scans and filtered investigations expensive. |
| Memory state | `memory_events`, `memory_summaries`, and access logs lack indexes on subject/job/agent/resource fields (`models/memory.py:11-88`). List repositories are global order-by-id with offset (`repositories/memory.py:10-25`, `73-88`, `139-155`). | Memory-state reads become global scans and do not scale by org/job/subject. |
| Approvals | Models only declare unique IDs, not indexes for `execution_id`, `status`, `requester_id`, `state`, `approval_id`, `workflow_id`, or decision filters (`models/approval.py:13-115`). Repositories filter by these fields (`repositories/approvals.py:100-149`, `215-234`, `295-320`). | Approval queues and active approval checks degrade; duplicate pending approval race is also not DB-enforced. |
| Reviews | `review_id` is unique but job/artifact/status/requested/assigned fields lack explicit indexes (`models/review.py:19-52`). Listing is global order-by-id with offset (`repositories/reviews.py:16-25`). | Review queues will degrade as records grow. |
| Permissions | `list_enabled_permissions()` loads all enabled permissions, then API slices in memory (`repositories/permissions.py:26-36`, `api/routes/permissions.py:104-119`). Assignment query joins registry and filters by user/enabled/expiry (`repositories/permissions.py:94-123`). | Registry reads over-fetch; assignment checks can become hot under route guards. |
| Organizations/memberships | Membership has indexes on `(user_id, org_id)` and `org_id` (`models/org_membership.py:20-27`) but no `(user_id,status)` or `(org_id,status)` index. Organization has owner index but status is not indexed (`models/organization.py:14-27`). | Org context resolution filters active memberships and owner active orgs repeatedly. |
| Global contacts | Directory builder disables org isolation and loads all joined contact rows (`global_contact_directory.py:77-93`, `repositories/global_contacts.py:36-60`). | Full-table join and Python sort under every directory request. |
| Replay nonce cleanup | Each nonce registration deletes all expired rows before checking duplicate (`repositories/security.py:143-168`). | Under callback floods this creates extra write load and table contention. |

Pagination risk: many repository APIs apply `limit/offset`, but high offsets are still expensive. Some C19/runtime endpoints return unpaginated in-memory lists.

Tenant filter risk: several foundation tables are global by design, but C19 `messages` has no `org_id`, and in-memory C18/C19 registries bypass DB-level tenant isolation entirely.

## 6. API Performance Bottlenecks

| Endpoint/pattern | Evidence | Bottleneck |
| --- | --- | --- |
| Control-plane and app middleware stack | Control plane middleware, org context, permission isolation, data isolation, and route dependencies can each validate the session (`main.py:249-290`, `api/deps.py:91-96`, `org_context.py:329-335`, `permission.py:212-248`, `data_isolation.py:181-190`). `validate_session()` commits `mark_session_seen()` (`auth_service.py:396-409`). | Multiple DB sessions and writes per request. High QPS can create row contention on `auth_sessions`. |
| `/permissions/registry` | Loads all enabled permissions, then slices in memory (`api/routes/permissions.py:104-119`). | Over-fetching and avoidable memory use. |
| Global contact directory | Loads and sorts all contacts (`global_contact_directory.py:77-93`). | Full directory rebuild per request. |
| C19 conversation list | Scans `_DIRECT_CONVERSATION_REGISTRY.values()` and sorts result (`conversation_service.py:181-200`). | O(total conversations) per user list, no pagination. |
| C19 friend list | Scans `_FRIEND_REQUESTS.values()` and sorts (`messaging_permission.py:423-432`). | O(total friend requests), no pagination. |
| C15 DLQ list | Returns all in-memory DLQ records and counts categories (`failure_handling.py:503-517`). | O(total failures), no durable query pagination. |
| C17 audit queries | Build candidate records from full storage snapshot/cache (`audit_query_engine.py:658-730`), and storage `_query()` filters/sorts in memory (`storage_layer.py:452-470`). | CPU and memory grow with audit volume. |
| Frontend API proxy | Client and proxy both use `cache: "no-store"` (`frontend/src/lib/api.ts:32-39`, `frontend/src/app/api/backend/[...path]/route.ts:397-402`). | No cache/dedupe for stable registries; every navigation hits backend. |
| Console boot | Protected layout nests auth, module access, adapter access, and route guards (`frontend/src/app/(console)/layout.tsx:9-20`). Auth refresh calls `/auth/me` on mount and after login (`auth-provider.tsx:42-80`). Module access calls `/modules/me` (`module-access-provider.tsx:43-75`). Adapter provider calls four registry/access endpoints in parallel (`adapter-access-provider.tsx:118-129`). | Console first load fans out into repeated registry/access/session checks. |
| User permission panel | Loads permission registry for each target user state transition (`user-permissions-panel.tsx:201-233`). | Repeated stable registry calls. |

## 7. C17/C18/C19 Runtime Stability Report

### C17 observability

Stability rating: High risk under event burst.

- `EventEmitter` is bounded but lossy. The queue size is 10,000 and recent buffer is 5,000 (`event_collector.py:21-22`, `60-74`). On full queue, `emit()` increments dropped and returns `False` (`event_collector.py:94-100`), but `emit_event()` does not surface that loss (`event_collector.py:214-249`).
- The drain worker is daemonized (`event_collector.py:80-84`), so queued events can disappear during process exit.
- C17D in-memory storage is unbounded and unsynchronized (`storage_layer.py:350-377`).
- C17E query cache/snapshot is mutable and unsynchronized (`audit_query_engine.py:455-467`, `724-730`).

### C18 multi-tenant layer

Stability rating: Medium to High risk under multi-worker production.

- C18G request context uses `ContextVar`, which is appropriate for async isolation (`data_isolation.py:59-78`).
- ORM scope and write guards exist (`data_isolation.py:340-359`, `454-485`), but they apply to DB-backed org-scoped models only. C18D/C18I module visibility state is not DB-backed.
- C18D `_MODULE_BINDINGS` and C18I `_SHARED_MODULES` are process-local (`module_binding_service.py:33-34`, `shared_module_registry.py:49-50`).
- Shared module registry writes C18D private module state directly (`shared_module_registry.py:115-126`), making consistency dependent on in-process ordering.
- Emergency kill switch is not system-wide because it is module-global only (`emergency_kill_switch.py:17-20`, `102-124`).

### C19 IM system

Stability rating: Critical risk for real IM usage.

- Direct conversation registry is in memory only (`conversation_service.py:41-42`).
- Friend requests are in memory only (`messaging_permission.py:52-53`).
- Message send path validates permission and cross-org gates but does not persist a `MessageRecord`; event payload marks persistence and websocket as not implemented (`messages.py:55-85`, `cross_org_communication.py:420-443`, `469-543`).
- Fetch/read message APIs are schema-only 501 (`api/routes/messages.py:118-141`).
- Attachments are schema-only 501 (`api/routes/attachments.py:25-55`).
- The `messages` DB model exists but does not include `org_id` and lacks a timeline index (`models/message.py:9-47`).

### Sandbox and core runtime

Stability rating: Low shared-state risk, not a high-concurrency execution runtime.

- Sandbox runner explicitly performs no runtime process creation, no DB mutation, no filesystem write, no external provider/callback/network call, and no real CPU/memory enforcement (`sandbox/runner.py:45-60`, `880-915`).
- Resource enforcer validates logical policies only and does not inspect/control host resources (`sandbox/resource.py:142-190`, `320-390`).
- Execution context models are frozen and copy-on-transition (`sandbox/execution_context.py:85-115`, `227-261`), so memory-state concurrency risk is low inside the mock boundary.
- Core execution provider concurrency/rate-limit policies are declared only and cannot enforce runtime limits (`core/execution_providers.py:300-319`).

## 8. Rate Limiting & Security Performance Gaps

| Gap | Evidence | Risk |
| --- | --- | --- |
| Login rate limit is DB-backed but not atomic. | Three buckets are registered sequentially (`rate_limiter.py:45-100`); each bucket update is read-modify-write (`repositories/security.py:65-120`). | Brute-force bursts can undercount or create contention. |
| Account lockout counter is not atomic. | Failed login increments `failed_login_count` in memory then flushes (`repositories/users.py:105-117`). | Concurrent bad passwords can delay lockout. |
| Distributed replay protection has partial-commit boundaries. | `register_replay_key()` commits per key when DB is supplied (`replay_protection.py:75-93`); callback registers nonce and idempotency separately (`callback_handler.py:165-181`). | Partial replay state can block legitimate retries. |
| Replay fallback is process-local. | `DEFAULT_REPLAY_PROTECTION_STORE` is in memory (`replay_protection.py:24-63`). | If any path omits DB, multi-worker replay protection is ineffective. |
| API flood protection is narrow. | Login has rate limiting; C19 conversations/friends/messages, callback binding/results, DLQ list/replay, registry endpoints, global contacts, and audit queries have no distributed flood control in reviewed paths. | A valid session can create CPU/memory/DB load spikes. |
| Session validation writes on read-heavy paths. | `validate_session()` commits `mark_session_seen()` on validation (`auth_service.py:396-409`), and middleware/deps can validate multiple times per request. | Normal UI traffic can become a write-heavy workload and contention point. |
| Frontend load amplifies security checks. | Console boot calls auth/module/provider/permission data without client cache (`auth-provider.tsx:42-80`, `module-access-provider.tsx:43-75`, `adapter-access-provider.tsx:118-129`). | Security middleware and session writes are multiplied by frontend fan-out. |

## 9. Critical Risks (P0)

### P0-1: data loss under concurrency

- C17 events are dropped on queue overflow and there is no durable event sink in the emitter path (`event_collector.py:88-100`, `214-249`).
- C15 callback result state is held in unsynchronized memory dicts and can be lost on restart or overwritten by concurrent callbacks (`callback_handler.py:206-313`, `371-416`).
- C15 DLQ is an in-memory dict with no durable retry queue (`failure_handling.py:202-272`, `503-672`).
- C19 message sends can return allowed without persisting message records (`cross_org_communication.py:420-443`, `469-543`).
- Replay nonce can be committed before callback state is updated, causing retry loss after partial failure (`callback_handler.py:132-181`, `replay_protection.py:75-93`).

### P0-2: state divergence across workers

- C18 module bindings and shared modules are process-local (`module_binding_service.py:33-34`, `shared_module_registry.py:49-50`).
- C19 conversations and friend requests are process-local (`conversation_service.py:41-42`, `messaging_permission.py:52-53`).
- Emergency kill switch is process-local and not distributed (`emergency_kill_switch.py:17-20`, `102-124`).
- Callback bindings/results and DLQ records are process-local (`callback_handler.py:206-313`, `failure_handling.py:202-272`).

### P0-3: unbounded memory growth

- C17D `InMemoryStorageAdapter._records` appends without bound (`storage_layer.py:350-377`).
- C17E `_candidate_cache` has no eviction policy (`audit_query_engine.py:455-467`, `689-730`).
- C19 conversation/friend registries have no TTL, pagination, or durable compaction (`conversation_service.py:41-42`, `181-200`; `messaging_permission.py:52-53`, `423-432`).
- C15 callback and DLQ stores have no TTL/size bounds in the default stores (`callback_handler.py:206-313`, `failure_handling.py:202-272`).

P0 conclusion: the application is not safe for true high-concurrency, multi-worker production operation if these runtime stores are expected to be authoritative.

## 10. System Performance Score

| Dimension | Score |
| --- | --- |
| Concurrency safety | 42% |
| Throughput risk level | High |
| Stability rating | C- / Not high-concurrency production safe |
| Multi-worker safety | Critical gaps |
| Data durability under runtime failures | Critical gaps |
| DB query scalability | Medium to High risk |
| Frontend load efficiency | Medium risk |

Score rationale:

- Positive: request-local org context uses `ContextVar`; several process-local registries use local locks; security tables have unique hashes and basic indexes; sandbox mock execution avoids shared mutable runtime state.
- Negative: authoritative runtime state for C15/C17/C18/C19 is mostly in process memory; several counters and status transitions are read-modify-write without row locks or optimistic concurrency; observability and DLQ paths can lose data; repeated session validation creates avoidable write pressure; high-volume query paths lack tenant/time/status indexes.

Overall assessment: barong-ops-console can support low-concurrency mock/admin-console workflows, but it is not resilient enough for real high-concurrency, multi-worker operation where state durability, worker consistency, or complete observability are required.
