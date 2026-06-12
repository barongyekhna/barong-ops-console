# Barong Ops Console

Barong Ops Console is the control-panel foundation for the Barong Yekhna independent-site automation operating system.

This project must be built as an independent containerized console and must not modify existing production n8n, Filebrowser, MinIO, WooCommerce, or legacy Baisuwan containers directly.

Core rule:
- Build the empty foundation first.
- Add business modules one by one.
- Every module must be registered, isolated, testable, and removable.

## F13 foundation acceptance

F05 through F12 are complete and accepted as the first-generation empty
foundation. The repository is still in the foundation/demo stage:

- The FastAPI backend, PostgreSQL migration path, owner authentication,
  Next.js shell, F10 foundation APIs, F11 Foundation Demo, and F12 n8n Test
  Bridge are present.
- F11 and F12 are exercise loops only. They do not represent real business
  completion.
- No real P-series, Baisuwan, WooCommerce, MinIO, Filebrowser, production n8n
  workflow, AI model, product task, or product page is connected.
- The next phase may add real modules only after separate design, security,
  and production-readiness review.

Run the complete F13 acceptance suite from the repository root:

```bash
./scripts/test_foundation_acceptance.sh
```

The script runs only the existing example Docker tests, validates the example
Compose file, checks the diff, and scans foundation source for prohibited
registration, credential, external-integration, host-dependency, and
production-path changes. It does not operate on production containers or
production Compose files.

The detailed acceptance record and residual risks are in
`docs/FOUNDATION_ACCEPTANCE_F13.md`.

## C01 production deployment

C01 production deployment is complete and sealed for the formal console domain
`https://ops.barongyekhna.com`:

- `docker-compose.production.yml` defines `console_frontend`,
  `console_backend`, and `console_postgres` on the dedicated
  `barong-ops-console-prod` network.
- `.env.production.example` documents placeholder-only production settings.
  The real `.env.production` must stay server-local and must not be committed.
- Production frontend and backend are exposed only on `127.0.0.1:3000` and
  `127.0.0.1:8000`; PostgreSQL stays private on the Docker network.
- Nginx now reverse-proxies `ops.barongyekhna.com`, HTTPS is enabled, and HTTP
  redirects to HTTPS.
- `docs/C01_PRODUCTION_DEPLOYMENT.md` contains the deployment, HTTPS,
  bootstrap, rollback, and production-boundary checklist.
- `docs/C01_PRODUCTION_ACCEPTANCE.md` records the C01C production acceptance
  evidence and C01 sealing conclusion.
- `scripts/check_production_deploy_files.sh` validates the deployment files
  and compose syntax without reading or modifying the real `.env.production`.
- `scripts/production_smoke_check.sh` runs a read-only production smoke check
  for HTTPS login, backend health proxy, HTTP redirect, and Docker status.

C01 remains foundation/console only. It still does not connect real P-series
workflows, production n8n, WooCommerce, MinIO, or Filebrowser. It does not
create real products or real business tasks. The next stage is C02:
production/test environment separation.

## C02 production/staging isolation

C02A documented the production/test isolation plan in
`docs/C02_ENVIRONMENT_ISOLATION_PLAN.md`. C02B prepared the staging
construction files. C02C started staging on server-local ports, initialized
the staging owner, and tested the backend login path. C02D added
dual-environment operations documentation and read-only checks. C02E completed
final production/staging acceptance. C02F has now sealed the environment
isolation system.

Current staging defaults:

- Compose project: `barong-ops-console-staging`
- Frontend: `127.0.0.1:3100`
- Backend: `127.0.0.1:8100`
- PostgreSQL: Docker network only, no host `5432`
- Network: `barong-ops-console-staging`
- Volume: `console_staging_postgres_data`
- Env files: `.env.staging.example` committed, real `.env.staging` local only

Staging is still not exposed publicly. C02F did not modify production, Nginx,
certificates, real env files, production/staging containers, or real business
systems.

Run the staging static check with:

```bash
./scripts/check_staging_deploy_files.sh
```

Run the staging read-only smoke check with:

```bash
./scripts/staging_smoke_check.sh
```

Run the production + staging read-only status check with:

```bash
./scripts/check_dual_env_status.sh
```

Details are in `docs/C02_STAGING_SETUP.md`,
`docs/C02_DUAL_ENV_OPERATIONS.md`, and
`docs/C02_ENVIRONMENT_ISOLATION_ACCEPTANCE.md`. The final seal is in
`docs/C02_ENVIRONMENT_ISOLATION_SEAL.md`.

C02 remains foundation/console only. It still does not connect real n8n,
P-series, WooCommerce, MinIO, Filebrowser, products, orders, or business
tasks. The next stage is C03: Owner creates sub-accounts.

## C03 owner account management

C03B implemented the backend owner-created sub-account API, C03C added the
frontend user management surface, C03D accepted the flow on staging, C03E
released it to production, and C03F has sealed the Owner-created sub-account
stage:

- `docs/C03_OWNER_ACCOUNT_MANAGEMENT_PLAN.md` records the users/auth audit,
  C03 scope, backend API, frontend implementation, security rules,
  staging-first flow, and C03B-C03F task split.
- `docs/C03_STAGING_ACCEPTANCE.md` records the C03D staging acceptance result,
  including the test user lifecycle, operation log verification, production
  smoke result, and environment safety boundaries.
- `docs/C03_PRODUCTION_RELEASE.md` records the C03E production release
  acceptance result, including production `/users` availability, unauthenticated
  `/api/backend/users` returning 401, `/auth/register` still returning 404, and
  production/staging/dual-env smoke checks passing.
- `docs/C03_OWNER_ACCOUNT_MANAGEMENT_SEAL.md` records the C03F final seal:
  C03 is complete, User Management is in production, there is still no public
  registration, and `super_admin` plus full RBAC stay out of C03.
- Owner-only `/users` APIs now support list, create, detail, update,
  enable/disable, and reset-password for sub-accounts.
- The protected `/users` console page is available under **User Management**
  in the System navigation.
- The production user management page is available at
  `https://ops.barongyekhna.com/users`.
- The page can list users, create `viewer`, `operator`, and `reviewer`
  accounts, view user details, update managed roles, enable/disable users,
  and reset sub-account passwords through the restricted frontend API proxy.
- `get_current_user` now validates active authenticated users, while
  `require_owner` handles owner-only authorization for `/users`.
- Active non-owner users can log in and call `/auth/me`; inactive users cannot
  log in or use protected APIs.
- C03D verified this on staging with a `c03d_test_<timestamp>` account, without
  reading real env files, printing secrets, changing Nginx/certificates,
  restarting containers, or connecting real business workflows.
- C03E verified production read-only behavior without reading real env files,
  creating production users, changing Nginx/certificates, restarting containers,
  or connecting real business workflows.
