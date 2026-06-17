# PRE20-I UI Productization Design Audit

Date: 2026-06-17

Mode: static source audit and product UI architecture design only. No frontend
code, backend code, build, deployment, production command, or runtime execution
was performed. This document is the only PRE20-I output.

Scope covered:

- `frontend/src/app/`
- `frontend/src/components/`
- `frontend/src/lib/navigation.ts`
- `frontend/src/app/(console)/`
- `frontend/src/app/api/backend/[...path]/route.ts`
- Console layout/sidebar system via `frontend/src/app/(console)/layout.tsx`
  and `frontend/src/components/console-shell.tsx`
- Empty states, permission guards, dashboard, and all current module pages

Existing structure note: `frontend/src/layout/` is not present. The active
layout is `frontend/src/app/(console)/layout.tsx`; the active sidebar shell is
`frontend/src/components/console-shell.tsx`.

## 1. UI Architecture Redesign Map

### 1.1 Current UI Architecture

The current console is a protected Next.js shell:

```text
AuthGuard
  -> ModuleAccessProvider
  -> AdapterAccessProvider
  -> ConsoleShell
       -> static navigationGroups from frontend/src/lib/navigation.ts
       -> PermissionRouteGuard
       -> page component
       -> global AdapterSurfaceShell
```

This already contains useful control-plane primitives:

- `AuthGuard` protects console routes.
- `ModuleAccessProvider` reads `/modules/me`.
- `PermissionRouteGuard` blocks direct entry based on module access decisions.
- `AdapterAccessProvider` reads module adapter and execution provider status.
- Backend proxy uses an explicit allowlist and blocks direct `n8n`/`webhook`
  style paths.

The productization gap is that navigation and page promises still come from
static frontend entries, not from the complete capability system. Evidence:

- `navigationGroups` is a hardcoded array in `frontend/src/lib/navigation.ts`.
- `ConsoleShell` maps those static groups and only filters them afterward.
- `Dashboard`, `Products`, and `Settings` are static empty-state pages.
- `Foundation Demo` and `n8n Test Bridge` remain first-class sidebar entries.
- `EmptyState` only accepts `title`, `description`, and `icon`, so it cannot
  explain capability reason, unlock condition, role, org state, or module state.

### 1.2 Target UI Architecture

PRE20-I target architecture:

```text
Authenticated user/session
  -> active org context
  -> C18 module visibility / shared modules
  -> C18 permission isolation and current permission snapshot
  -> module registry + user module access
  -> C19 communication capability registry, future-ready only
  -> PRE20-D execution provider mode and readiness
  -> Dynamic Module Registry UI
  -> capability-aware pages and states
```

The frontend should render only capability records that survive all of these
gates:

1. The module exists in the registry.
2. The current org can see the module.
3. The current user has a defined permission state.
4. The backend API binding is real and allowed through the proxy.
5. Adapter/execution provider status does not imply a fake live action.
6. The UI state is one of `allowed`, `forbidden`, `hidden`, or `partial`.

### 1.3 Product UI Layers

| Layer | Responsibility | Current status | Product target |
| --- | --- | --- | --- |
| Auth shell | Login, session, protected layout | Real backend-bound | Keep, remove foundation-stage copy from production UI |
| Capability registry | Module, permission, adapter, provider, org visibility | Split across providers and static nav | Single normalized capability view model |
| Sidebar | Primary navigation | Static source, filtered after the fact | Generated from capability registry |
| Page routing | Direct route access | PermissionRouteGuard supports locked/unavailable | Route decision must expose reason/unlock metadata |
| Empty states | No data / unavailable UI | Generic title/description only | Capability-aware state with reason and unlock condition |
| Dashboard | Operational overview | Static empty state | System Operations Control Center |
| Backend proxy | Frontend API boundary | Explicit allowlist with demo/test exceptions | Real-first allowlist aligned to product pages |

### 1.4 Canonical Capability View Model

Every renderable page or sidebar entry should be derived into:

