# PRE20-A Global Architecture Audit

Audit date: 2026-06-16

Scope: C01-C19 full-system architecture audit for `barong-ops-console`.

Mode: read-only source, docs, migration, and frontend route review. No runtime production execution, no migration execution, no API/schema/code change. This report file is the only generated artifact.

Risk grading:

- P0 = system-level crash, data leakage, or permission loss of control.
- P1 = production risk or high-concurrency risk.
- P2 = structural or maintainability risk.

Overall verdict: C20 entry is not recommended. The system has a coherent control-plane direction, but C18 multi-tenant isolation and C19 IM persistence are not closed, C17 observability is mostly non-durable, and several C13-C15 execution/control-plane boundaries are contract-only or blocked by deployment semantics.

## Audit Dimensions A-G

### A. Architecture Robustness

- Responsibilities are partially separated: auth/session, RBAC, module registry, adapters, execution gates, sandbox, observability, tenant OS, and IM are split into distinct modules.
- The separation is not yet enforceable end to end. C18 tenant isolation is implemented as middleware/service policy, but most core C01-C17 tables do not carry `org_id`, so C18G cannot scope them.
- No explicit import-level circular dependency was found in the reviewed paths, but there are logical coupling loops:
  - C19 cross-org communication mutates C18D module binding internals directly.
  - C18 shared-module registry writes into C18D private in-memory state.
  - C15 signed webhook/callback routes are mounted under the session-protected control plane while also using `require_internal_rbac`, creating a caller-model conflict.
- Cross-layer violations exist:
  - C19 service code reaches into C18 binding internals instead of using a stable adapter/repository.
  - Frontend proxy allowlists only older C01-C17 surfaces; C18/C19 backend APIs are not represented in the frontend route model.
  - Global RBAC routes still query tenant-relevant core data without org scoping.

### B. Concurrency Risk

- Shared process state exists in module binding, shared modules, conversations, friend requests, callback execution store, emergency kill switch, C17 event collector, and C17 in-memory storage.
- Several shared maps use `RLock`, which protects only a single Python process. Multi-worker, multi-pod, and restart scenarios lose state or diverge.
- `CallbackExecutionStore` and `InMemoryStorageAdapter` are non-durable and not suitable as production coordination primitives.
- Login rate limiting increments `attempt_count` through read-modify-write repository logic without row-level locking or atomic update, so concurrent login attempts can lose increments.
- Session validation updates `last_seen_at`; because middleware and dependencies can validate the same session in the same request chain, concurrent writes are amplified.
- C17 log/trace collection uses queue and ring-buffer memory. Queue overflow drops events, and multiple workers produce inconsistent audit views.

### C. Architecture Gaps

- C18 and C19 ORM models exist, but migrations do not create `organizations`, `org_memberships`, `contact_identities`, `messages`, or conversation/friend/attachment persistence tables.
- C19 has mounted routes, but multiple APIs are schema-only or 501:
  - message fetch/read
  - attachment upload/fetch
  - group conversation behavior
- C10 sandbox and C09 providers remain mock/no-op/safe-contract execution paths.
- C17 storage, replay, audit query, and anomaly detection are mostly in-memory or schema-level components.
- C15 webhook/callback validates signatures/replay but does not dispatch a real n8n execution path.
- UI/backend mismatch is material: C18/C19 backend APIs are not exposed through frontend navigation or proxy allowlist.

### D. Security Weaknesses

- Cross-org data exposure risk is P0 because core tables such as jobs, artifacts, reviews, memory, errors, operation logs, registry records, approval records, and auth-adjacent records are not org-scoped in managed migrations.
- Permission bypass paths exist where C18F middleware cannot resolve both `org_id` and `module_id`; in those cases it passes through and leaves older global RBAC dependencies in control.
- C18G only scopes ORM classes that have an `org_id` column. Models without `org_id` remain globally visible through repository queries.
- C19 global contact directory can expose all contact identities to any active organization member if that is not an intentional product policy.
- Webhook replay protection is DB-backed when a DB session is supplied, but callback result binding remains process-memory only.
- Debug docs are disabled for prod/staging by config, and public webhook/n8n paths are blocked by the security firewall and frontend proxy. No immediate debug-route exposure was found in the reviewed configuration.

### E. Data Consistency