- C03F sealed the scope without reading or modifying real env files, creating
  production users, restarting/rebuilding containers, changing Nginx or
  certificates, committing, or connecting real business systems.
- C03 does not add `super_admin`, full RBAC, public registration,
  OAuth/email flows, or real business workflows.

The current system remains foundation/console only. Real n8n, P-series,
WooCommerce, MinIO, Filebrowser, products, orders, and business tasks are
still not connected. The next stage is C04: role system.

## C04 role system

C04A started the role-system stage with the design plan in
`docs/C04_ROLE_SYSTEM_PLAN.md`. C04B has added backend role constants,
metadata, validation, tests, and an owner-only `GET /users/roles` catalog.
C04C has updated the User Management frontend to read that catalog through
`/api/backend/users/roles`. C04D accepted the role catalog UI/API on staging;
the acceptance record is `docs/C04_STAGING_ACCEPTANCE.md`. C04E released the
role catalog backend and frontend UI to production; the release archive is
`docs/C04_PRODUCTION_RELEASE.md`. C04F has sealed the role-system stage in
`docs/C04_ROLE_SYSTEM_SEAL.md`.

C04 defines account identity types. It does not define the full permission
matrix. C05 will define permissions, module access, and how roles map to
allowed actions.

Current C04 status:

- Existing `users.role` is a string and can hold the C04 standard role names.
- C04B adds no migration; role validation is application-level for now.
- Standard roles are `owner`, `super_admin`, `module_admin`, `operator`,
  `reviewer`, `viewer`, and `bot_agent`.
- `owner` must still come only from bootstrap or system initialization, not
  from `/users`.
- Owner-created `/users` roles remain limited to `viewer`, `operator`, and
  `reviewer`.
- `super_admin` is defined in C04 but should not receive all permissions in
  C04; C05 must decide concrete permissions.
- `module_admin` is defined but not open for `/users` creation until module
  scope is defined in C05/C07.
- `bot_agent` is reserved for future robot accounts and is not connected to a
  real bot/agent workflow in C04.
- C04B keeps `/users` owner-only and only replaces hard-coded owner checks
  with the shared role helper.
- C04C makes the create-user and managed-role selectors use the backend role
  catalog. The selectors currently show only `viewer`, `operator`, and
  `reviewer`.
- The production User Management page at `https://ops.barongyekhna.com/users`
  now uses the role catalog UI.
- The User Management page now explains that `super_admin`, `module_admin`,
  and `bot_agent` are reserved roles and are not assignable in C04.
- C04D verified on staging that `/users/roles` is owner-only, unauthenticated
  access returns 401, non-owner access returns 403, `viewer`/`operator`/
  `reviewer` can be created and assigned, reserved roles cannot be created or
  assigned, `/auth/register` remains 404, and operation logs contain user
  management records.
- C04D also verified staging `/login`, `/users`, and `/api/backend/health`,
  confirmed the running frontend build contains the role catalog UI, and
  reran production/staging/dual-env smoke checks successfully.
- C04D did not rebuild, recreate, stop, remove, or restart production/staging
  containers; did not run `docker-compose up/down`; did not read real env
  files; did not modify Nginx/certificates; did not create production users;
  and did not connect real business systems.
- C04E verified production `/users` returns 200, unauthenticated
  `/api/backend/users/roles` returns 401, production backend health is normal,
  staging `/users` remains normal, and production/staging/dual-env smoke
  checks pass.
- C04E did not read or modify real env files, create production users,
  restart/rebuild/remove containers, modify Nginx/certificates, or connect
  real business systems.
- C04F sealed the role system: production `/users` returns 200,
  unauthenticated `/api/backend/users/roles` and `/api/backend/users` return
  401, `/api/backend/auth/register` still returns 404, and
  production/staging/dual-env checks pass.
- C04F did not read or modify real env files, create production users,
  restart/rebuild/remove containers, modify Nginx/certificates, commit, or
  connect real business systems.
- C04 does not add `super_admin` powers, complete RBAC, or real user/business
  creation.
- Company positions such as designer, SEO editor, customer service, or factory
  supervisor should be represented with `role` plus later `job_title`,
  `department`, `module_access`, and `permissions`, not as new hard-coded role
  strings.

C04 remains foundation/console only. It does not connect real n8n, P-series,
WooCommerce, MinIO, Filebrowser, products, orders, or business tasks.
C04 is sealed. OPS01 Docker Compose v1 `ContainerConfig` cleanup is also
sealed. C05 is sealed, and C06 user permission management is sealed in
`docs/C06_PERMISSION_MANAGEMENT_SEAL.md`.

## OPS01 Docker Compose governance

OPS01 is sealed. It governed the recurring Docker Compose v1
`KeyError: 'ContainerConfig'` deployment issue without installing tools,
upgrading Docker, reading real env files, modifying Nginx/certificates, or
connecting real business systems.

The current server still has only `docker-compose` v1.29.2 available. Docker
Compose v2 was not installed because the current apt source has no
`docker-compose-plugin` candidate package. Compose v2 can be evaluated later as
a separate toolchain task, but it does not block the product roadmap.

OPS01 now uses `scripts/safe_compose_release.sh` as the default backend/frontend
release path. The script defaults to dry-run, requires explicit project names,
allows only staging/production backend/frontend targets, rejects postgres, and
requires double confirmation for production real execution.

OPS01C rehearsed safe release on staging backend/frontend. OPS01D rehearsed it
on production backend/frontend. Both environments passed smoke checks and
dual-env status checks, rollback tags exist, production postgres remained
untouched, staging remained isolated, and the Docker Compose v1
`ContainerConfig` issue did not recur.

The OPS01 records are:

- `docs/OPS01_DOCKER_COMPOSE_GOVERNANCE_PLAN.md`
- `docs/OPS01_SAFE_RELEASE_RUNBOOK.md`
- `docs/OPS01_STAGING_SAFE_RELEASE_ACCEPTANCE.md`
- `docs/OPS01_PRODUCTION_SAFE_RELEASE_DRY_RUN.md`
- `docs/OPS01_PRODUCTION_SAFE_RELEASE_ACCEPTANCE.md`
- `docs/OPS01_SAFE_RELEASE_SEAL.md`

Future staging/production backend/frontend releases should prefer
`scripts/safe_compose_release.sh` instead of `docker-compose --force-recreate`.
OPS01 is complete. C05 permission-system work and C06 user permission
management work are now sealed.

## C05 permission system

C05A starts the permission-system stage with
`docs/C05_PERMISSION_SYSTEM_PLAN.md`. C05B adds the backend permission data
model documented in `docs/C05_PERMISSION_DATA_MODEL.md`. C05C adds backend
permission access enforcement and current-user permission APIs documented in
`docs/C05_PERMISSION_BACKEND_ACCESS.md`. C05D adds frontend permission-aware
navigation, no-permission messaging, and lightweight route protection
documented in `docs/C05_PERMISSION_FRONTEND_ACCESS.md`. C05E accepted the
permission system on staging in
`docs/C05_PERMISSION_STAGING_ACCEPTANCE.md`. C05F released and accepted the
permission system on production in
`docs/C05_PERMISSION_PRODUCTION_RELEASE.md`. C05G sealed the full permission
system in `docs/C05_PERMISSION_SYSTEM_SEAL.md`.

