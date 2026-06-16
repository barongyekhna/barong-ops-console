# PRE20-H Frontend Menu Refactor Report

Date: 2026-06-16

Mode: static source audit only. No frontend code change, backend code change, build, deploy, or runtime test was executed.

Scope covered:

- `frontend/src/app/`
- `frontend/src/components/`
- `frontend/src/lib/`
- `frontend/src/app/api/`
- Missing requested directories were checked by path scan: `frontend/src/navigation/`, `frontend/src/layout/`, `frontend/src/pages/`, and `frontend/src/api/backend/` are not present in this repository. Active navigation is `frontend/src/lib/navigation.ts`; active console layout is `frontend/src/app/(console)/layout.tsx`; active backend proxy is `frontend/src/app/api/backend/[...path]/route.ts`.

### 1. Sidebar Menu Inventory

| Menu Item | Type | Backend Link | Status |
|---|---|---|---|
| Dashboard (`/dashboard`) | PARTIAL UI | No page-level API call; only global module/adapter access providers run around it. | Static empty state while menu status is `sealed`; should be wired to C17 operational/audit data or hidden from production navigation. |
| Foundation Demo (`/foundation-demo`) | FAKED FUNCTION UI | `POST /api/control-plane/foundation-demo/run`, `GET /api/control-plane/foundation-demo/latest` via proxy special case. | Delete from production sidebar or hide behind an internal dev/demo flag. It is first-class menu UI for a demo-only data loop. |
| n8n Test Bridge (`/n8n-test`) | FAKED FUNCTION UI | `POST /api/control-plane/n8n-test/run`, `GET /api/control-plane/n8n-test/latest`; `callback` backend route is not proxied. | Delete from production sidebar. Backend and frontend explicitly label it mock/test-only and not a real n8n integration. |
| Products (`/products`) | PARTIAL UI | No product backend route, proxy allowlist path, or page API call found. | Hide until a real products module/API exists. Current page is static empty state with `status: planned`. |
| Modules (`/modules`) | REAL DATA UI with demo wording | `GET /api/control-plane/modules`; module access also uses `/modules/me` and `/modules/registry`. | Keep as registry read UI, but remove "foundation/demo" wording and avoid implying dynamic module installation. |
| Agents (`/agents`) | REAL DATA UI with demo wording | `GET /api/control-plane/agents`. | Keep as registry read UI, but remove "foundation/demo" wording. |
| Workflows (`/workflows`) | PARTIAL UI | `GET /api/control-plane/workflows`; backend create path is metadata-only. | Keep only as workflow metadata registry; do not present as live workflow execution. |
| Jobs (`/jobs`) | PARTIAL UI | `GET /api/app/jobs`; backend create path records `execution=not_triggered`. | Keep as read-only job records; do not present as executable job runner. |
| Artifacts (`/artifacts`) | PARTIAL UI | `GET /api/app/artifacts`; backend create path records `storage=metadata_only`. | Keep as metadata list; do not imply file/object storage. |
| Reviews (`/reviews`) | PARTIAL UI | `GET /api/app/reviews`; backend decision path records demo decision/downstream false and is not proxied by frontend. | Keep as read-only governance records until review action UI is backed by production behavior. |
| Errors (`/errors`) | REAL DATA UI with foundation-demo source risk | `GET /api/app/errors`. | Keep as system error record list, but remove foundation/demo empty-state wording and avoid conflating with C17 operation logs. |
| Memory Events (`/memory-events`) | PARTIAL UI / placeholder risk | `GET /api/app/memory-events`; backend writes include `model_called=False`. | Rename or hide unless presented as audit memory records only. It currently looks like a real memory system but backend has no model memory execution. |
| User Management (`/users`) | REAL PRODUCTION UI | `GET/POST /api/app/users`, `/users/roles`, `/users/{id}`, `/disable`, `/enable`, `/reset-password`. | Keep. DB-backed owner-controlled C03/C04 user management. |
| Settings (`/settings`) | PARTIAL UI | No settings backend route, proxy allowlist path, or page API call found. | Hide or merge into admin/user pages until a real settings API exists. Current page is static empty state with `status: planned`. |
| Permission Management (embedded under `/users`) | REAL PRODUCTION UI | `GET /api/app/permissions/registry`; `GET/POST/PATCH/DELETE /api/app/permissions/users/{id}/assignments`. | Keep. It is route-embedded, not a sidebar item, but is DB-backed and permission-controlled. |

