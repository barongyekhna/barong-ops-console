# Backend

This directory contains the F05 FastAPI foundation, F06 migration mechanism,
F07 core tables, F08 authentication, F10 foundation APIs, F11 Foundation Demo,
F12 n8n Test Bridge, C03 owner-only user management API, C04B backend role
constants/validation, C05B backend permission data-model groundwork, C05C
backend permission dependency/API access, and C06B backend owner-only
permission assignment APIs, plus the C07B backend Module Manifest v1 and
read-only module registry foundation. C05C adds `require_permission()`,
`/auth/me.permissions`, read-only `/permissions/me` and
`/permissions/registry`; C06B adds owner-only assignment list/grant/update/
revoke API while keeping `/users` owner-only. C07B adds authenticated
`GET /modules/registry` and `GET /modules/me` without adding a migration or
real business integration. C06E has released the C06B backend API to production,
and C06F has sealed C06 in
`docs/C06_PERMISSION_MANAGEMENT_SEAL.md`; real business integration remains
out of scope.

C01 production deployment is complete for
`https://ops.barongyekhna.com`. The production backend service is named
`console_backend`, binds only to `127.0.0.1:8000`, reads server-local
environment at runtime, and connects to the compose-internal
`console_postgres` host. PostgreSQL does not expose a host port. The real
`.env.production` file must remain server-local and must not be printed,
committed, or read by repository checks. `OWNER_PASSWORD` is only for the first
owner bootstrap and should be cleared from the server env after bootstrap.
C01 remains foundation/console only; C02 is production/test environment
separation.

C02C has started the staging/test backend on `127.0.0.1:8100` with
`console_staging_backend`, `console_staging_postgres`,
`barong-ops-console-staging`, `console_staging_postgres_data`, and server-local
`.env.staging`. Its `DATABASE_URL` must point at
`console_staging_postgres:5432`, `AUTH_TOKEN_SECRET` and `POSTGRES_PASSWORD`
must be different from production, and the staging owner must be a test
account. C02D added read-only dual-environment checks, C02E completed final
production/staging acceptance, and C02F sealed the environment isolation
system. Both environments are usable and isolated. C02F did not read real env
files, restart production/staging containers, or connect real n8n, P-series,
WooCommerce, MinIO, or Filebrowser systems. C03D accepted the owner-created
sub-account flow on staging, and C03E has released the user-management API and
page to production. C03F has sealed the Owner-created sub-account stage.

C03B exposes owner-only user management:

- `GET /users`
- `POST /users`
- `GET /users/{user_id}`
- `PATCH /users/{user_id}`
- `POST /users/{user_id}/reset-password`
- `POST /users/{user_id}/disable`
- `POST /users/{user_id}/enable`

It creates only non-owner sub-account roles: `viewer`, `operator`, and
`reviewer`. It hashes all passwords, omits `password_hash` from responses,
writes `user.create`, `user.update`, `user.disable`, `user.enable`, and
`user.reset_password` operation logs, and keeps `/auth/register` absent. C03B
adds no migration and no full RBAC. C03C added the frontend page, C03D accepted
the user lifecycle on staging with a `c03d_test_<timestamp>` account, and C03E
released it to production at `https://ops.barongyekhna.com/users`. Production
read-only checks confirmed unauthenticated `/api/backend/users` returns 401
and `/api/backend/auth/register` still returns 404. C03 still does not add
`super_admin`, complete RBAC, or real business integration. C03F has sealed
this stage; the next stage is C04: role system.

C04A started the role-system stage with `docs/C04_ROLE_SYSTEM_PLAN.md`. C04B
has added backend role constants, role metadata, unified assignable-role
validation, tests, and owner-only `GET /users/roles`. C04C connected the
frontend role catalog UI, and C04D accepted the role catalog API/UI on staging
in `docs/C04_STAGING_ACCEPTANCE.md`. C04E has released the backend role
catalog and frontend role catalog UI to production, with the release archive
in `docs/C04_PRODUCTION_RELEASE.md`. C04F has sealed the role system in
`docs/C04_ROLE_SYSTEM_SEAL.md`. C04 defines account identity types, not the
complete permission system. The current backend still stores `users.role` as a
plain string, which is enough for C04 standard role validation and does not
require a migration in C04.