C05 is about authorization, not business-module onboarding. It does not connect
real n8n, P-series, WooCommerce, MinIO, Filebrowser, product flows, orders, or
business tasks.

Current C05 status:

C05 is sealed. C06 user permission management is also sealed in
`docs/C06_PERMISSION_MANAGEMENT_SEAL.md`. The next step must follow the
project plan, not P-series work and not real business onboarding inside C06.

- C05A audited the existing auth, role, user-management, frontend navigation,
  and role-system tests/docs.
- C05B added `permission_registry`, `user_permission_assignments`, and
  `role_default_permissions` with Alembic migration `c05b_permissions_001`.
- C05B added the first permission registry seed source, idempotent registry
  upsert, assignment grant/disable/revoke helpers, role default permission
  storage, and base permission query services.
- C05C added `require_permission()`, extended `GET /auth/me` with
  `permissions`, and exposes read-only `GET /permissions/me` plus
  `GET /permissions/registry`.
- Owner has full global access through dependency/resolver logic and does not
  need per-permission assignment rows. C05C API responses use
  `permission_keys: ["*"]` for owner.
- `super_admin` is still not a global owner; it receives no permission from
  role alone and only gets power through explicit scoped assignments.
- Current `/users` management remains owner-only through backend
  `require_owner`.
- Current `/auth/me` keeps the old identity fields and now adds a
  `permissions` object. The login response keeps the older user contract.
- Current frontend navigation reads `permissions` from `/auth/me`. Business
  modules remain visible with a locked state when denied, while admin/system
  entries are hidden when denied.
- C05E released only staging backend/frontend with the OPS01 safe release
  flow, applied staging Alembic `c05b_permissions_001 (head)` from the staging
  backend container, and verified owner plus non-owner permission behavior.
- C05E verified owner wildcard full access, non-owner no-wildcard empty
  permissions, non-owner `/users` 403, non-owner `/permissions/registry` 403,
  unauthenticated `/auth/me` / `/permissions/me` / `/users` 401, and
  `/auth/register` 404.
- C05E verified the C05D frontend policy: User Management is hidden for
  non-owner users, admin/system entries hide when denied, business entries show
  locked when denied, and direct denied routes show the no-permission notice.
- C05F released production backend with the OPS01 safe release flow, then ran
  Alembic `upgrade head` only inside the new production backend container.
  Production Alembic current/head is `c05b_permissions_001 (head)`.
- C05F released production frontend with the OPS01 safe release flow and
  confirmed production `/auth/me`, `/permissions/me`, `/permissions/registry`,
  `/users`, `/auth/register`, `/login`, and `/users` page behavior.
- C05F added the missing frontend proxy allowlist for read-only
  `GET /permissions/me` and `GET /permissions/registry`, plus a verifier check
  so these C05 endpoints stay exposed through `/api/backend`.
- C05F verified production owner full access and wildcard through both the
  frontend proxy and backend direct path. Production non-owner dynamic
  verification was not run because there was no existing account/password and
  C05F does not create production test accounts.
- C05A defines Permission Registry, User Permission Assignment, Role Default
  Permissions, Permission Scope, and Module Permission Manifest concepts;
  C05B implements the first three as backend tables.
- Ordinary users currently receive permissions through explicit assignment by
  owner. Scoped admin delegation is future work, not C06B behavior.
- C05D/C05F do not add permission grant/revoke UI, do not replace `/users`
  `require_owner()`, and do not connect real business systems.
- User Management remains owner-only in both backend and frontend. C05D does
  not expose `/users` to `super_admin` or ordinary non-owner users with
  `users.manage`; changing `/users` to permission-based access must be C06 or
  a separate backend task.
- C05F did not operate production postgres, did not directly connect
  production DB, did not read real env files, did not add grant/revoke UI or
  API, did not create production test accounts, and did not connect real
  business systems.
- C06B added owner-only assignment list/grant/update/revoke APIs under
  `/permissions/users/{user_id}/assignments`, kept `/users` owner-only, kept
  `super_admin` from receiving grant/revoke by default, and kept
  `role_default_permissions` from auto-applying.
- C06C added the User Management “权限” entry and “用户权限管理” panel, using
  `/permissions/registry` plus the C06B assignment APIs through the restricted
  frontend proxy. Frontend checks remain UX only; backend `require_owner()`
  remains the security boundary.
- C06D released C06B/C06C to staging, initialized staging
  `permission_registry` seed only after explicit approval through the existing
  backend helper, and completed dynamic owner/non-owner grant/update/revoke,
  high-risk, operation_logs, `/users` owner-only, `/auth/register` 404,
  `role_default_permissions`, and `super_admin` checks.
- C06E released production backend/frontend with OPS01 safe release. Production
  Alembic stayed at `c05b_permissions_001 (head)` and no upgrade was executed.
  Production `permission_registry` was initially empty; after explicit
  approval it was initialized only through backend helper
  `upsert_permission_registry()` and now returns 18 registry items.
- C06E verified production owner `/auth/me`, `/permissions/me`,
  `/permissions/registry`, `/permissions/users/{user_id}/assignments`, and
  `/users`; verified C06C bundle marker on `/users`; confirmed unauthenticated
  `/auth/me`, `/permissions/me`, `/users` remain 401 and `/auth/register`
  remains 404. It did not create production test accounts, did not write
  production assignments, did not operate production postgres, did not read
  real env files, did not publish staging, and did not connect real business.
- C05G sealed the permission system. The sealed record confirms `/users` stays
  owner-only, User Management stays owner full access only, owner remains
  global full access, `super_admin` is not global by default, role defaults do
  not auto-grant permissions, frontend permissions are UX only, and backend
  `require_permission()` / `require_owner()` remain the security boundary.
- C05 does not include grant/revoke API, permission assignment UI, complete
  company/factory/department scope management, or real n8n/P-series/
  WooCommerce/MinIO/Filebrowser business integration.
- C06F sealed user permission management after C06D staging acceptance and
  C06E production release archival. C18/later remains the place for
  organization scope and business-module Permission Manifest rules.

## C06 user permission management

C06A started with `docs/C06_PERMISSION_MANAGEMENT_PLAN.md` as the read-only
audit and design stage for owner-managed user permission assignment. C06B
added the backend owner-only assignment API documented in
`docs/C06_PERMISSION_BACKEND_ACCESS.md`. C06C added the frontend User
Management permission UI documented in `docs/C06_PERMISSION_FRONTEND_UI.md`.
C06D released C06B/C06C to staging and archived the acceptance in
`docs/C06_PERMISSION_STAGING_ACCEPTANCE.md`. C06E released C06B/C06C to
production and archived owner read-only acceptance in
`docs/C06_PERMISSION_PRODUCTION_RELEASE.md`. C06F sealed the full C06 user
permission management stage in `docs/C06_PERMISSION_MANAGEMENT_SEAL.md`.