```text
ProductCapabilityItem
  module_key
  display_name
  category: core | operational | business | admin | system | communication
  route_namespace
  nav_group
  nav_order
  icon_token
  module_status
  org_visibility_state
  permission_state: allowed | forbidden | hidden | partial
  required_permissions
  missing_permissions
  required_role
  required_org_state
  required_module_state
  adapter_state
  execution_provider_mode: mock | staging | live | unavailable | none
  execution_readiness
  api_binding_state: bound | missing | proxy_missing | schema_only | mock_only
  ui_state
  reason
  unlock_condition
```

The UI must not infer product capability from the existence of a React route
alone.

## 2. Sidebar Dynamic Design Spec

### 2.1 Current Sidebar Findings

Current sidebar data source:

- `frontend/src/lib/navigation.ts` lines 44-224 define hardcoded groups/items.
- `ConsoleShell` lines 32-47 maps these static groups through
  `getNavigationStateForModule()`.

This means the sidebar is permission-filtered but not capability-sourced. It
can still advertise entries that should not exist in product UI:

- `/foundation-demo`: static enabled experimental entry.
- `/n8n-test`: static adapter-pending integration entry.
- `/products`: planned route without backend product API binding.
- `/settings`: planned route without backend settings API binding.
- `/memory-events`: real DB list, but product semantics are misleading if shown
  as an AI memory module.

### 2.2 Target Sidebar: Dynamic Module Registry UI

The sidebar must be generated from the backend capability graph. Static frontend
navigation may remain only as a presentation fallback for core shell exceptions
and icon mapping, not as the source of truth.

Required sources:

- C18 module visibility: active org visible modules.
- C18 shared modules: modules shared into the current org context.
- C18 permission system: current effective permission and missing permission
  list.
- C19 communication capability: future-ready registry only; hidden until durable
  messaging/storage is available.
- PRE20-D execution provider capability: execution mode and readiness.
- Module registry/user module access: `/modules/registry` and `/modules/me`.
- Adapter/provider status: `/module-adapters/me` and
  `/execution-providers/me`.

Resolution algorithm:

```text
1. Resolve authenticated user and current permission snapshot.
2. Resolve active org context.
3. Fetch C18 visible modules and shared modules for active org.
4. Fetch module registry and current user's module access.
5. Fetch adapter and execution-provider access summaries.
6. Join records by module_key.
7. Drop entries whose UI state is hidden.
8. Mark forbidden entries as locked only when denied_behavior says show_locked.
9. Mark partial entries read-only/no-execute.
10. Sort by registry navigation.group and navigation.order.
```

Fail-closed rules:

- If module visibility cannot be read, org-scoped business modules are hidden.
- If permission state cannot be read, non-owner admin/system modules are hidden.
- If execution provider status cannot be read, execution actions are partial
  read-only and no-execute.
- If API binding is missing or mock-only, the sidebar item is hidden unless it
  is explicitly a diagnostic/admin read-only page.

### 2.3 Sidebar Groups

Product sidebar groups should be:

| Group | Entries | Render source |
| --- | --- | --- |
| Core System | Dashboard, Users, Permissions | Auth/session + real admin APIs |
| Operations | Logs, Audit, Traces, Approvals, Jobs, Artifacts | C17/C12 + DB-backed record APIs |
| Business Modules | Organizations, Module Registry, Shared Modules, Communication | C18/C19 capability graph |
| Execution | Provider Readiness, Adapter Contracts | PRE20-D/C08/C09 read-only status |
| Hidden | Demo/test/planned/no-permission modules | Not rendered |

### 2.4 Sidebar States

| State | Sidebar behavior | Route behavior |
| --- | --- | --- |
| `allowed` | Normal link | Full page UI |
| `forbidden` | Locked item only if policy is `show_locked`; otherwise hidden | Locked capability notice |
| `hidden` | Not rendered | Direct route returns not-found style or no-access state |
| `partial` | Visible with `Read-only`, `No execute`, or `Adapter pending` badge | Page renders data but disables mutations/actions |

### 2.5 Sidebar Entries To Remove From Product Navigation

Must not appear in enterprise product sidebar:

- `Foundation Demo`
- `n8n Test Bridge`
- `Products` until a real products API/module exists
- `Settings` until a real settings API/module exists
- Standalone `Memory Events` unless renamed and scoped as C17 audit memory
  records, not AI memory capability

## 3. Page System Redesign

### 3.1 Core System Pages

| Page | Current route | Current binding | Product target |
| --- | --- | --- | --- |
| Auth/Login | `/login` | Real `/auth/login`, `/auth/me`, `/auth/logout` | Keep; remove foundation-stage labels |
| Dashboard | `/dashboard` | No page-level API; empty state | Become System Operations Control Center |
| Users | `/users` | Real users API and DB | Keep as admin core page |
| Permissions | embedded in `/users` | Real permission registry/assignment API and DB | Keep embedded or promote to first-class Admin > Permissions tab |

### 3.2 Operational Pages

| Product page | Current frontend state | Backend/API state | Product decision |
| --- | --- | --- | --- |
| Logs | No direct page | `/operation-logs` exists but proxy does not allow it | Add as C17 operation logs page after proxy binding |
| Audit | No page | C17E/C17H design exists; UI not integrated | Add read-only audit dashboard when query API is exposed |
| Traces | No page | C17 trace/query design exists; UI not integrated | Add trace drill-down under audit |
| Approvals | No page | C12D `/approval/*` exists and is DB-backed; proxy missing | Add Operational > Approvals |
| Jobs | `/jobs` via `FoundationList` | DB-backed list, no execution | Keep as read-only execution/job records |
| Artifacts | `/artifacts` via `FoundationList` | DB-backed metadata list | Keep as artifact metadata until storage is real |
| Reviews | `/reviews` via `FoundationList` | DB-backed list; decision UI/proxy missing | Keep as read-only until decision workflow is bound |
| Errors | `/errors` via `FoundationList` | DB-backed system errors | Merge into Logs/Audit or keep as filtered C17 error view |
| Memory Events | `/memory-events` via `FoundationList` | DB-backed memory records, not model-backed AI memory | Rename/merge into audit records; do not show as memory product |

### 3.3 Business Modules

| Module family | Current frontend state | Backend capability | Product decision |
| --- | --- | --- | --- |
| C18 Org System | No frontend route/proxy | Org lifecycle and membership routes exist; visibility/shared binding routes exist, some binding/shared state is not durable | Add only capability-aware org pages; hide non-durable module binding controls until storage is production-ready |
| C18 Module Registry | `/modules`, `/agents`, `/workflows` list metadata | DB-backed registry list routes | Keep as Module Registry read UI; remove demo/foundation wording |
| C19 Communication | No frontend route/proxy | Contacts identity exists; conversations/friends are in-memory; messages can fake accepted send; attachments return schema-only 501 | Design-only, hidden from sidebar until persistence, delivery, and storage exist |
| Products | `/products` static empty state | No product backend/proxy binding found | Hide until installed as real module |
| Settings | `/settings` static empty state | No settings backend/proxy binding found | Hide or merge into admin pages until real settings API exists |

### 3.4 Disabled / Hidden Pages

Pages/modules must be hidden when any of the following is true:

- Module is not installed or not in registry.
- Current org cannot see module through C18 visibility.
- Current user permission state resolves to `hidden`.
- API binding is missing.
- Backend route exists but is mock-only, schema-only, in-memory-only, or 501 for
  the promised product action.
- Module requires execution but PRE20-D provider mode is unavailable/no-execute.

Direct routes for hidden modules should render a capability-aware blocked state
for authenticated users, but should not appear in sidebar or Dashboard cards.

## 4. Empty State Design System

### 4.1 Current Empty State Problem

`EmptyState` only renders:

- `title`
- `description`
- optional icon

It cannot tell the user:

- why the state exists
- whether data is empty or capability is disabled
- what unlocks the page
- what role/permission/org/module state is required
- whether the page is read-only, planned, no-execute, or backend unavailable

Current product risks:

- Dashboard says no operational activity, but has no API binding.
- Products and Settings look like future product areas but have no API.
- `FoundationList` loading text says "Loading foundation records".
- Several empty descriptions mention foundation/demo records.

### 4.2 Target Capability-Aware Empty State

