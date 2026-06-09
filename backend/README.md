# Backend

This directory contains the F05 FastAPI foundation, F06 migration mechanism,
F07 core tables, F08 owner authentication, F10 foundation APIs, F11
Foundation Demo, and F12 n8n Test Bridge. F13 accepts this backend as an empty
foundation; it does not add a real business integration.

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

C02B prepares the staging/test construction files only. Staging uses
`console_staging_backend`, `console_staging_postgres`,
`barong-ops-console-staging`, `console_staging_postgres_data`, and server-local
`.env.staging`. Its `DATABASE_URL` must point at
`console_staging_postgres:5432`, `AUTH_TOKEN_SECRET` and `POSTGRES_PASSWORD`
must be different from production, and the staging owner must be a test
account. C02B does not create `.env.staging`, start staging, or connect real
n8n, P-series, WooCommerce, MinIO, or Filebrowser systems.

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
authentication, and authentication operation logs. It exposes:

- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`

F08 itself did not add a frontend login page; F09 added that page later.
There is still no registration API, complex permission matrix, seed data, or
real external integration.

F10 adds owner-only list/detail APIs and controlled foundation/demo writes for
Modules, Agents, Workflows, Jobs, Job Events, Artifacts, Reviews, System
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
`upgrade head`, and `alembic check`. The accepted foundation has one migration:
`f07_core_001`. F13 adds no migration or dependency.

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