C06 is scoped to user permission management after the C05 permission-system
seal:

- owner can view a user's permission assignments.
- owner can grant, revoke, and update permission assignments through the C06B
  backend API.
- owner can use the C06C User Management UI to view assignments, grant,
  update, disable/enable, and revoke explicit assignments for non-owner users.
- assignment changes write `operation_logs`.
- high-risk permissions require explicit secondary confirmation with
  `CONFIRM_HIGH_RISK_PERMISSION`.
- `/users` remains backend owner-only.
- User Management remains visible only to owner full access.
- `super_admin` is not a global owner and does not default to grant/revoke
  ability.
- `role_default_permissions` remains a template only and does not
  automatically grant effective permissions.
- C06 first-version scope handling stays limited to existing assignment scope
  fields such as `global` and `module`; complete company/factory/department
  organization scope management remains deferred to C18.
- C06D verified staging owner assignment list, ordinary grant/update/revoke,
  `/permissions/me` effective permission changes, high-risk secondary
  confirmation, operation logs, non-owner 403s, `/users` owner-only,
  `/auth/register` 404, role defaults not auto-applying, and production staying
  untouched.
- During C06D, staging `permission_registry` was initially empty. With explicit
  approval, the existing backend `upsert_permission_registry()` application
  helper initialized the staging registry seed from inside the staging backend
  container. No migration, direct SQL, postgres-container operation, env read,
  production release, or real business connection was performed.
- During C06E, production `permission_registry` was initially empty. With
  explicit approval, the same existing backend helper initialized the
  production registry seed from inside the production backend container;
  registry count is 18. C06E did not create production test accounts and did
  not execute production grant/update/revoke writes.
- C06F sealed C06 with backend C06B assignment APIs still owner-only,
  frontend permission management still owner-only, `/users` still owner-only,
  `/auth/register` still 404, owner still global full access,
  `super_admin` still without default grant/revoke, `role_default_permissions`
  still not auto-applying, high-risk confirmation preserved, and
  `operation_logs` written by the backend.

Final split:

- C06B: backend owner-only assignment list/grant/revoke/update API and tests
  are implemented.
- C06C: frontend permission management UI inside User Management and tests are
  implemented.
- C06D: staging permission-management acceptance is complete.
- C06E: production permission-management release archive is complete.
- C06F: C06 permission-management seal is complete.

## C07 module isolation

C07 has started with C07A, documented in
`docs/C07_MODULE_ISOLATION_PLAN.md`. C07A is a module-isolation audit and
design stage only. It does not implement Module Adapter, Execution Provider,
module sandbox, module switches, approval gates, secret rules, n8n
integration, new API, new UI, migration, staging release, production release,
or real business workflows.

C07 defines the rule set for future modules such as SEO, GEO, K01 product
knowledge, product page automation, image assets, article generation, review,
publish, and integration bridges. Future modules must declare stable
`module_key`, category, status, lifecycle, route namespace, API namespace,
navigation behavior, denied behavior, permissions, external dependencies,
isolation policy, and staging/production acceptance requirements before they
enter the console.

Current C07A conclusions:

- User Management is an admin/system management module and remains owner-only.
- Permission Management is an admin/system security management module and
  remains owner-only.
- Business modules default to `show_locked` when denied.
- Admin/system modules default to `hide_when_denied` when denied.
- C07 does not allow modules to directly connect real n8n, WooCommerce,
  MinIO, Filebrowser, AI providers, or production business workflows.
- K01 is a future business module, not C07. Before later adapter work, it
  should remain `adapter_pending`, disabled by default, and hidden from normal
  navigation.

C07B has added the backend Module Manifest v1 and read-only module registry
foundation documented in `docs/C07_MODULE_REGISTRY_BACKEND.md`:

- Static code-only module manifests in `backend/app/core/modules.py`; no new
  database table and no migration.
- Manifest and access-state schemas in `backend/app/schemas/module.py`.
- Central validation and current-user access-state logic in
  `backend/app/services/module_registry.py`.
- Authenticated `GET /modules/registry` for safe registry metadata.
- Authenticated `GET /modules/me` for owner/non-owner module access state.
- Initial registry includes current console/core modules such as
  `core.dashboard`, `admin.users`, `admin.permissions`, `admin.modules`,
  `business.jobs`, `business.products`, `integration.n8n_test_bridge`,
  `system.errors`, and `system.memory_events`.
- business modules denied by permission return locked metadata through
  `show_locked`; admin/system modules denied by permission use
  `hide_when_denied`.
- `planned`, `adapter_pending`, and `unavailable` modules are not executable.
- C07B does not add frontend UI, does not add migration, does not connect K01,
  P-series, n8n, WooCommerce, MinIO, Filebrowser, or real business flows.

C07C has added frontend module-aware navigation and route guards documented in
`docs/C07_MODULE_FRONTEND_ISOLATION.md`:

- Frontend module types, normalization helpers, and API client consume
  `GET /modules/registry` and `GET /modules/me` through the restricted proxy.
- The proxy precisely allows `GET /modules/registry` and `GET /modules/me`
  without opening a `/modules/*` wildcard.
- Sidebar navigation now uses C07B namespaced keys such as `core.dashboard`,
  `admin.users`, `admin.permissions`, `business.jobs`, and `system.errors`.
- Permission Management remains an owner-only panel inside User Management and
  is recorded as `admin.permissions`.
- business denied modules remain visible as locked, while admin/system denied
  modules remain hidden.
- `planned`, `adapter_pending`, and `unavailable` modules show safe
  unavailable states and cannot enter a real workspace.
- If `/modules/me` is unavailable, the frontend marks module access unknown and
  falls back to the C05/C06 permission strategy without exposing admin/system
  modules to non-owner users.
- C07C does not add backend APIs, migrations, K01, P-series, n8n,
  WooCommerce, MinIO, Filebrowser, Module Adapter, Execution Provider,
  staging release, production release, or real business flows.

C07D has added the module-isolation verify/test system documented in
`docs/C07_MODULE_ISOLATION_VERIFICATION.md`:

- Backend module registry contract tests now cover Module Manifest v1 required
  fields, unique and valid `module_key`, legal category/status/lifecycle/
  denied behavior, route/API namespace rules, permission manifest drift,
  generic permission-key rejection, safe external dependencies, K01/P-series
  no-connect boundaries, n8n test bridge limits, non-executable module states,
  and C05/C06 permission regressions.