C04 standard roles are `owner`, `super_admin`, `module_admin`, `operator`,
`reviewer`, `viewer`, and `bot_agent`. Owner-created `/users` roles remain
limited to `viewer`, `operator`, and `reviewer`. `owner` stays
bootstrap-only, `super_admin` is defined without real power, `module_admin` is
reserved until module scope is defined, and `bot_agent` remains future
robot-account work. C04D verified on staging that owner can read
`/users/roles`, unauthenticated access returns 401, non-owner access returns
403, `viewer`/`operator`/`reviewer` can be created and assigned, reserved
roles cannot be created or assigned, `/auth/register` remains 404, operation
logs contain user management records, and staging `alembic current` is
`f07_core_001 (head)`. C05 will define permissions, module access, and
role-to-permission bindings. C04E verified production `/users` returns 200,
unauthenticated `/api/backend/users/roles` returns 401, production backend
health is normal, staging remains normal, and production/staging/dual-env
checks pass. C04 still does not give `super_admin` power, does not implement
complete RBAC, and does not connect real n8n, P-series, WooCommerce, MinIO,
Filebrowser, or real business tasks. C04F confirmed production `/users`
returns 200, unauthenticated `/api/backend/users/roles` and
`/api/backend/users` return 401, `/api/backend/auth/register` still returns
404, and production/staging/dual-env checks pass. C04F did not read real env
files, create production users, restart/rebuild/remove containers, modify
Nginx/certificates, commit, or connect real business systems. C04 is sealed;
OPS01 Docker Compose v1 `ContainerConfig` issue cleanup is also sealed, and
C05A has started permissions / RBAC design.

C05A is documented in `docs/C05_PERMISSION_SYSTEM_PLAN.md`. C05B is documented
in `docs/C05_PERMISSION_DATA_MODEL.md`. C05C is documented in
`docs/C05_PERMISSION_BACKEND_ACCESS.md`. C05B adds:

- `permission_registry`
- `user_permission_assignments`
- `role_default_permissions`

The current backend now has a permission registry seed source, registry
upsert, user assignment grant/disable/revoke helpers, role default permission
storage, and `user_has_permission()` / `resolve_effective_permissions()` service
helpers. Owner is treated as full global access without assignment rows.
`super_admin` receives no permissions from role alone and must have scoped
assignments.

C05C adds `require_permission(permission_key, scope_type="global",
scope_key="*")`. Owner passes in the dependency layer without assignments or
scope checks. Non-owner users must have enabled, unexpired, scope-matching
`user_permission_assignments`; `super_admin` does not default to global access.

`GET /auth/me` now keeps the original identity fields and adds a `permissions`
object. Owner returns `is_owner_full_access=true` and
`permission_keys=["*"]`, so the response does not depend on registry seed
state. Non-owner users receive only explicit effective assignments.
`POST /auth/login` keeps the previous `AuthenticatedUser` response contract.

C05C also exposes read-only permission APIs:

- `GET /permissions/me` for the current user's effective permissions.
- `GET /permissions/registry`, protected by owner or `permissions.read`, for
  enabled registry entries.

C05C still does not add frontend permission UI, does not add grant/revoke API,
does not replace current `/users` owner-only behavior, and does not connect
real business integrations.

C05 has been sealed in `docs/C05_PERMISSION_SYSTEM_SEAL.md`, and C06A has
started user permission management planning in
`docs/C06_PERMISSION_MANAGEMENT_PLAN.md`. C06B is documented in
`docs/C06_PERMISSION_BACKEND_ACCESS.md` and implements:

- `GET /permissions/users/{user_id}/assignments`
- `POST /permissions/users/{user_id}/assignments`
- `PATCH /permissions/users/{user_id}/assignments/{assignment_id}`
- `DELETE /permissions/users/{user_id}/assignments/{assignment_id}`

All four C06B routes use `require_owner()`. They do not use
`require_permission("permissions.manage")`, so `super_admin` still does not
receive grant/revoke power by default. `role_default_permissions` still does
not automatically grant effective permissions. High-risk permissions require a
reason, `confirm_high_risk=true`, and
`confirmation_text="CONFIRM_HIGH_RISK_PERMISSION"` for grant and high-risk
re-enable or scope-changing update. Revoke is a soft revoke through
`is_enabled=false`. Grant/update/revoke write existing `operation_logs`.

C06B adds no migration, no frontend permission UI, no staging/production
release, and no real business integration.

C06D has released the C06B backend API to staging and archived the acceptance
in `docs/C06_PERMISSION_STAGING_ACCEPTANCE.md`. The staging backend assignment
routes are live, Alembic current/head remains `c05b_permissions_001 (head)`,
and no Alembic upgrade was executed for C06D. During acceptance, staging
`permission_registry` was initially empty; with explicit approval, the existing
`upsert_permission_registry()` application helper was run inside the staging
backend container to initialize only registry seed rows. C06D did not use psql,
did not hand-write SQL, did not operate the staging postgres container, did not
read real env files, did not release production, and did not connect real
business systems.