Canonical fields:

```text
CapabilityEmptyState
  state
  title
  reason
  unlock_condition
  required_role
  required_permissions
  required_org_state
  required_module_state
  backend_binding
  data_source
  allowed_next_action
```

State taxonomy:

| State | Meaning | UI behavior |
| --- | --- | --- |
| `empty_allowed` | Capability exists and API returned zero records | Show normal empty state with data source |
| `forbidden` | User lacks permission | Show required permission/role and no action buttons |
| `hidden` | Module should not be discoverable | Not rendered in navigation; direct route blocked |
| `partial_read_only` | Data can be read but actions are disabled | Show data and disabled actions with reason |
| `module_not_installed` | Module absent from registry/org visibility | Explain installation/binding requirement |
| `org_required` | Active org context missing or invalid | Prompt org selection/switch when available |
| `module_disabled` | Module disabled/unavailable/planned | Show module lifecycle state and owner unlock condition |
| `adapter_pending` | Adapter exists but not ready | Show adapter status and no-execute reason |
| `execution_not_connected` | PRE20-D mode is mock/no-execute/unavailable | Show no live execution available |
| `backend_unavailable` | Real API exists but request failed | Show retry and service dependency |
| `mock_hidden` | Feature is demo/mock/test-only | Hidden in production UI |

### 4.3 Empty State Copy Rules

Allowed copy:

- "No operation logs match the current filters."
- "Approvals are empty. Source: `/approval/list`."
- "Module is visible but actions are read-only because execution provider mode
  is `mock`."
- "Requires `operation_logs.read` and active org membership."

Disallowed copy:

- "Foundation/demo records will appear here."
- "No products created yet" when no product API exists.
- "No settings available yet" when no settings API exists.
- "Memory events" as a product memory capability without model-backed memory.

## 5. Permission State UI System

### 5.1 Unified Permission State Model

| State | Behavior | Source |
| --- | --- | --- |
| `allowed` | Render full UI and allowed actions | C18F + current permission snapshot + module access |
| `forbidden` | Render locked UI with reason and required permission | Missing permission, denied role, or owner-only boundary |
| `hidden` | Do not render nav/module card/page entry | C18E visibility denied, `hide_when_denied`, module absent |
| `partial` | Render read-only data, disable write/execute controls | Adapter/provider pending, no-execute, approval required, execution mode unavailable |

### 5.2 Route-Level Rules

Current route guard already computes a route decision from module records, but
the notices are generic. Product target:

- Route guard must pass through `reason`, `missing_permissions`,
  `required_role`, `required_org_state`, and `required_module_state`.
- `ModuleUnavailableNotice` must distinguish planned, adapter pending,
  execution not connected, module disabled, and backend unavailable.
- Forbidden routes must not show generic "contact Owner" only; they must show
  the concrete unlock condition.

### 5.3 Action-Level Rules

For actions inside allowed pages:

- Allowed action: render enabled button/control.
- Forbidden action: do not render the action unless a locked action is useful
  for admin/operator discovery.
- Partial action: render disabled button with reason, e.g. "Approval required",
  "Provider mode is mock", "Adapter pending", "Missing `jobs.create`".
- Dangerous/high-risk action: require backend-backed confirmation policy, not
  frontend-only copy.

### 5.4 Data-Level Rules

Read-only pages may show data when the read API is real and allowed:

- `/jobs`: records only, no run/retry/cancel until execution is real.
- `/artifacts`: metadata only, no download/storage action until object storage
  binding is real.
- `/reviews`: list only, no approve/reject until C12/C12D UI and proxy are
  bound.
- `/modules`, `/agents`, `/workflows`: registry metadata only, no install/run
  implication.

## 6. Fake UI Removal Plan

### 6.1 Foundation Demo Removal

Current evidence:

- Sidebar entry exists as `experimental.foundation_demo`.
- Page exists at `/foundation-demo`.
- `FoundationDemoPanel` labels itself "Demo only" and exposes a run button.
- Backend proxy explicitly allows `foundation-demo/run` and
  `foundation-demo/latest`.

Product plan:

1. Remove from production sidebar.
2. Hide route from capability registry.
3. Remove demo run entry points from production proxy policy.
4. Keep any engineering-only page behind a non-production/internal flag, not
   normal permissions like `jobs.create`.
5. Remove "Foundation Demo" as a product-facing page title or status source.

### 6.2 n8n Test Removal

Current evidence:

- Sidebar entry exists as `integration.n8n_test_bridge`.
- Page exists at `/n8n-test`.
- `N8nTestPanel` labels itself "Test only" and "Mock bridge only".
- Backend proxy explicitly allows `n8n-test/run` and `n8n-test/latest`.

Product plan:

1. Remove from production sidebar.
2. Do not represent this as a C19/C15/n8n integration.
3. Hide mock run UI and mock status from operator pages.
4. Keep real n8n/live execution out of UI until PRE20-D live provider gates are
   satisfied.
5. If retained, expose only as an internal diagnostics tool with environment
   labeling and no product navigation entry.

### 6.3 Memory Fake UI Removal

Current evidence:

- Standalone `/memory-events` page exists.
- Empty copy says foundation/demo memory events will appear.
- Demo/test panels render "Memory event summary".
- Existing memory records are DB-backed records, but not proof of model-backed
  memory execution.

Product plan:

1. Remove standalone "Memory Events" product module.
2. Reclassify as "Memory Audit Events" only under C17 audit/log views.
3. Do not show memory as AI capability unless backend proves model execution,
   persistence, scope, and audit semantics.
4. Remove demo memory summaries from product dashboards.

### 6.4 Placeholder Product Page Removal

Hide until real backend binding exists:

- `/products`
- `/settings`

Keep as hidden route stubs only if required for engineering continuity. They
must not appear in product navigation or Dashboard cards.

### 6.5 Demo-Only Navigation Cleanup

Remove or hide:

- `Foundation Demo`
- `n8n Test Bridge`
- F-series labels such as `F09`, `F11`, `F12` from production UI
- Empty-state text containing "foundation" or "demo"
- Mock/test route proxy allowlist entries from production-facing proxy rules

## 7. Dashboard Redesign Spec

### 7.1 Target: System Operations Control Center

Dashboard must become an operational control surface, not an empty-state page.
It should answer:

- Is the console healthy?
- What happened recently?
- Which modules are visible/installed/enabled for this org?
- What execution mode is active?
- Are adapters/providers ready or blocked?
- What approvals are pending?
- What permissions does the current actor have?
- Which communication/org capabilities are disabled and why?

### 7.2 Dashboard Sections

| Section | Data source | Required behavior |
| --- | --- | --- |
| System health | `/health`, auth/session status, proxy health | Show backend reachability and current session |
| C17 logs overview | `/operation-logs` and future C17E query API | Recent operations, failures, top modules, latency/anomaly summary |
| Audit/traces | C17E/C17H query/drill-down | Context/trace search and latest trace groups |
| C18 org status | org lifecycle, membership, visible modules | Active org, org state, module visibility count |
| C19 communication status | future C19 capability registry | Hidden or disabled until persistence/delivery/storage are real |
| Execution readiness | `/execution-providers/me`, `/module-adapters/me`, PRE20-D mode | Mock/staging/live mode, no-execute counts, blocked reasons |
| Permission snapshot | current user permissions and `/permissions/me` | Role, owner full access, missing capability highlights |
| Approvals | `/approval/list` | Pending/approved/rejected counts; no execution implication |
| Module registry | `/modules/registry`, `/modules/me` | Installed/enabled/planned/unavailable counts |

### 7.3 Dashboard Layout

Recommended first viewport:

```text
Header: active org, environment/provider mode, current role
Metric row: health, logs, approvals, module readiness, provider readiness
Main left: C17 latest operations and error/anomaly stream
Main right: execution readiness and permission snapshot
Lower tabs: Logs | Traces | Approvals | Modules | Org | Communication
```

Design constraints:

- Dense operational UI, not marketing layout.
- No hero section.
- No demo cards.
- No fake "all good" state when APIs are unavailable.
- Every tile must show source and freshness.
- Disabled tiles must show reason and unlock condition.