- Frontend module-isolation tests now cover navigation `module_key` binding,
  registry alignment, User Management as `admin.users`, Permission Management
  as `admin.permissions`, owner/non-owner access behavior, business
  `show_locked`, admin/system `hide_when_denied`, planned/adapter_pending/
  unavailable route decisions, `/modules/me` failure fallback, wildcard
  non-bypass, safe module notices, and C05D/C06C helper regressions.
- `frontend/scripts/verify-foundation.mjs` now verifies exact
  `GET /modules/registry` and `GET /modules/me` proxy allowlist entries,
  rejects broad `/modules/*` patterns, checks C07C helper/provider/test files,
  keeps C05/C06 permission proxy paths covered, and blocks default K01/P-series
  or live n8n/WooCommerce/MinIO/Filebrowser action markers.
- C07D does not add runtime features, backend APIs, frontend business UI,
  migrations, K01, P-series, real provider connections, staging release, or
  production release.

C07E has released the C07B/C07C runtime to staging and archived the acceptance
in `docs/C07_MODULE_STAGING_ACCEPTANCE.md`:

- Staging backend safe release completed for `console_staging_backend`.
- Staging frontend safe release completed for `console_staging_frontend`.
- No Alembic upgrade was executed, no staging/production postgres container was
  modified, no real env file was read, and production was not released.
- Staging unauthenticated `GET /modules/registry` and `GET /modules/me` return
  401.
- Staging frontend proxy precisely forwards `GET /api/backend/modules/registry`
  and `GET /api/backend/modules/me` to backend auth, while broad
  `/api/backend/modules/*` remains blocked.
- Staging frontend bundle contains C07C module-aware provider and route guard
  markers, including locked/no-permission and unavailable module states.
- C05/C06 unauthenticated regressions remain intact: `/auth/me`,
  `/permissions/me`, and `/users` return 401; `/auth/register` remains 404.
- The release did not connect K01, P-series, n8n, WooCommerce, MinIO,
  Filebrowser, Module Adapter, Execution Provider, or real business flows.
- Owner/non-owner live login requests were not executed because no approved
  staging owner credentials or active non-owner staging test account were
  available. The same access-state rules remain covered by the C07D Docker and
  frontend test suites.

C07F has released the C07B/C07C runtime to production and archived the
acceptance in `docs/C07_MODULE_PRODUCTION_RELEASE.md`:

- Production backend safe release completed for `console_backend`.
- Production frontend safe release completed for `console_frontend`.
- No Alembic upgrade was executed; production Alembic current/head remains
  `c05b_permissions_001 (head)`.
- Production postgres was not stopped, restarted, removed, rebuilt, exposed, or
  directly accessed.
- Production unauthenticated `GET /modules/registry` and `GET /modules/me`
  return 401.
- Production frontend proxy precisely forwards
  `GET /api/backend/modules/registry` and `GET /api/backend/modules/me` to
  backend auth, while `/api/backend/modules/not-allowed` remains 404.
- Production frontend bundle contains C07C `ModuleAccessProvider`,
  module-aware navigation, namespaced `module_key` values, route guard, locked
  and unavailable module states.
- C05/C06 unauthenticated regressions remain intact: `/auth/me`,
  `/permissions/me`, and `/users` return 401; `/auth/register` remains 404.
- No staging release, env read, direct DB access, production test account,
  production assignment grant/update/revoke, K01/P-series menu, provider
  connection, or real business flow was performed.
- Owner/non-owner production live login requests were not executed because no
  approved production auth material was available. The same access-state rules
  remain covered by C07D tests and C07E staging acceptance.

C07G has sealed the full C07 module-isolation system in
`docs/C07_MODULE_ISOLATION_SEAL.md`:

- C07A-F are complete and traceable from plan, backend registry, frontend
  isolation, verification, staging acceptance, production release, and final
  seal.
- The production backend module registry and production frontend
  module-aware navigation / route guard are the sealed C07 runtime state.
- `/modules/registry` and `/modules/me` require login and return 401 when
  unauthenticated.
- `/api/backend/modules/registry` and `/api/backend/modules/me` remain exact
  frontend proxy allowlist entries; broad `/modules/*` proxying remains
  prohibited.
- Business modules remain `show_locked` / locked when denied; admin/system
  modules remain `hide_when_denied` / hidden when denied.
- User Management and Permission Management remain owner-only, `/users`
  remains backend owner-only, and `/auth/register` remains 404.
- C07 is sealed without K01, P-series, n8n, WooCommerce, MinIO, Filebrowser,
  Module Adapter, Execution Provider, sandbox, module switch, approval gate,
  secret rules, new APIs, new UI, new migrations, or real business tasks.

## C08 module adapter

C08A has started Module Adapter planning in
`docs/C08_MODULE_ADAPTER_PLAN.md`. C08A is a docs-only audit and contract
design stage. It does not implement backend runtime code, frontend runtime
code, API, UI, migration, staging release, production release, Execution
Provider, module sandbox, module switch, approval gate, secret rules, n8n
integration, K01, P-series, or real business workflows.

C08 defines how future modules formally hand pages, routes, navigation
bindings, capabilities, actions, status, health, data contracts, permissions,
operation-log bindings, dependency declarations, and unavailable behavior to
the console. C08 builds on C07 Module Manifest / Registry but does not replace
it:

- Module Manifest says who the module is, where its route/API boundary is,
  what permissions it declares, and what status it has.
- Module Adapter says how that module exposes console surfaces and contracts.
- C08 declares action contracts only; C09 Execution Provider will execute
  actions later.
- C08 declares feature-flag/module-switch bindings only; C13 will implement
  module enable/disable later.
- C08 declares `scope_bindings` as pending only; C18 will define formal
  company/factory/department/organization scope.
- C08 declares dependency needs such as n8n, WooCommerce, MinIO, Filebrowser,
  AI provider, SERP, WeCom, or Google Sheets by safe dependency name only. It
  does not store or read URLs, tokens, credentials, or real env values.

C08A confirms K01 is a future business module, not C08. K01 may later provide
a Module Adapter in `adapter_pending` state, but C08A does not develop K01 and
does not modify the K-series worktree. P-series workflows are n8n workflows,
not C08; they may later enter through action/execution capability after C09
and C15, but C08A does not read or modify P-series workflow JSON.

C08B has added the backend Module Adapter contract and static adapter registry
documented in `docs/C08_MODULE_ADAPTER_BACKEND.md`:

- Static code-only adapter contracts in `backend/app/core/module_adapters.py`;
  no new database table and no migration.
- Adapter schema and access-state responses in
  `backend/app/schemas/module_adapter.py`.
- Central validation and current-user adapter access-state logic in
  `backend/app/services/module_adapter_registry.py`.
- Authenticated `GET /module-adapters/registry` for safe adapter metadata.
- Authenticated `GET /module-adapters/me` for owner/non-owner adapter access
  state based on C07 modules and C05/C06 effective permissions.