C06E has released the C06B backend API to production and archived the release
in `docs/C06_PERMISSION_PRODUCTION_RELEASE.md`. Production backend safe
release succeeded, Alembic current/head remained `c05b_permissions_001 (head)`
with no upgrade, and owner `/permissions/users/{owner_id}/assignments` returns
200 with owner full-access metadata. Production `permission_registry` was
initially empty; with explicit approval, the existing backend helper
`upsert_permission_registry()` was run inside the production backend container
to initialize only registry seed rows. C06E did not use psql, did not hand-write
SQL, did not operate the production postgres container, did not write
`user_permission_assignments` or `role_default_permissions`, did not create
production test accounts, did not read real env files, and did not connect real
business systems.

C06F has sealed C06 user permission management in
`docs/C06_PERMISSION_MANAGEMENT_SEAL.md`. The backend boundary remains: all
C06B assignment list/grant/update/revoke routes are owner-only, `/users` still
uses `require_owner()`, `/auth/register` still returns 404, owner still has
global full access without assignment rows, `super_admin` does not default to
grant/revoke, `role_default_permissions` does not auto-apply, high-risk
confirmation remains required, and grant/update/revoke operation logs are
written by the backend.

C07A has started module-isolation planning in
`docs/C07_MODULE_ISOLATION_PLAN.md`. C07A is docs-only and does not change the
backend runtime. Future C07B work should define backend Module Manifest v1 and
module registry foundations so future business modules declare `module_key`,
category, status, lifecycle, permissions, route namespace, API namespace,
external dependencies, isolation policy, and staging/production acceptance
requirements before they enter backend routes. C07A does not implement Module
Adapter, Execution Provider, sandboxing, module switches, n8n integration, new
API, migration, staging release, production release, or real business tasks.

C07B has implemented that backend registry foundation and is documented in
`docs/C07_MODULE_REGISTRY_BACKEND.md`. It adds:

- `backend/app/schemas/module.py` for Module Manifest v1 and access-state
  response schemas.
- `backend/app/core/modules.py` for the static code-only manifest registry.
- `backend/app/services/module_registry.py` for validation and current-user
  access-state decisions.
- `GET /modules/registry` for authenticated safe registry metadata.
- `GET /modules/me` for authenticated module access state based on existing
  C05/C06 effective permissions.

The C07B registry covers current console modules such as `core.dashboard`,
`admin.users`, `admin.permissions`, `admin.modules`, `business.jobs`,
`business.products`, `integration.n8n_test_bridge`, `system.errors`, and
`system.memory_events`. Business modules default to `show_locked`;
admin/system modules default to `hide_when_denied`; planned and
adapter-pending modules are not executable. C07B does not add frontend UI, does
not add migration, does not implement Module Adapter or Execution Provider,
does not connect K01/P-series/n8n/WooCommerce/MinIO/Filebrowser, and does not
write real business data.

C07D has added backend module registry contract verification documented in
`docs/C07_MODULE_ISOLATION_VERIFICATION.md`. The primary backend test entry is
`tests/backend/test_modules_registry.py`; it now covers Module Manifest v1
required fields, unique and valid `module_key`, legal category/status/
lifecycle/denied behavior, route/API namespace rules, permission manifest
alignment, generic permission-key rejection, external dependency safety,
planned/adapter_pending/unavailable non-executable access states, K01/P-series
no-connect boundaries, the `integration.n8n_test_bridge` test-only limit, and
C05/C06 regressions for owner full access, non-owner hidden admin/system,
business locked state, `role_default_permissions`, `super_admin`,
`/users`, `/auth/register`, `/permissions/me`, and C06B assignment APIs.
C07D does not modify backend runtime code, add APIs, add migrations, connect
providers, or release staging/production.

F12 adds the n8n test webhook bridge:

- `POST /n8n-test/run`
- `POST /n8n-test/callback`
- `GET /n8n-test/latest`

Run and latest require the owner Bearer token. Run creates or reuses only the
`n8n_test_bridge`, `n8n_test_agent`, and `n8n_test_webhook_workflow` demo
registry records, creates a test Job, and sends the minimal test payload
through the standard-library HTTP client. The configured URL must use HTTP(S)
and contain an explicit test/demo marker. Redirects are rejected.

The callback does not use owner authentication. It requires
`X-Barong-Callback-Secret` to match `N8N_TEST_CALLBACK_SECRET`, accepts only
the `n8n_test_bridge` run type and `completed_demo` or `failed`, and cannot
trigger a downstream workflow. Successful callbacks register metadata-only
demo Artifact, pending demo Review, no-model Memory Event, Job Events, and
Operation Logs. Dispatch failures mark the test Job failed and write a
System Error.

`N8N_TEST_WEBHOOK_URL` is empty by default, so the run endpoint fails safely
without a network request until explicitly configured.
`N8N_TEST_CALLBACK_SECRET` and `N8N_TEST_REQUEST_TIMEOUT_SECONDS` are also
environment settings. Neither the URL nor callback value is stored in the
workflow registry, returned by an API, or written to operation logs.