### 7.4 Dashboard Product Copy

Allowed:

- "Execution provider mode: mock. Live execution unavailable."
- "Approvals API not exposed through frontend proxy."
- "C19 communication not installed: persistence and delivery not available."
- "Operation logs source unavailable. Retry."

Disallowed:

- "Foundation APIs have not recorded any operational activity."
- "Run demo."
- "Create mock result."
- Any copy implying n8n/live execution while PRE20-D says no live provider.

## 8. Backend-Frontend Binding Audit

### 8.1 Matched: Page -> API -> DB/Real Source

| Frontend page/surface | API through frontend | Backend/source | Product status |
| --- | --- | --- | --- |
| `/login` | `/auth/login`, `/auth/me`, `/auth/logout` | Auth/user/session backend | Real core UI |
| `/users` | `/users`, `/users/roles`, `/users/{id}`, user actions | `users` table/service | Real admin UI |
| Permissions embedded in `/users` | `/permissions/registry`, `/permissions/users/{id}/assignments` | permission registry/assignments tables | Real admin UI |
| `/modules` | `/modules` | module registry DB list | Real metadata UI; copy must change |
| `/agents` | `/agents` | agent registry DB list | Real metadata UI; copy must change |
| `/workflows` | `/workflows` | workflow registry DB list | Real metadata UI; no live workflow claim |
| `/jobs` | `/jobs` | automation jobs DB list | Real record UI; no execution claim |
| `/artifacts` | `/artifacts` | artifacts DB list | Real metadata UI; no storage/download claim |
| `/reviews` | `/reviews` | review items DB list | Read-only governance records |
| `/errors` | `/errors` | system errors DB list | Real system error records |
| `/memory-events` | `/memory-events` | memory events DB list | Real records, but misleading as product memory |
| Global adapter shell | `/module-adapters/registry`, `/module-adapters/me` | adapter contract registry/access | Real read-only contract metadata |
| Execution provider status | `/execution-providers/registry`, `/execution-providers/me` | provider contract/access | Real read-only no-execute status |

### 8.2 Missing: UI Needed But API/Proxy/Page Missing

| Capability | Backend state | Frontend state | Gap |
| --- | --- | --- | --- |
| Dashboard operations center | No dedicated dashboard API; C17/C12/C18 sources exist separately | Empty state only | Needs composed real data model |
| Operation logs | `/operation-logs` backend exists | No page; proxy missing | Add Logs page and proxy binding |
| C17 audit/traces | C17E/C17H design/services exist | No page/proxy | Add audit and trace UI only after API exposure |
| Approvals | `/approval/*` DB-backed backend exists | No page; proxy missing | Add approvals console and proxy allowlist |
| C18 org lifecycle | `/org/*` backend exists | No page; proxy missing | Add org admin pages after capability gating |
| C18 module visibility | `/org/{org_id}/visible-modules` exists | No frontend binding/proxy | Required source for dynamic sidebar |
| C18 module/shared binding | backend routes exist, some state non-durable | No frontend binding/proxy | Hide controls until durable enough for product |
| C19 communication | routes exist but include in-memory/schema-only/fake send behavior | No UI/proxy | Keep hidden/design-only |
| Review decisions | backend decision behavior exists | No UI/proxy for approve/reject | Keep reviews read-only until bound |
| Job detail/events | backend has richer routes | List-only frontend/proxy | Add detail only if product semantics are real |
| Artifact detail/storage | metadata backend exists; storage not product-bound | List-only frontend | Keep metadata-only |

### 8.3 Orphan UI

| UI | Reason |
| --- | --- |
| `/foundation-demo` | Demo-only run UI, product navigation should not expose it |
| `/n8n-test` | Mock-only test bridge, not a live n8n capability |
| `/products` | Static empty state; no backend/proxy product API |
| `/settings` | Static empty state; no backend/proxy settings API |
| `/dashboard` current version | No page-level data binding |
| Global `AdapterSurfaceShell` on every page | Can make no-execute contracts look like product actions |
| Standalone `/memory-events` | Real records but product semantics imply memory capability |