- Initial adapters are `core.dashboard.adapter`, `admin.users.adapter`,
  `admin.permissions.adapter`, `business.products.placeholder.adapter`, and
  `integration.n8n_test_bridge.adapter`.
- `business.products.placeholder.adapter` and
  `integration.n8n_test_bridge.adapter` remain `adapter_pending`, unavailable,
  and not executable.
- Dependency declarations are safe names only; the n8n test bridge declares
  only `n8n` with no live connection.
- C08B adds no frontend UI, no migration, no action execution endpoint, no
  Execution Provider, no Module Switch, no K01/P-series runtime, and no live
  n8n/WooCommerce/MinIO/Filebrowser integration.

C08C has added the frontend adapter rendering shell documented in
`docs/C08_MODULE_ADAPTER_FRONTEND.md`:

- Frontend Module Adapter types, normalizers, and no-execute helpers in
  `frontend/src/lib/module-adapter.ts`.
- Adapter registry API client in `frontend/src/lib/module-adapter-api.ts`,
  calling only `GET /module-adapters/registry` and `GET /module-adapters/me`
  through the restricted frontend backend proxy.
- `AdapterAccessProvider` and hooks alongside the C07 `ModuleAccessProvider`;
  C07 still owns module visibility, locked/hidden/unavailable state, and route
  guard behavior.
- `AdapterSurfaceShell` displays adapter status, supported surfaces, pages /
  nav / route / api bindings, capabilities, action contracts, data/input/output
  contracts, and safe dependency names.
- Action contracts are displayed only as disabled declarations. They show
  `Execution Provider not connected`, wait for C09 Execution Provider, and
  approval-required actions wait for C12 Approval Gate.
- The proxy precisely allows only `GET /module-adapters/registry` and
  `GET /module-adapters/me`; `/module-adapters/*` broad wildcard paths remain
  blocked.
- `tests/frontend/module-adapter.test.mjs` and
  `frontend/scripts/verify-foundation.mjs` cover adapter proxy, no-execute,
  no-secret dependency display, admin/system hiding on access unknown, business
  locked state, and C05/C06/C07 regressions.
- C08C adds no backend API, no migration, no action execution, no Execution
  Provider, no Approval Gate, no Module Switch, no K01/P-series runtime, and no
  live n8n/WooCommerce/MinIO/Filebrowser integration.

C08D has added the Adapter contract verify/test system documented in
`docs/C08_MODULE_ADAPTER_VERIFICATION.md`:

- Backend adapter tests now cover Module Adapter v1 required fields, unique
  and valid `adapter_key`, legal version/status/lifecycle/surfaces, C07 module
  binding, route/API/nav namespace boundaries, action contract permission/risk/
  operation-log requirements, execution/approval no-execute behavior, safe
  dependency/status/health/data contracts, pending scope bindings, K01/P-series
  no-enable boundaries, live provider bans, and C05/C06/C07 API regressions.
- Frontend adapter tests now cover exact adapter proxy allowlisting, no broad
  `/module-adapters/*` wildcard, adapter helper/provider/shell/API client
  presence, no-execute helper behavior, `available_actions` safe downgrade,
  execution-required actions waiting for C09, approval-required actions waiting
  for C12, safe dependency display, owner/non-owner metadata behavior, and
  C05/C06/C07 regressions.
- `frontend/scripts/verify-foundation.mjs` now checks C08D no-mutation/no-live
  boundaries: adapter API client cannot POST/PUT/PATCH/DELETE, adapter shell
  cannot create fetch/action execution calls, and live n8n/WooCommerce/MinIO/
  Filebrowser action/provider markers remain blocked.
- C08D adds no runtime feature, no backend API, no frontend business UI, no
  migration, no Execution Provider, no Approval Gate, no Module Switch, no
  K01/P-series runtime, no live provider integration, and no staging/production
  release.

C08E has released the C08B backend adapter registry and C08C frontend adapter
shell to staging and archived the acceptance in
`docs/C08_MODULE_ADAPTER_STAGING_ACCEPTANCE.md`:

- staging backend safe release completed for `console_staging_backend`; C08B
  `/module-adapters/registry` and `/module-adapters/me` are now present in
  staging and return 401 when unauthenticated.
- staging frontend safe release completed for `console_staging_frontend`; the
  frontend proxy precisely allows `/api/backend/module-adapters/registry` and
  `/api/backend/module-adapters/me`, both returning backend auth 401, while
  `/api/backend/module-adapters/not-allowed` returns 404.
- the staging frontend bundle contains C08C adapter shell markers including
  `AdapterAccessProvider`, adapter API paths, `Action contracts`, C09
  Execution Provider wait text, and C12 Approval Gate wait text.
- C08E did not execute Alembic upgrade, did not operate staging/production
  postgres, did not read real env files, did not publish production, did not
  create accounts or mutate permission assignments, and did not execute
  adapter actions.
- owner and non-owner live adapter access checks were not run because no
  approved staging auth material was provided; backend Docker tests and
  frontend Node tests cover those access-state contracts.

C08F has released the C08B backend adapter registry and C08C frontend adapter
shell to production and archived the acceptance in
`docs/C08_MODULE_ADAPTER_PRODUCTION_RELEASE.md`:

- production backend safe release completed for `console_backend`; production
  `GET /module-adapters/registry` and `GET /module-adapters/me` now return 401
  when unauthenticated.
- production frontend safe release completed for `console_frontend`; the proxy
  precisely allows `/api/backend/module-adapters/registry` and
  `/api/backend/module-adapters/me`, both returning 401 unauthenticated, while
  `/api/backend/module-adapters/not-allowed` returns 404.
- the production frontend bundle contains C08C adapter shell markers including
  `AdapterAccessProvider`, adapter API paths, `Action contracts`, C09
  Execution Provider wait text, C12 Approval Gate wait text, and dependency
  safety helper markers.
- C08F did not execute Alembic upgrade; production current/heads remain
  `c05b_permissions_001 (head)`.
- C08F did not operate production/staging postgres, did not read real env files,
  did not create accounts or mutate permission assignments, did not execute
  adapter actions, did not publish staging, and did not connect K01/P-series or
  live n8n/WooCommerce/MinIO/Filebrowser providers.
- owner and non-owner live adapter access checks were not run because no
  approved production auth material was provided; backend Docker tests and
  frontend Node tests cover those access-state contracts.

C08G has sealed the full C08 Module Adapter system in
`docs/C08_MODULE_ADAPTER_SEAL.md`:

- C08A-F are complete and traceable from plan, backend registry/contract,
  frontend shell/placeholders, verification, staging acceptance, production
  release, and final seal.
- The sealed production runtime state is authenticated read-only
  `/module-adapters/registry` and `/module-adapters/me`, exact frontend proxy
  allowlisting, and a contract-only adapter shell.