### 2. Fake / Demo UI List

- `Foundation Demo`: `frontend/src/app/(console)/foundation-demo/page.tsx`, `frontend/src/components/foundation-demo-panel.tsx`, and `frontend/src/lib/foundation-demo-api.ts` expose a "Demo only" run button and call `foundation-demo/run/latest`. The backend route is mounted, but the feature is explicitly a demo data loop.
- `n8n Test Bridge`: `frontend/src/app/(console)/n8n-test/page.tsx`, `frontend/src/components/n8n-test-panel.tsx`, and `frontend/src/lib/n8n-test-api.ts` expose a "Test only" mock bridge. The client type fixes `test_mode: true` and `completed_demo`; the panel text says it does not call n8n or send webhook traffic.
- F-series legacy labels remain visible: `/foundation-demo` uses section index `F11`, `/n8n-test` uses `F12`, and the login identity shows `F09 / Console shell`. These should not be user-facing production capability labels.
- Module registry demo wording appears in `Modules`, `Agents`, and `Jobs` empty states (`Foundation and demo ... will appear here`). Backend create handlers also use audit actions like `module.create_demo`, `agent.create_demo`, `workflow.create_demo`, and `job.create_demo`, although the current frontend only lists records.
- Memory placeholder/demo wording appears in `Memory Events` (`Foundation and demo memory events will appear here`) and in demo panels that render "Memory event summary". Backend memory creation records `model_called=False`, so this must not be marketed as real AI memory.
- `AdapterSurfaceShell` is rendered under console pages and shows action contracts, surfaces, capabilities, and provider status, but its own copy says execution is not connected. The execution-provider status shell has a disabled action button. This is a production-shaped shell, not executable UI.
- `/products` and `/settings` are static empty-state pages with planned navigation status and no backend binding. They are not demo-labeled, but they are fake product/admin capability entry points if visible to users.

### 3. Partial UI (Broken Binding)

- Dashboard: route exists and is marked `sealed`, but it renders only an `EmptyState`; no C17 audit/operation metrics, operation-log API, or dashboard API binding is present.
- Products: route exists and sidebar item requires `products.read`, but there is no backend products router, no proxy allowlist entry, and no page API call.
- Settings: route exists and sidebar item requires `settings.read`, but there is no settings router, no proxy allowlist entry, and no page API call.
- Workflows: DB-backed metadata list exists, but the backend create route records metadata-only execution and the frontend has no live workflow status/action binding.
- Jobs: list API is real, but backend job creation records `execution=not_triggered`; the frontend has no job detail, event timeline, retry, cancel, or real execution action binding.
- Artifacts: list API is real, but backend artifact creation is metadata-only; there is no file/object storage UI.
- Reviews: list API is real, but review approval/rejection UI is missing and the frontend proxy does not expose review decision routes.
- Memory Events: list API is real, but the semantics are partial because memory/context creation records no model call and the frontend copy implies demo memory.
- Errors: list API is real, but direct operation-log/audit linkage is missing; backend error creation source is still foundation-demo flavored.
- Adapter/action contract surfaces: registry/status APIs are real read-only APIs, but the UI intentionally has no execution handler and shows disabled provider/action states.
- API proxy mismatch: the frontend proxy allowlist exposes some backend families with no UI, blocks some mounted backend routes, and special-cases demo/test endpoints.

### 4. Real Production UI