- C17 audit/log/trace is not a single durable source of truth. `operation_logs` is DB-backed, but C17 event collector, structured logs, traces, storage snapshots, replay, and anomaly state are not consistently persisted.
- C18 `org_id` coverage is incomplete across the existing managed schema. Only C18/C19-specific models declare `org_id`; most C01-C17 records do not.
- C19 identity immutability is not DB-enforced. `CONTACT_IDENTITY_IMMUTABLE_FIELDS` is used by the service as the controlled update field set for `name`, `org_name`, and `title`, so the naming and enforcement semantics are inconsistent.
- Orphan data risk is high: messages lack managed persistence and org linkage; conversations and friend requests are memory-only; core records can reference module/user/job identifiers without tenant ownership.
- Schema drift is confirmed between ORM models, docs, and migrations.

### F. Scalability Risk

- Multi-org scale is not safe until org-scoped persistence is added to core entities and all list/detail repositories filter by org context.
- Dynamic module onboarding is partially represented by registries/contracts, but C18 module binding and shared modules are process-memory state.
- C20+ expansion is blocked by mixed permission systems and hardcoded module/action rules.
- Hardcoded module IDs exist, including drift between `integration.n8n_test_bridge` and `n8n_test_bridge`.
- Static frontend proxy allowlists and navigation create deployment friction for new C18/C19/C20 modules.

### G. Technical Debt

- Deprecated, placeholder, mock, reserved, and schema-only markers are widespread in C08-C10, C15, C17, and C19.
- Permission logic is duplicated across static RBAC, explicit permission assignments, and C18F org/module permission isolation.
- Temporary process-memory stores are used for production-shaped features.
- C19 identity naming conflicts with behavior: fields named immutable are mutable under service rules.
- C18/C19 docs and schemas are ahead of migrations and frontend integration.

## 1. System Overview Map

Text architecture map:

```text
Browser / Console UI
  -> Next.js backend proxy allowlist
  -> FastAPI app
     -> global middleware:
        control-plane isolation
        security headers
        C17 audit event collector
        C18G data isolation
        C18F permission isolation
        C18H org context
     -> route groups:
        /api/public
        /api/app
        /api/control-plane
     -> SQLAlchemy repositories
     -> PostgreSQL managed by backend/alembic/versions
```

C01-C02: environment and infrastructure are centralized through `core/config.py`, FastAPI app setup, middleware, DB session, and Alembic migrations.

C03-C05: users, auth sessions, RBAC roles, login hardening, explicit permission registry, and assignment APIs exist. Static RBAC and DB permission assignment both remain active.

C06-C09: module isolation, module registry, adapter registry, execution provider registry, and no-connect execution contracts exist. Runtime execution is still blocked/mock/no-op by design.

C10-C12: sandbox runner and approval schemas/tables exist. Sandbox is safe mock execution. Approval persistence exists, but C13E does not show a positive path for approved `approval_required` execution.

C13-C16: control plane, emergency kill switch, module switches, capability binding, external dependency governance, webhook/callback signing, replay nonce protection, and security hardening exist mostly as contract gates.

C17: observability contains event collection, structured logs, execution traces, storage layer, replay, audit query, and anomaly detection. Most components are in-memory or schema-oriented.

C18: multi-tenant OS has org context, org lifecycle, org membership, module binding, shared module registry, permission isolation, and data isolation. Persistence is incomplete and core tables are not tenant-scoped.

C19: IM system has contact identity, global directory, conversations, cross-org communication, messaging permission, friend requests, messages, and attachments. It is largely API/schema/service-level, with missing managed persistence for the main runtime data.

## 2. Module Dependency Graph

High-level dependency graph:

```text
C01/C02 config + infrastructure
  -> FastAPI app + middleware + DB session

C03 auth/session/users
  -> C04 static RBAC
  -> C05 explicit permission registry
  -> route dependencies

C06/C07 module isolation + registry
  -> C08 adapter contracts
  -> C13 module switch / execution flow gate
  -> C14 dependency + capability gates
  -> C09 provider contracts
  -> C10 sandbox runner

C12 approvals
  -> C13E execution flow gate
  -> approval tables

C15 workflow/webhook/callback
  -> C13/C14/C09/C10 contracts
  -> C16 signing/replay/security
  -> C17 event collector

C17 observability
  <- middleware, auth, C15, C18, C19, foundation writes
  -> in-memory storage/replay/anomaly components
  -> operation_logs table for selected audit records

C18 tenant OS
  -> org context middleware
  -> org/membership models
  -> C18F permission isolation
  -> C18G data isolation
  -> in-memory module binding/shared modules

C19 IM
  -> C18 org membership and module binding
  -> contact identities
  -> in-memory conversations/friend requests
  -> message decision envelopes
  -> C17 operation/event logging
```

Problematic dependency edges:

