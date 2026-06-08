# Barong Ops Console

Barong Ops Console is the control-panel foundation for the Barong Yekhna independent-site automation operating system.

This project must be built as an independent containerized console and must not modify existing production n8n, Filebrowser, MinIO, WooCommerce, or legacy Baisuwan containers directly.

Core rule:
- Build the empty foundation first.
- Add business modules one by one.
- Every module must be registered, isolated, testable, and removable.

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
