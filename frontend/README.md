# Frontend

The frontend is a Next.js, React, and TypeScript console shell. F09 provides
the public `/login` page, authenticated navigation, the Dashboard, and
structured empty states for the remaining foundation routes.

C01 production deployment is complete for
`https://ops.barongyekhna.com`. The production frontend service is
`console_frontend`, bound only to `127.0.0.1:3000` behind Nginx HTTPS reverse
proxy. HTTP redirects to HTTPS. It uses
`BACKEND_API_URL=http://console_backend:8000` for the server-side restricted
proxy. The deployment does not expose a generic backend proxy and does not
connect real business systems. C01 remains foundation/console only; C02 is
production/test environment separation.

C02C has started the staging/test frontend on `127.0.0.1:3100`. The staging
frontend service is `console_staging_frontend` and uses
`BACKEND_API_URL=http://console_staging_backend:8000` for the server-side
restricted proxy. The real `.env.staging` is not committed and must not reuse
production owner passwords or token secrets. C02D added read-only
dual-environment checks, C02E completed final production/staging acceptance,
and C02F sealed the environment isolation system. Both environments are usable
and isolated. Staging is still not exposed publicly, no real business
integration is connected, and the next stage is C03: Owner creates
sub-accounts.

F13 accepts the required routes `/`, `/login`, `/dashboard`,
`/foundation-demo`, `/n8n-test`, `/products`, `/modules`, `/agents`,
`/workflows`, `/jobs`, `/artifacts`, `/reviews`, `/errors`,
`/memory-events`, `/users`, and `/settings`. The console route group uses the
protected layout and authentication guard. There is no `/register` page.

Authentication uses the F08 backend endpoints through a restricted same-origin
Next.js proxy:

- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/logout`

F10 extends the restricted same-origin proxy with GET-only access for:

- `/modules`
- `/agents`
- `/workflows`
- `/jobs`
- `/artifacts`
- `/reviews`
- `/errors`
- `/memory-events`

Those pages show loading, backend error, empty, and simple list states. The
proxy does not expose F10 write APIs to the UI. Products remains an empty
state and does not create product records. There is no public account creation
flow or real external integration.

F11 adds the protected `/foundation-demo` page. Its **Run Foundation Demo**
button calls only `POST /foundation-demo/run`, while initial/retry loading
calls only `GET /foundation-demo/latest`. The page displays the demo job ID and
status, event count, artifact title, review status, memory event summary, and
operation-log count.

The panel explicitly identifies the flow as an internal demo. It does not
trigger real n8n, WooCommerce, MinIO/Filebrowser, P-series tasks, external
HTTP calls, uploads, or real business work. The proxy allowlist exposes only
the two exact Foundation Demo paths and does not become a generic write proxy.

F12 adds the protected `/n8n-test` page. The **Run n8n Test** button calls only
`POST /n8n-test/run`; the page loads and polls `GET /n8n-test/latest` while a
Job is pending, running, or waiting for callback. It displays only the test
Job ID/status, latest event, demo Artifact/Review/Memory summary, operation-log
count, and safe error message.

The page states: “Test bridge only. Does not run real n8n production
workflows.” The restricted proxy exposes only the exact run and latest paths.
It does not proxy `/n8n-test/callback`, display callback credentials, or
provide a generic webhook route. F12 does not add registration, product
creation, WooCommerce, P-series, MinIO, or Filebrowser UI integration.

C03C adds the protected `/users` page under **User Management** in the System
navigation. C03E has released it to production at
`https://ops.barongyekhna.com/users`. It calls only the owner-only C03B
`/users` APIs through the restricted same-origin proxy. The page lists users,
creates `viewer`, `operator`, and `reviewer` accounts, shows user detail,
updates managed roles, enables/disables users, and resets sub-account
passwords with confirmation.
It does not show `owner` or `super_admin` as create options, does not add
public registration, does not print passwords or tokens, and does not connect
real business systems. C03D accepted this flow on staging with a
`c03d_test_<timestamp>` account, including list/detail, login, 403 for
non-owner `/users`, disable, enable, password reset, `role=owner` rejection,
`/auth/register` 404, and operation log verification. C03E production
read-only checks confirmed `/users` returns 200, unauthenticated
`/api/backend/users` returns 401, `/auth/register` still returns 404, and
production/staging/dual-env checks pass. C03 still does not add
`super_admin`, full RBAC, or real business integration. C03F has sealed this
stage; the next stage is C04: role system.

C04A has started the role-system stage with
`docs/C04_ROLE_SYSTEM_PLAN.md`. C04 is about account identity labels, not the
full permission system. C04B added the owner-only `GET /users/roles` catalog,
and C04C updates the `/users` page to read it through
`/api/backend/users/roles`. C04D accepted the role catalog UI on staging; the
acceptance record is `docs/C04_STAGING_ACCEPTANCE.md`. C04E has released the
role catalog UI to production; the release archive is
`docs/C04_PRODUCTION_RELEASE.md`. C04F has sealed the role system in
`docs/C04_ROLE_SYSTEM_SEAL.md`.