- `C19 -> C18D private state`: cross-org communication writes directly into `_MODULE_BINDINGS`.
- `C18 shared modules -> C18D private state`: shared module registry writes into `_MODULE_BINDINGS`.
- `C15 external ingress -> control-plane session middleware`: signed system ingress depends on human/session control-plane access.
- `C18G -> ORM org_id columns`: isolation works only where models expose `org_id`.
- `Frontend proxy -> static allowlist`: module/API availability depends on static route strings.

## 3. Critical Risks

### P0-01: Tenant isolation is not enforceable for core data

Evidence:

- Managed migrations in `backend/alembic/versions` create foundation, permission, approval, auth session, and C16 tables, but do not add `org_id` to core C01-C17 entities.
- Route handlers such as `backend/app/api/routes/jobs.py`, `artifacts.py`, and `reviews.py` list global records through repositories after global RBAC checks.
- C18G data isolation only scopes ORM classes with an `org_id` column.

Impact: users with a valid global role can read or mutate records across organizations because the database schema cannot express tenant ownership for most existing data.

### P0-02: C18/C19 ORM-model-to-migration drift can crash tenant and IM APIs

Evidence:

- ORM models exist for organizations, org memberships, contact identities, and messages.
- No managed migration creates `organizations`, `org_memberships`, `contact_identities`, or `messages`.
- C18/C19 routes call repositories that expect those tables.

Impact: a database built from the current Alembic chain can raise runtime SQL errors when C18/C19 APIs are used. This is a production crash risk for the tenant OS and IM surfaces.

### P0-03: C18F permission isolation can be bypassed when org/module context is absent

Evidence:

- `resolve_permission_request_context` returns `None` unless both `org_id` and `module_id` can be resolved.
- When context is `None`, the middleware passes through to the older route dependencies.
- Several legacy app routes do not carry org/module identifiers and use only static RBAC.

Impact: C18F does not operate as a universal mandatory access-control layer. The system can fall back to global permissions on tenant-relevant resources.

## 4. High Risks

### P1-01: Process-memory state is used for production-shaped features

Affected areas:

- C18 module bindings: `_MODULE_BINDINGS`
- C18 shared modules: `_SHARED_MODULES`
- C19 direct conversations: `_DIRECT_CONVERSATION_REGISTRY`
- C19 friend requests: `_FRIEND_REQUESTS`
- C15 callback execution store
- C13 emergency kill switch
- C17 event buffers and in-memory storage adapter

Impact: state diverges across workers, disappears on restart, and cannot support HA or horizontal scaling.

### P1-02: C17 observability is non-durable and can drop events

Evidence:

- Event collector uses `queue.Queue(maxsize=10000)` and `deque(maxlen=5000)`.
- Structured logs, execution traces, storage/replay, and anomaly detection are not wired to a durable production backend.

Impact: incident response, replay, audit search, and anomaly detection cannot be trusted as complete records.

### P1-03: Rate limiting has a concurrent lost-update risk

Evidence:

- Security repository increments `attempt_count` through read-modify-write logic.
- No row lock or atomic SQL increment was found in the reviewed path.

Impact: high-concurrency brute-force attempts can undercount attempts and delay lockout/rate-limit enforcement.

### P1-04: Signed webhook/callback ingress conflicts with control-plane isolation

Evidence:

- Webhook gateway and callback receiver are mounted under `/api/control-plane`.
- The global control-plane middleware requires an authenticated session cookie and admin/system/owner role.
- The routes also call `require_internal_rbac`, which creates a system principal check but does not authenticate the external HTTP caller.

Impact: external n8n/system callbacks cannot cleanly call the signed ingress path without a console session. This blocks production integration semantics.

### P1-05: C13E approval-required execution appears fail-closed without approved pass-through

Evidence:

- `_c12_block_reason` returns `c12_approval_bypass` when approval is required but status is `not_required`.
- For any approval-required request, it returns `c12_approval_not_cleared`.
- A positive `approved` status path was not found in the reviewed function.

Impact: once live execution is introduced, approved workflows may remain blocked unless the gate semantics are extended.

### P1-06: C19 message send is not a durable messaging system

Evidence:

- Send returns a cross-org decision envelope.
- Message history fetch and read marking return 501 schema-only notices.
- Attachments return 501 placeholder notices.
- Conversations and friend requests are memory-only.

Impact: users can receive apparent send success without durable message, delivery, read, attachment, or replay semantics.

### P1-07: Module ID drift around n8n test bridge

Evidence:

- Registry/docs/frontend use `integration.n8n_test_bridge`.
- `backend/app/repositories/n8n_test.py` uses `N8N_TEST_MODULE_KEY = "n8n_test_bridge"`.

Impact: module registry lookup, permission binding, workflow binding, and UI/runtime identity can diverge.

