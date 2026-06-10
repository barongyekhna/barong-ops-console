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
sealed. C05A has started permissions / RBAC design.

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
OPS01 is complete. C05A has now started the permissions / RBAC stage with a
design-only audit and plan.

## C05 permission system

C05A starts the permission-system stage with
`docs/C05_PERMISSION_SYSTEM_PLAN.md`. C05B adds the backend permission data
model documented in `docs/C05_PERMISSION_DATA_MODEL.md`. C05C adds backend
permission access enforcement and current-user permission APIs documented in
`docs/C05_PERMISSION_BACKEND_ACCESS.md`. C05D adds frontend permission-aware
navigation, no-permission messaging, and lightweight route protection
documented in `docs/C05_PERMISSION_FRONTEND_ACCESS.md`.

C05 is about authorization, not business-module onboarding. It does not connect
real n8n, P-series, WooCommerce, MinIO, Filebrowser, product flows, orders, or
business tasks.

Current C05 status:

- C05A audits the existing auth, role, user-management, frontend navigation,
  and role-system tests/docs.
- C05B adds `permission_registry`, `user_permission_assignments`, and
  `role_default_permissions` with Alembic migration `c05b_permissions_001`.
- C05B adds the first permission registry seed source, idempotent registry
  upsert, assignment grant/disable/revoke helpers, role default permission
  storage, and base permission query services.
- C05C adds `require_permission()`, extends `GET /auth/me` with
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
- C05A defines Permission Registry, User Permission Assignment, Role Default
  Permissions, Permission Scope, and Module Permission Manifest concepts;
  C05B implements the first three as backend tables.
- Ordinary users receive permissions through manual assignment by owner or an
  authorized scoped super_admin.
- C05D does not add permission grant/revoke UI, does not replace `/users`
  `require_owner()`, does not deploy staging/production, and does not connect
  real business systems.
- User Management remains owner-only in both backend and frontend. C05D does
  not expose `/users` to `super_admin` or ordinary non-owner users with
  `users.manage`; changing `/users` to permission-based access must be C06 or
  a separate backend task.

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