The User Management create-user selector and managed-role selector are now
generated from catalog roles that are `assignable=true` and pass the frontend
safety whitelist. They currently show only `viewer`, `operator`, and
`reviewer`. The production page at `https://ops.barongyekhna.com/users` now
uses this role catalog UI. The page also displays `owner`, `super_admin`,
`module_admin`, and `bot_agent` as reserved/not assignable in C04.
`super_admin` is not enabled, `module_admin` still needs module scope, and
`bot_agent` still needs agent identity and token scope design.

C04 does not make `super_admin` all-powerful, does not connect `bot_agent` to
real automation, and does not define module permissions. C05 will define
permissions, module access, and role-to-permission bindings. Future company
positions such as designer, SEO editor, customer service, or factory
supervisor should be represented through role plus later job title,
department, module access, and permissions, not as hard-coded frontend role
strings. C04D verified on staging that `/login`, `/users`, and
`/api/backend/health` return normally, the running frontend build contains
`/users/roles` and reserved role UI text, the create-user selector is limited
to `viewer`, `operator`, and `reviewer`, and reserved roles remain displayed
but not selectable. C04D did not rebuild/recreate/restart containers, run
`docker-compose up/down`, read real env files, modify Nginx/certificates, or
connect real business systems. C04E verified production `/users` returns 200,
unauthenticated `/api/backend/users/roles` returns 401, production backend
health is normal, staging remains normal, and production/staging/dual-env
checks pass. C04E did not read real env files, create production users,
restart/rebuild/remove containers, modify Nginx/certificates, or connect real
business systems. C04F confirmed production `/users` returns 200,
unauthenticated `/api/backend/users/roles` and `/api/backend/users` return
401, `/api/backend/auth/register` still returns 404, and
production/staging/dual-env checks pass. C04F did not read real env files,
create production users, restart/rebuild/remove containers, modify
Nginx/certificates, commit, or connect real business systems. C04 is sealed;
OPS01 Docker Compose v1 `ContainerConfig` issue cleanup is also sealed, and
C05A has started permissions / RBAC design.

C05A is documented in `docs/C05_PERMISSION_SYSTEM_PLAN.md`. C05B adds the
backend permission data model, C05C adds `/auth/me.permissions` and read-only
permission APIs, and C05D adds frontend permission awareness documented in
`docs/C05_PERMISSION_FRONTEND_ACCESS.md`.

C05D reads `permissions` from `GET /auth/me`, safely downgrades missing or
malformed permissions to no access, and uses `frontend/src/lib/permissions.ts`
for owner wildcard, exact permission, navigation, and route decisions.
Business navigation items remain visible with a locked state when denied and
show the no-permission notice after click. Admin/system navigation items are
hidden when denied. Direct access to a denied protected route shows
“无权访问此板块”.

User Management remains owner-only in C05D. The `/users` entry is visible only
when `permissions.is_owner_full_access=true`, and the page guard does not open
it to `super_admin` or non-owner users with `users.manage`, because the backend
still uses `require_owner()` for `/users`. Moving `/users` to `users.manage`
must be a later backend task.

C05 is not a real business-module connection stage. The frontend still does
not add permission grant/revoke management, and it still does not connect real
n8n, P-series, WooCommerce, MinIO, Filebrowser, products, orders, or business
tasks.

C05 has been sealed in `docs/C05_PERMISSION_SYSTEM_SEAL.md`. C06A documented
the user permission management plan in
`docs/C06_PERMISSION_MANAGEMENT_PLAN.md`, C06B added the owner-only backend
assignment APIs in `docs/C06_PERMISSION_BACKEND_ACCESS.md`, and C06C has added
the frontend User Management permission UI in
`docs/C06_PERMISSION_FRONTEND_UI.md`. C06D has released this UI to staging and
archived the acceptance in `docs/C06_PERMISSION_STAGING_ACCEPTANCE.md`. C06E
has released it to production in `docs/C06_PERMISSION_PRODUCTION_RELEASE.md`,
and C06F has sealed C06 in `docs/C06_PERMISSION_MANAGEMENT_SEAL.md`.

C06C keeps User Management owner-only. The `/users` entry remains visible only
when `permissions.is_owner_full_access=true`, and the permission management
entry is only available inside that owner-only page. The user row “权限” button
opens the user detail area, where the “用户权限管理” panel lists explicit
assignments, shows owner full access as a note rather than a normal
assignment, and lets owner grant, update, disable/enable, and revoke
assignments for non-owner users.