- Adapter actions remain non-executable; execution-required actions wait for
  C09 Execution Provider and approval-required actions wait for C12 Approval
  Gate.
- `/users` remains owner-only, `/auth/register` remains 404,
  `role_default_permissions` do not auto-apply, and `super_admin` is not
  global by default.
- C08 is sealed without K01, P-series, n8n/WooCommerce/MinIO/Filebrowser live
  providers, real business tasks, new migrations, runtime changes, staging or
  production release in C08G, or adapter action execution.

Current next split after C08G:

- C09: Execution Provider. C09A has started as docs-only audit and contract
  planning in `docs/C09_EXECUTION_PROVIDER_PLAN.md`.

## C09 execution provider

C09A has started Execution Provider planning in
`docs/C09_EXECUTION_PROVIDER_PLAN.md`. C09A is a docs-only audit and contract
design stage. It does not implement backend runtime code, frontend runtime
code, API, UI, migration, queue, worker, webhook execution, n8n execution,
Approval Gate, Module Switch, Secret Rules, formal scope, staging release,
production release, adapter action execution, live provider integration, or
real business workflows.

C09 defines how a C08 adapter action becomes a safe execution request. C08
answers what a module can declare; C09 answers how one action request is
submitted, permission-checked, blocked, accepted, queued, executed, logged,
timed out, cancelled, retried, summarized, and archived.

C09A confirms:

- C08 Module Adapter is sealed at `17b371a`.
- C08 action contracts remain declaration-only.
- C09A does not execute adapter actions.
- high-risk and approval-required actions must wait for C12 Approval Gate.
- secret-bearing providers must wait for C14 Secret Rules.
- n8n live provider integration must wait for C15.
- C18 remains responsible for formal company/factory/department scope.

Execution Provider Contract v1 is planned to cover provider identity/status,
supported execution modes, module/adapter/action binding, request/result/state
schemas, inherited required permission/risk/operation log action, approval and
secret requirements, scope placeholder rules, idempotency, retry, cancel,
timeout, concurrency, rate limit, operation log, audit event, artifact,
callback, failure, fallback, unavailable behavior, tests, and docs path.

C09B has added the backend Execution Provider contract and static no-op
provider registry documented in `docs/C09_EXECUTION_PROVIDER_BACKEND.md`:

- Backend schema now defines `ExecutionProviderContractV1`, Execution Request /
  Result / State contract schemas, safe registry output, and current-user
  provider access state.
- Static registry now declares `core.no_op_provider`, `core.mock_provider`,
  `core.contract_only_provider`, and future local/queue/webhook/scheduled/live
  provider placeholders.
- New authenticated read-only APIs are `GET /execution-providers/registry` and
  `GET /execution-providers/me`.
- Provider action binding must match C08 `action_contract` `module_key`,
  `adapter_key`, `action_key`, `required_permission`, `risk_level`, and
  `operation_log_action`.
- C09B returns permission/approval/secret/scope/provider blocking states, but
  every provider remains `executable=false` and `can_request_execution=false`.
- C09B adds no frontend UI, no migration, no execution submit API, no queue,
  no worker, no webhook execution, no live provider, no adapter action
  execution, and no real business task.

The recommended next step after C09B is C09C: frontend execution status shell /
action submit disabled state.

## Temporary login preview

Use a distinct example-only Compose project and shell-provided values. Do not
write or commit a real `.env`:

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

Open `http://127.0.0.1:3000/login`. When the temporary preview is finished,
stop the foreground process and remove only that named example project:

```bash
docker-compose -p "$COMPOSE_PROJECT_NAME" \
  -f docker-compose.example.yml down --volumes --remove-orphans
unset OWNER_PASSWORD AUTH_TOKEN_SECRET OWNER_USERNAME COMPOSE_PROJECT_NAME
```

`AUTH_TOKEN_SECRET`, `N8N_TEST_WEBHOOK_URL`, and
`N8N_TEST_CALLBACK_SECRET` are environment variables. Never commit real
values. Leave the n8n test variables empty for a login-only preview.

## F12 n8n test webhook bridge

F12 adds a test-only Console to n8n webhook loop:

`Test Job -> configured test webhook -> authenticated callback -> Job Events
-> demo Artifact -> demo Review -> demo Memory Event -> Operation Logs`

The protected **n8n Test Bridge** page at `/n8n-test` can create a test Job,
call only an explicitly test/demo-marked webhook, poll the latest result, and
show the Job status, latest event, demo records, and safe error summary. A
successful callback ends as `completed_demo`; failures end as `failed`.
Neither state represents real business completion.

Configure the bridge only through environment variables:

```bash
export N8N_TEST_WEBHOOK_URL="https://n8n-test.example.invalid/webhook-test/barong-demo"
read -r -s -p "Test callback value: " N8N_TEST_CALLBACK_SECRET
export N8N_TEST_CALLBACK_SECRET
export N8N_TEST_REQUEST_TIMEOUT_SECONDS=10
```

The webhook URL is empty by default. An empty URL, an URL not explicitly
marked test/demo, or a missing callback value fails safely before any network
request. The callback uses `X-Barong-Callback-Secret`; its value is never
returned to the frontend or stored in operation logs. The workflow registry
stores only a `demo://` reference, never the configured network URL.

This bridge does not trigger real P-series work or WooCommerce, does not
connect MinIO/Filebrowser, and does not create real products or business
tasks. Tests replace the HTTP sender with a fake and never call a network
webhook.

F12 APIs:

- `POST /n8n-test/run` (owner Bearer token)
- `POST /n8n-test/callback` (callback header authentication)
- `GET /n8n-test/latest` (owner Bearer token)

Run the complete isolated verification:

```bash
./scripts/test_backend_docker.sh
./scripts/test_backend_db_docker.sh
./scripts/test_frontend_docker.sh
docker-compose -f docker-compose.example.yml config
```

## F11 Foundation Demo closed loop

F11 adds an owner-only Foundation Demo exercise that validates the complete
console data path:

`Module -> Agent -> Workflow -> Job -> Job Events -> Artifact -> Review ->
Memory Event -> Operation Logs -> Frontend`

Use the protected **Foundation Demo** navigation page to run the exercise and
view the latest demo job ID/status, event count, artifact title, pending demo
review, memory summary, and related operation-log count.

The endpoint creates or reuses the fixed `foundation_demo` module,
`foundation_demo_agent`, and `foundation_demo_workflow`. Every run creates a
new pending demo job, records the six demo events, registers metadata-only
artifact and review records, writes a no-model memory event, and finishes only
as `completed_demo`. Registry records are not duplicated across runs.

This is an internal database exercise only. It does not call external HTTP,
trigger real n8n or P-series work, connect WooCommerce, upload to
MinIO/Filebrowser, or create a real business task. A failed run rolls back its
demo transaction and records a separate safe system error and failure
operation log.

F11 APIs:

- `POST /foundation-demo/run`
- `GET /foundation-demo/latest`