- Auth/login/session UI: `LoginForm`, `AuthProvider`, `AuthGuard`, and `/api/public/auth/login`, `/auth/me`, `/auth/logout` are real backend-backed flows.
- Protected console shell: all console pages run under auth, module access, adapter access, and permission route guards.
- User Management: owner-only `/users` UI is backed by real DB services for listing, creation, role update, enable/disable, and password reset.
- Role catalog: `/users/roles` is backend-backed and used by user creation/update UI, though reserved role copy still mentions later RBAC phases.
- Permission registry and user permission assignments: the embedded permissions panel uses real permission registry and assignment APIs with DB persistence.
- Module access gating: navigation visibility is filtered by user permissions plus `/modules/me`; this is real access-control plumbing even though navigation itself is static.
- Module/agent/workflow record lists: these call real DB-backed list routes. They should be retained only as registry/metadata lists, not as claims of dynamic install or live execution.
- Jobs/artifacts/reviews/errors/memory-events record lists: these call real DB-backed list routes. They should be retained only as operational record views with corrected wording and capability boundaries.
- Module adapter and execution-provider registries: registry/status APIs are real read-only control-plane APIs. They are not real execution UI and must keep a clear no-execute state.

### 5. Missing Backend Binding Map

UI exists but API missing or not bound:

- `/dashboard`: no dashboard API call and no dedicated backend route. Candidate replacement: C17 audit dashboard/operation-log aggregation.
- `/products`: no products backend router, no proxy path, and no page data load.
- `/settings`: no settings backend router, no proxy path, and no page data load.
- `AdapterSurfaceShell` action button: disabled UI only; no action execution endpoint is called.
- Job/detail/event/retry UX: backend has job detail/events and create/event routes, but frontend only calls the list path.
- Artifact/detail/storage UX: backend has artifact detail/create metadata routes, but frontend only calls the list path and has no storage binding.
- Review decision UX: backend has review decision routes, but frontend only calls the list path and proxy does not allow the decision route.
- Memory/context UX: backend has memory-events, context-packets, and memory-summaries routes, but frontend only calls `/memory-events`.

API exists but UI missing:

- C12 approval: `/api/app/approval/list`, detail, approve, reject exist in backend, but no frontend page/proxy allowlist entry was found.
- C17 operation logs: `/api/app/operation-logs` list/detail exists in backend, but sidebar uses `/errors`; operation logs are not proxied as a direct UI surface.
- C18 org lifecycle/membership: `/api/app/org` and `/api/app/org/{id}/members...` exist in backend, but no frontend route, sidebar item, or proxy allowlist binding was found.
- C18 module binding/visibility/shared module: backend routes exist for module binding, org visible modules, module visibility, and shared modules; no frontend page/proxy binding was found.
- C19 contacts/conversations/friends/messages/attachments: backend routes exist, but no frontend pages exist. Some backend C19 routes are in-memory, fake envelope, or 501/schema-only and should not be surfaced until production-ready.
- n8n callback: backend `POST /api/control-plane/n8n-test/callback` exists, but frontend proxy intentionally does not expose it.
- Webhook/callback/failure control-plane routes: backend mounts webhook gateway, callback handler, and failure handling routes; frontend proxy blocks `webhook-gateway/ingress` and does not expose most callback/failure paths.
- Workflow registry: backend mounts `/api/control-plane/workflow-registry/...`, but frontend proxy and UI do not expose the registry family.
- C14/C14X/C15 read-model families: proxy allowlist exposes external-dependencies, AI execution bindings, model locks, capability bindings, module-workflow bindings, module allocations, execution prompts, payload standardization, and result normalization, but no dedicated frontend pages or menu entries were found.

Proxy allowlist mismatches:

- Demo/test endpoints are special-cased in the proxy: `foundation-demo/run`, `foundation-demo/latest`, `n8n-test/run`, and `n8n-test/latest`.
- Security isolation blocks first segments `webhook` and `n8n`, and blocks `webhook-gateway/ingress`.
- Backend has many mounted app routes not available through the proxy: approval, operation-logs, org/org membership, contacts, conversations, cross-org communication, friends, messages, attachments, module binding, module visibility, and shared module.
- Backend has mounted control-plane routes not available through current UI and not fully represented in proxy: workflow-registry, callback-handler, webhook gateway design/status paths, and failure-handling.
- Proxy exposes several control-plane read-model APIs without corresponding UI, which can create hidden API surface without operator workflows.

