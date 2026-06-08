# Backend

This directory contains the F05 FastAPI foundation, the F06 database migration
foundation, the F07 core tables, and the F08 backend authentication
foundation, plus the F10 foundation operations APIs.

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

There is no registration API, frontend login page, complex permission matrix,
seed data, or real external integration.

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
security, authentication, F10 API, audit, and external-boundary tests and
verifies migration upgrade, downgrade, and a second upgrade. Do not point
`DATABASE_URL` at a production database.
Do not install the requirements in the system Python or commit a real `.env`
file.

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

## Run the example backend

```bash
docker compose -f docker-compose.example.yml up --build backend
```

The health endpoint is available at `http://127.0.0.1:8000/health`.
It continues to report `database: "not_configured"` and does not perform a
database connectivity check. The authenticated F10 endpoints use the example
database, while real external integrations and business modules remain absent.