Both require an owner Bearer token. Run all isolated checks with:

```bash
./scripts/test_backend_docker.sh
./scripts/test_backend_db_docker.sh
./scripts/test_frontend_docker.sh
docker-compose -f docker-compose.example.yml config
```

## F10 foundation operations APIs

F10 adds owner-only, Bearer-authenticated foundation APIs over the existing
F07 tables:

- Module, Agent, and Workflow registry list/detail/demo-create endpoints.
- Job list/detail/demo-create endpoints and append-only job events with safe
  demo status changes.
- Artifact metadata, Review, System Error, Memory Event, and Context Packet
  foundation endpoints.
- Read-only Memory Summary and Operation Log endpoints.

Every F10 write records an `operation_logs` row in the same database
transaction. Operation Logs are an audit entry point and cannot be created,
changed, or deleted through the API. Requests reject credential-shaped
structured fields, real network endpoint references, real completion status,
and non-demo review decisions.

These APIs do not execute workflows, call models, connect WooCommerce, upload
to MinIO/Filebrowser, or create real business jobs. Workflow and Artifact
records are metadata only. The frontend Modules, Agents, Workflows, Jobs,
Artifacts, Reviews, Errors, and Memory Events pages now read their real API
lists and show loading, API error, empty, or simple record states. Products
still has no product creation integration, and Settings remains an empty
foundation page.

Run the isolated backend and frontend checks with:

```bash
./scripts/test_backend_docker.sh
./scripts/test_backend_db_docker.sh
./scripts/test_frontend_docker.sh
docker-compose -f docker-compose.example.yml config
```

## F09 frontend shell and login

F09 adds the Next.js / React / TypeScript frontend shell on top of the F08
backend authentication foundation:

- Public `/login` page with username and password fields.
- Login through `POST /auth/login`, current-user validation through
  `GET /auth/me`, and logout through `POST /auth/logout`.
- Access-token storage without URL or console output, plus centralized 401
  handling that clears invalid login state.
- Protected Dashboard, Products, Modules, Agents, Workflows, Jobs, Artifacts,
  Reviews, Errors, Memory Events, and Settings routes.
- Sidebar navigation, current username and role display, logout control, and
  structured empty states without fabricated business records.

The first version has no public registration page or registration API call.
Every console page except `/login` is protected by the frontend authentication
guard; backend APIs remain responsible for their own authentication and
authorization.

F09 still does not connect real business modules, P-series workflows, n8n,
WooCommerce, MinIO, or Filebrowser. The frontend authentication proxy only
allows the three F08 authentication endpoints and does not expose a generic
business API proxy.

Use only the example backend URL in local configuration:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

The example Compose frontend uses `BACKEND_API_URL=http://backend:8000` for
server-side container networking. These URLs contain no credentials. Do not
create or commit a real `.env`.

Build and verify the frontend entirely in Docker:

```bash
./scripts/test_frontend_docker.sh
```

The Docker build installs the locked dependencies in its isolated build stage,
checks all required routes and prohibited registration references, runs
TypeScript, and completes a production Next.js build. It does not install npm
packages on the host.

Start the example frontend, backend, and example-only database with:

```bash
export AUTH_TOKEN_SECRET="replace-with-an-example-only-value-at-least-32-bytes"
docker-compose -f docker-compose.example.yml up --build db backend frontend
```

Initialize the example database and owner using the F08 migration and bootstrap
instructions below before testing login. Never use production credentials,
databases, paths, or external services with this Compose file.

## F08 backend authentication foundation

The current backend includes the F05 FastAPI foundation, the F06 PostgreSQL /
SQLAlchemy / Alembic migration foundation, and the F07 core foundation tables.
F08 adds the minimum backend authentication foundation:

- Argon2id password hashing and verification.
- Controlled, idempotent initialization of the first active `owner`.
- JWT login tokens with configured expiration.
- `POST /auth/login`, `POST /auth/logout`, and `GET /auth/me`.
- Authentication operation logs for owner initialization, login, and logout.

The first version intentionally has no public registration endpoint. F08 does
not add business APIs or connect real n8n, WooCommerce, Filebrowser, MinIO, or
other external services.

Do not install project dependencies into the server's system Python and do
not create a virtual environment for these checks. Run the health test in the
isolated Docker example environment:

```bash
./scripts/test_backend_docker.sh
```

Run the database, migration, security, authentication, and owner bootstrap
checks with:

```bash
./scripts/test_backend_db_docker.sh
```

This second script uses only `docker-compose.example.yml`. It starts an
ephemeral example PostgreSQL service, tests the F08 authentication flow,
executes `alembic upgrade head`, `alembic downgrade base`, and
`alembic upgrade head` again, then runs `alembic check`. The script removes
the isolated test containers, volume, and network when it exits.

## Initialize the example owner

Set the owner credentials in the current shell without writing a real `.env`
file, then run the example-only bootstrap script:

```bash
export OWNER_USERNAME="choose-an-owner-name"
read -r -s -p "Owner password: " OWNER_PASSWORD
export OWNER_PASSWORD
./scripts/bootstrap_owner_docker.sh
unset OWNER_PASSWORD
```

The script builds and uses only `docker-compose.example.yml`, migrates the
example PostgreSQL database, and creates at most one active `owner`. Running
it again safely records a skipped bootstrap. It never prints the password.

`AUTH_TOKEN_SECRET` must be at least 32 bytes before the authentication API
can issue or validate tokens. Pass it into an example backend container
without committing it:

```bash
read -r -s -p "Token signing value: " AUTH_TOKEN_SECRET
export AUTH_TOKEN_SECRET
docker compose -p barong-ops-console-example \
  -f docker-compose.example.yml run --rm --service-ports \
  -e AUTH_TOKEN_SECRET backend \
  python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Do not commit a real `.env` file. Values in `.env.example` are placeholders;
the example token signing value and owner password must never be used in
production.

Equivalent Alembic commands inside the example backend container are:

```bash
docker compose -f docker-compose.example.yml run --rm backend \
  python -m alembic -c backend/alembic.ini upgrade head
docker compose -f docker-compose.example.yml run --rm backend \
  python -m alembic -c backend/alembic.ini downgrade base
docker compose -f docker-compose.example.yml run --rm backend \
  python -m alembic -c backend/alembic.ini upgrade head
docker compose -f docker-compose.example.yml run --rm backend \
  python -m alembic -c backend/alembic.ini check
```

Start the example backend with:

```bash
docker compose -f docker-compose.example.yml up --build backend
```

The example configuration is separate from production Compose files and uses
only clearly marked example database credentials, with no production mounts
or external services. Never point these migrations at a production
database and never commit a real `.env` file.

`GET /health` remains anonymous and continues to report
`database: "not_configured"` because it does not claim a live database
readiness check. The authentication endpoints use the database, while real
business integrations remain intentionally absent.
