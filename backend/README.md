# Backend

This directory contains the F05 FastAPI foundation, the F06 database migration
foundation, and the F07 core foundation table models and migration. It
currently exposes only `GET /health`.

F07 adds:

- SQLAlchemy models for all 14 reviewed core foundation tables.
- PostgreSQL JSONB-backed structured fields through portable SQLAlchemy types.
- Primary keys, stable business ID uniqueness, required status fields,
  timestamps, and the core tracing foreign keys.
- One Alembic revision that creates and removes the empty tables.

F07 includes no data seed, owner initialization, password handling, login,
authentication API, business API, frontend, or real external integration. F08
is responsible for controlled owner initialization and authentication basics.

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

Run the isolated PostgreSQL schema and Alembic checks with:

```bash
./scripts/test_backend_db_docker.sh
```

This uses only the example Compose file and example credentials. It runs
schema tests and verifies migration upgrade, downgrade, and a second upgrade.
Do not point `DATABASE_URL` at a production database. Do not install the
requirements in the system Python or commit a real `.env` file.

## Run the example backend

```bash
docker compose -f docker-compose.example.yml up --build backend
```

The health endpoint is available at `http://127.0.0.1:8000/health`.
It continues to report `database: "not_configured"` and does not perform a
database connectivity check. Authentication, external integrations, business
APIs, frontend code, owner initialization, and business modules are not
included.