The C06C UI reads selectable permission keys from `/permissions/registry` and
uses the C06B APIs under `/permissions/users/{user_id}/assignments`. High-risk
grant and high-risk re-enable or scope changes require reason,
`confirm_high_risk=true`, and
`confirmation_text="CONFIRM_HIGH_RISK_PERMISSION"`. High-risk revoke requires
reason. Wildcard `*` is not shown as a grant option. Role default permissions
still do not auto-apply, and `super_admin` still does not default to
grant/revoke.

The restricted proxy now precisely allows the C06B assignment paths in
addition to the existing `/permissions/me` and `/permissions/registry` paths.
Frontend permission checks remain UX only; backend `require_owner()` and the
C06B owner-only APIs are still the security boundary. C06D verified staging
`/users`, frontend proxy owner login, owner `/auth/me`, registry access, and
the published C06C bundle markers. C06E has released the C06C UI to
production, verified production `/users` returns 200, confirmed the linked JS
bundle contains the `C06C permissions` marker, and verified owner frontend
proxy access to `/auth/me`, `/permissions/registry`,
`/permissions/users/{user_id}/assignments`, and `/users`. Production
`permission_registry` was initially empty; with explicit approval it was
initialized through the backend helper so registry-driven UI options are
available. Real business systems remain unconnected.

C06F keeps the frontend boundary sealed: User Management and the permission
management entry remain visible only to owner full access, owner users render
as full access instead of ordinary assignments, wildcard is not a grant option,
high-risk confirmation remains in the UI, and frontend checks remain UX only.
The backend owner-only C06B APIs, `require_owner()`, and `require_permission()`
remain the real security boundary.

C07A started module-isolation planning in
`docs/C07_MODULE_ISOLATION_PLAN.md`, and C07B added the backend Module Manifest
v1 / registry APIs documented in `docs/C07_MODULE_REGISTRY_BACKEND.md`.
C07C has now added frontend module-aware navigation and route guards
documented in `docs/C07_MODULE_FRONTEND_ISOLATION.md`.

The frontend calls `GET /modules/registry` and `GET /modules/me` only through
the restricted same-origin backend proxy. The proxy precisely allows those two
C07B paths and does not open a `/modules/*` wildcard. If `/modules/me` is not
available, the console marks module access as unknown, falls back to the
C05/C06 permission strategy, and keeps admin/system modules hidden from
non-owner users.

Navigation items now bind to C07B namespaced module keys. User Management maps
to `admin.users`; Permission Management remains an owner-only panel inside
User Management and is recorded as `admin.permissions`; dashboard maps to
`core.dashboard`; current foundation business placeholders map to
`business.products`, `business.jobs`, `business.artifacts`, and
`business.reviews`.

The sidebar displays safe module states only: locked, planned,
adapter_pending, and unavailable. It does not display env values, URLs,
secrets, tokens, credentials, or internal dependency details. The route guard
uses module route namespaces, shows no-permission notices for hidden/locked
modules, and shows “模块暂不可用” for planned/adapter_pending/unavailable
modules. User Management and Permission Management remain visible only to owner
full access.

C07C does not add real business pages, does not add K01 or P-series menus,
does not connect n8n, WooCommerce, MinIO, Filebrowser, product flows, or real
business tasks, does not implement Module Adapter or Execution Provider, and
does not publish staging or production.

## Configuration

For host-based development, use the example backend URL:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

The Docker example also sets `BACKEND_API_URL=http://backend:8000` for
container-to-container requests. `BACKEND_API_URL` takes precedence inside the
Next.js server. Neither variable may contain credentials.

## Docker verification

Do not install dependencies on the host. From the repository root, run:

```bash
./scripts/test_frontend_docker.sh
```

The frontend Docker build runs the route and safety verification, TypeScript
typecheck, and the production Next.js build before producing the runtime image.

Run the full repository acceptance with:

```bash
./scripts/test_foundation_acceptance.sh
```

## Temporary login preview

From the repository root, set example-only owner and token values, bootstrap
the named example project, and start the example backend/frontend:

```bash
export COMPOSE_PROJECT_NAME=barong-ops-console-preview
read -r -s -p "Preview token signing value (32+ bytes): " AUTH_TOKEN_SECRET
export AUTH_TOKEN_SECRET
export OWNER_USERNAME="preview_owner"
read -r -s -p "Preview owner password (12+ characters): " OWNER_PASSWORD
export OWNER_PASSWORD
./scripts/bootstrap_owner_docker.sh
docker-compose -p "$COMPOSE_PROJECT_NAME" \
  -f docker-compose.example.yml up --build backend frontend
```

Open `http://127.0.0.1:3000/login`. Leave `N8N_TEST_WEBHOOK_URL` and
`N8N_TEST_CALLBACK_SECRET` empty for a login-only preview. These settings and
`AUTH_TOKEN_SECRET` are environment variables; real values must not be
committed. This preview uses only `docker-compose.example.yml` and does not
connect production n8n, P-series, WooCommerce, MinIO, or Filebrowser services.