### P1-08: UI/backend surface mismatch for C18/C19

Evidence:

- Frontend proxy allowlist and navigation expose C01-C17-style routes.
- C18/C19 routes such as orgs, memberships, module binding, contacts, conversations, messages, friends, and cross-org communication are absent from the frontend route model.

Impact: backend capabilities cannot be operated or validated from the console UI, and future auth/proxy policy can silently block new modules.

### P1-09: Permission systems have semantic drift

Evidence:

- Static RBAC, explicit DB permission assignment, and C18F org/module permission isolation all exist.
- Different routes use different dependencies and bypass semantics.

Impact: permission meaning differs by route family, making audits and least-privilege policy hard to prove.

## 5. Medium Risks

### P2-01: Contract-only execution components are broad

C08 adapters, C09 providers, C10 sandbox, C14 model/dependency gates, and C15 workflow dispatch are intentionally mock/no-op/contract-first. This is safe for non-production execution, but it is not production execution readiness.

### P2-02: Static registries limit dynamic module onboarding

Module definitions, adapter contracts, provider contracts, workflow registry, dependency bindings, module switches, and frontend routes are mostly static code/config lists.

### P2-03: C18F module action rules are hardcoded

`K-series`, `C-series`, and `P-series` action rules are embedded in service code. Unknown module IDs fall back to broad default action sets.

### P2-04: Private-state mutation creates brittle module boundaries

C18 shared modules and C19 cross-org communication write directly into C18D module binding private variables. This is a boundary and maintainability issue.

### P2-05: Contact identity immutability semantics are confusing

Fields named immutable are used as controlled mutable fields in update logic. This increases policy misunderstanding risk.

### P2-06: Placeholder/deprecated/reserved markers are widespread

The codebase contains many schema and UI markers for `placeholder`, `reserved`, `deprecated`, `mock`, and `schema_only` behavior. That is acceptable during staged buildout, but must be tracked before a seal.

## 6. Architecture Breakpoints

1. Schema breakpoint: ORM models and C18/C19 services expect tables that Alembic does not create.
2. Tenant breakpoint: C18 isolation middleware exists, but core table schemas lack tenant keys.
3. Permission breakpoint: global RBAC, explicit permissions, and C18F org/module checks coexist without a single enforcement contract.
4. Control-plane breakpoint: signed webhook/callback system ingress is placed behind session-based control-plane middleware.
5. Observability breakpoint: C17 defines log/trace/replay/anomaly models but does not persist them as a unified durable event store.
6. UI breakpoint: C18/C19 backend APIs are not represented in frontend navigation/proxy.
7. Runtime breakpoint: C13E/C15/C10 provide safety gates and mock execution, not a complete production execution path.
8. IM breakpoint: C19 communication decisions exist without durable message, conversation, attachment, delivery, or read-state persistence.

## 7. Concurrency Risk Zones

| Zone | State | Protection | Risk |
| --- | --- | --- | --- |
| C18 module binding | process dict | `RLock` | diverges across workers; lost on restart |
| C18 shared modules | process dict | `RLock` | diverges across workers; mutates C18D internals |
| C19 conversations | process dict | `RLock` | no durable conversation identity |
| C19 friend requests | process dict | `RLock` | no durable friend/request state |
| C15 callback store | process dict | no durable backend | callback state lost after restart |
| C13 kill switch | module globals | no distributed lock | worker-local kill state |
| C17 event collector | queue + deque | local lock | event drop and per-worker audit split |
| C17 in-memory storage | list-backed adapter | no production coordination | replay/query inconsistency |
| C16 rate limit buckets | DB row read-modify-write | unique insert handling only | concurrent increment lost-update |
| auth session `last_seen_at` | DB writes on validation | normal transaction | high write amplification |

## 8. Security Weakness Report

| Risk | Severity | Finding | Required direction |
| --- | --- | --- | --- |
| Cross-org data exposure | P0 | Core tables and routes are globally scoped. | Add tenant ownership to schema and enforce org filters in repositories/routes. |
| Permission bypass fallback | P0 | C18F passes through when org/module context is missing. | Make tenant context mandatory for tenant routes or explicitly classify safe global routes. |
| C18G coverage gap | P0 | Isolation only works for models with `org_id`. | Add `org_id` or explicit global-resource classification to all persistent models. |
| C15 ingress mismatch | P1 | Signed webhook/callback routes require control-plane session. | Split system ingress auth from human control-plane auth. |
| C19 global directory exposure | P1 | Active org users can query global contact directory. | Define privacy policy and enforce org/friend/visibility rules. |
| Replay persistence boundary | P1 | Nonce protection is DB-backed in reviewed routes, but callback result store is memory-only. | Persist callback binding/result state with idempotency constraints. |
| Debug route exposure | P2 | Docs are disabled in prod/staging by config; no exposed debug route found. | Keep this as an automated deployment check. |