### 6. Navigation Refactor Plan

What to delete or hide:

- Remove `Foundation Demo` and `n8n Test Bridge` from production sidebar. If retained for engineering, gate them behind a non-production/internal flag and not normal permissions like `jobs.create`.
- Hide `/products` and `/settings` until backend routes, proxy entries, and real page data bindings exist.
- Remove visible F-series labels (`F09`, `F11`, `F12`) from production UI.
- Suppress `AdapterSurfaceShell` from production pages unless the page explicitly needs registry/status diagnostics; otherwise it makes non-executable contracts look like product UI.

What to rename:

- `Dashboard` -> `Audit Dashboard` or `Operations Overview` only after wiring C17/operation-log data.
- `Workflows` -> `Workflow Registry` or `Workflow Metadata` until live workflow execution exists.
- `Jobs` -> `Job Records` or `Execution Records` until actual execution submission/retry/cancel is available.
- `Artifacts` -> `Artifact Metadata` until real storage/download binding exists.
- `Memory Events` -> `Memory Audit Events` or merge into C17 audit views until model-backed memory exists.
- `Modules`, `Agents`, `Reviews`, and `Errors` empty states should remove "foundation" and "demo" wording.

What to merge:

- Keep Permission Management embedded under User Management, or create a separate Admin > Permissions route only when a first-class `/permissions` page exists.
- Merge Settings into User/Permission admin controls until a real settings API exists.
- Merge Errors, Memory Events, and Operation Logs into a C17 observability section instead of scattered foundation-era lists.

What to replace with real modules:

- C17: replace static Dashboard and fragmented Errors/Memory views with a real audit dashboard backed by operation logs, audit query, execution trace, replay status, and anomaly signals once those APIs are durable and proxied.
- C18: add real Organization, Org Membership, Module Visibility, and Shared Module pages only after durable DB persistence and proxy paths are in place.
- C19: add Contacts, Conversations, Messages, Friends, and Attachments pages only after in-memory/501/fake-envelope behavior is replaced with durable persistence and delivery/storage semantics.

Navigation and proxy rules:

- Generate production navigation from backend module registry/access state plus capability flags, not only from the static `navigationGroups` array.
- Treat `planned`, `adapter_pending`, `mock`, `demo`, `test`, `schema_only`, and `no_execute` as non-production sidebar statuses.
- Align proxy allowlist with production UI: remove demo/test special cases from normal user paths, and add only audited real backend routes needed by production pages.
- Add a "read-only metadata" capability label where a page is intentionally real but non-executable.

### 7. Critical UI Risks (P0)

- Fake functionality is visible to users: Foundation Demo and n8n Test Bridge are first-class sidebar entries and can create successful-looking records while not performing real business or n8n work.
- Static navigation misrepresents capability: Dashboard is marked `sealed`, Products/Settings are visible routes, and several pages render empty states without backend binding.
- Execution capability is misleading: adapter/provider shells expose action contracts and disabled buttons across pages, but providers/adapters remain no-execute/mock/contract-only.
- Memory capability is misleading: Memory Events can look like real AI memory, but backend memory/context writes explicitly do not call a model.
- Broken navigation paths exist by design: Products and Settings have UI routes without backend routes; many backend C17/C18/C19 routes have no UI/proxy path.
- Proxy policy is inconsistent with product truth: demo/test APIs are allowed, while real-looking mounted backend routes such as approval, operation logs, org, contacts, messages, attachments, and callback/failure workflows are missing or blocked.
- Orphan backend routes can become accidental product promises: C18/C19 routes include in-memory, fake-envelope, and 501/schema-only behavior; surfacing them without cleanup would create production-visible fake capabilities.
- Module expansion will keep drifting unless navigation and proxy are registry/capability-driven rather than static hardcoded lists.