### 8.4 Fake API Calls / Proxy Exceptions

The frontend proxy currently special-cases:

- `POST foundation-demo/run`
- `GET foundation-demo/latest`
- `POST n8n-test/run`
- `GET n8n-test/latest`

These should not be part of production product navigation. The proxy correctly
blocks direct `n8n`, `webhook`, and `webhook-gateway/ingress` paths, but the
demo/test exceptions still allow product-looking mock actions.

### 8.5 Backend Exists But Product UI Must Not Surface Yet

C19 communication is the clearest case:

- conversations/friends are in-memory
- messages can return accepted-looking envelopes without durable message
  persistence/delivery
- message history/read-state and attachments are schema-only/501

Therefore C19 should appear only as future-ready capability design, not as a
sidebar item or Dashboard "available" module.

C18 shared/module binding has a similar caution:

- org lifecycle and membership are DB-backed enough for admin UI design
- module binding/shared module state is documented and implemented with
  process-memory registry behavior in the current stage
- production UI must distinguish durable org lifecycle from non-durable module
  binding controls

## 9. Final Product UX Architecture

### 9.1 Target Information Architecture

```text
Barong Ops Console
  Core System
    - Operations Dashboard
    - Users
    - Permissions

  Operations
    - Logs
    - Audit
    - Traces
    - Approvals
    - Job Records
    - Artifact Metadata
    - Reviews
    - Errors

  Business Modules
    - Organizations
    - Org Membership
    - Module Visibility
    - Shared Modules
    - Module Registry
    - Communication (hidden until durable)

  Execution Readiness
    - Adapter Contracts
    - Execution Provider Status
    - Provider Mode / PRE20-D Readiness

  Hidden / Internal
    - Foundation Demo
    - n8n Test Bridge
    - Products placeholder
    - Settings placeholder
    - Mock/schema-only C19 pages
```

### 9.2 Product UX Invariants

1. Navigation is capability-driven, not route-driven.
2. A visible page must have a real backend binding or a clearly marked
   read-only capability explanation.
3. Demo/mock/test pages are not product navigation.
4. Planned modules are hidden unless the user needs admin diagnostics.
5. No page implies live execution unless PRE20-D live mode is explicitly ready.
6. Empty states must explain reason and unlock condition.
7. Permission UI must use the same `allowed`, `forbidden`, `hidden`, `partial`
   model everywhere.
8. C19 communication remains hidden until persistence, delivery, attachments,
   and permissions are production-bound.
9. C18 module visibility is the required sidebar source for org-scoped modules.
10. Proxy allowlist and sidebar entries must be reviewed together.

### 9.3 Productization Priority

P0:

- Remove/hide `foundation-demo` and `n8n-test` from product navigation.
- Hide `products` and `settings`.
- Replace generic empty states with capability-aware state model.
- Reclassify `memory-events` under audit/logs.
- Stop labeling UI with foundation/demo stage copy.

P1:

- Build dynamic sidebar from module visibility/access/capability registry.
- Add operation logs and approvals pages because backend support exists.
- Redesign Dashboard as System Operations Control Center.
- Align proxy allowlist with real product pages.

P2:

- Add C18 org pages with explicit durable/non-durable boundaries.
- Add C17 audit/traces once query APIs are exposed through frontend.
- Add C19 communication only after durable conversation/message/friend/attachment
  backend capability exists.
- Add products/settings only when real module/API contracts are installed.

### 9.4 PRE20-I Final Decision

The current UI is partially protected and partially real, but it still presents
developer-console and demo-era concepts as product navigation. The enterprise
product console must be rebuilt around a capability registry:

```text
C18 visibility + C18 permission + C19 capability + PRE20-D provider mode
  -> ProductCapabilityItem
  -> dynamic sidebar
  -> capability-aware pages
  -> capability-aware empty/permission states
```

Until that model is in place, the product-safe posture is:

- keep auth/users/permissions and DB-backed read-only record pages
- hide demo/test/placeholder entries
- make Dashboard operational and source-bound
- treat all execution surfaces as read-only/no-execute unless PRE20-D live or
  staging mode explicitly unlocks them