## 9. Data Consistency Report

### C17 log/trace consistency

Status: not consistent enough for production audit.

`operation_logs` provides durable audit records for selected workflows, but C17 event collection, structured logs, traces, storage, replay, audit query, and anomaly detection are not one durable append-only data model. Trace/log correlation can be incomplete if queue overflow, process restart, or multi-worker execution occurs.

### C18 org_id coverage

Status: failed for C20 readiness.

`org_id` is not present across most existing managed C01-C17 tables. C18G cannot enforce tenant isolation on tables that lack tenant columns, and repository list calls do not consistently filter by org context.

### C19 identity immutability

Status: partially defined, not immutably enforced.

Contact identity policy exists at schema/service level, but the field naming is contradictory and DB-level immutability is absent. Direct repository usage or future service paths can bypass the intended policy unless centralized constraints are added.

### Orphan data

Status: high risk.

Missing C18/C19 migrations and tenant keys allow orphan records by module, job, user, org, conversation, and message relationships. Memory-only conversation/friend state cannot be reconciled with durable users/contact identities after restart.

### Schema drift

Status: confirmed.

Docs and ORM models describe C18/C19 tables and behavior that are not present in the managed Alembic schema. C19 message/conversation/attachment API contracts exceed current persistence.

## 10. Scalability Assessment

Multi-org scaling: not ready. Tenant ownership is not a universal schema property, and C18 middleware cannot compensate for missing DB columns.

Horizontal scaling: not ready. Process-memory module binding, shared modules, conversations, friend requests, callback store, kill switch, C17 buffers, and in-memory storage will diverge across workers.

Dynamic module onboarding: partially ready at contract level, not runtime ready. Registries are static, proxy routes are static, and C18 module binding is not durable.

C20+ extensibility: blocked by mixed permission systems, missing tenant schema, static route allowlists, and module ID drift.

Operational scale: constrained. C17 cannot guarantee complete audit/replay data, and rate limiting can undercount in concurrency.

## 11. Technical Debt List

- Multiple permission models: static RBAC, DB permission assignment, and C18F isolation.
- Broad owner bypass semantics across several layers.
- In-memory production-shaped stores in C18, C19, C15, C17, and C13.
- Missing migrations for C18/C19 managed runtime tables.
- Missing `org_id` on most foundation tables.
- Global list repositories for jobs, artifacts, reviews, and related foundation data.
- C19 message read/history/attachment/group APIs are schema-only.
- C17 replay/anomaly/storage are not durable.
- C15 webhook/callback routes mix signed system ingress with human control-plane middleware.
- `integration.n8n_test_bridge` versus `n8n_test_bridge` module ID drift.
- C18/C19 frontend routes and navigation absent.
- C18 shared module and C19 communication services mutate C18D private in-memory state.
- C13 kill switch is process-local.
- C13E approval-required path lacks an observed positive approved branch.
- Contact identity immutable-field naming conflicts with update behavior.
- Hardcoded module action rules and static module series policy.
- Placeholder/deprecated/reserved/mock markers remain across backend schemas, services, docs, and frontend UI.

## 12. C20 Readiness Assessment

Decision: do not enter C20 seal.

Required minimum before C20:

1. Add managed migrations for C18 organizations, memberships, module bindings, shared modules, and C19 contact/message/conversation/friend/attachment persistence.
2. Add org ownership or explicit global-resource classification to all persistent C01-C19 tables.
3. Make C18 org context and C18F permission checks mandatory for all tenant routes.
4. Refactor core repositories/routes to filter by org context and verify cross-org denial tests.
5. Replace process-memory production state with durable stores or explicitly mark endpoints non-production.
6. Split external signed webhook/callback ingress from session-only control-plane routes.
7. Persist C17 event/log/trace/replay records or downgrade C17 claims to best-effort diagnostics.
8. Align module IDs and remove `n8n_test_bridge` versus `integration.n8n_test_bridge` drift.
9. Add frontend proxy/navigation support or explicitly disable C18/C19 backend routes until UI policy is ready.
10. Define one authoritative permission contract across static RBAC, explicit permissions, and C18F.

Final readiness state:

```text
C20_READY = false
BLOCKING_SEVERITIES = P0, P1
PRIMARY_BLOCKERS = tenant isolation, schema drift, non-durable runtime state, control-plane ingress mismatch
```