F12 uses the existing foundation tables and adds no migration or dependency.
Its tests mock the HTTP sender. It does not call real n8n production
workflows, P-series endpoints, WooCommerce, MinIO, or Filebrowser and does not
create real business tasks.

F11 adds the owner-only Foundation Demo transaction:

- `POST /foundation-demo/run`
- `GET /foundation-demo/latest`

The run endpoint creates or reuses demo Module, Agent, and Workflow registry
records, then records a new pending demo Job, six Job Events, metadata-only
Artifact, pending demo Review, no-model Memory Event, and related Operation
Logs. The only terminal status is `completed_demo`. The job type is stored in
the existing safe input payload, so F11 requires no schema migration.

All successful writes are committed as one unit. If a run fails, that unit is
rolled back and a separate safe System Error plus failure Operation Log is
recorded. The service has no external HTTP client and does not trigger real
n8n, WooCommerce, MinIO/Filebrowser, P-series work, models, or business tasks.

F07 adds:

- SQLAlchemy models for all 14 reviewed core foundation tables.
- PostgreSQL JSONB-backed structured fields through portable SQLAlchemy types.
- Primary keys, stable business ID uniqueness, required status fields,
  timestamps, and the core tracing foreign keys.
- One Alembic revision that creates and removes the empty tables.

F08 adds Argon2id password hashing, controlled owner initialization, JWT
authentication, and authentication operation logs. C03B later split active-user
authentication from owner-only authorization. Auth exposes:

- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`

F08 itself did not add a frontend login page; F09 added that page later.
There is still no registration API, complex permission matrix, seed data, or
real external integration.

F10 adds authenticated list/detail APIs and controlled foundation/demo writes
for Modules, Agents, Workflows, Jobs, Job Events, Artifacts, Reviews, System
Errors, Memory Events, and Context Packets. Memory Summaries and Operation
Logs are read-only. All write operations commit their audit log in the same
transaction.

F10 records metadata only. It does not trigger a workflow engine, call a
model, upload a file, connect WooCommerce, or create a real product/business
job. Job creation accepts only `pending` or `draft`; event-driven completion
uses the explicit `completed_demo` status.

## Run tests

Use the isolated example Docker environment from the repository root. Do not
create a virtual environment or install these dependencies into the server's
system Python:

```bash
./scripts/test_backend_docker.sh
```

The equivalent explicit commands are:

```bash
docker compose -f docker-compose.example.yml build backend
docker compose -f docker-compose.example.yml run --rm --no-deps backend python -m pytest tests/backend/test_health.py
```

The script falls back to the legacy `docker-compose` executable when the
Compose v2 plugin is unavailable.

Run the isolated PostgreSQL schema, Alembic, authentication, and owner
bootstrap checks with:

```bash
./scripts/test_backend_db_docker.sh
```

This uses only the example Compose file and example credentials. It runs the
security, authentication, F10/F11/F12 API, audit, and external-boundary tests and
verifies migration upgrade, downgrade, and a second upgrade. Do not point
`DATABASE_URL` at a production database.
Do not install the requirements in the system Python or commit a real `.env`
file.

Run the repository-wide F13 acceptance, including this backend suite, the
frontend build, Compose validation, diff checks, and safety scans with:

```bash
./scripts/test_foundation_acceptance.sh
```

The database test performs `alembic upgrade head`, `downgrade base`, a second
`upgrade head`, and `alembic check`. The accepted foundation started with
`f07_core_001`; C05B adds `c05b_permissions_001` for permission data-model
tables. F13 itself adds no migration or dependency.

Initialize an example owner from environment variables with:

```bash
export OWNER_USERNAME="choose-an-owner-name"
read -r -s -p "Owner password: " OWNER_PASSWORD
export OWNER_PASSWORD
./scripts/bootstrap_owner_docker.sh
unset OWNER_PASSWORD
```

The example placeholders in `.env.example` are not production credentials.
`AUTH_TOKEN_SECRET` must be supplied separately and must contain at least 32
bytes before login tokens can be issued.
`N8N_TEST_WEBHOOK_URL` and `N8N_TEST_CALLBACK_SECRET` must also be supplied
through the environment only when intentionally exercising a test/demo
webhook. Never commit real values or point them at a production workflow.

## Run the example backend

```bash
docker compose -f docker-compose.example.yml up --build backend
```

The health endpoint is available at `http://127.0.0.1:8000/health`.
It continues to report `database: "not_configured"` and does not perform a
database connectivity check. The authenticated F10 endpoints use the example
database, while real external integrations and business modules remain absent.
