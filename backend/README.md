# Backend

This directory contains the F05 FastAPI foundation and the F06 database
migration foundation. It currently exposes only `GET /health`.

F06 adds:

- An example-only `DATABASE_URL` setting.
- Empty SQLAlchemy metadata, engine, and session factory configuration.
- An Alembic environment targeting that empty metadata.
- No models, business tables, or migration revisions.

Core business tables remain reserved for F07.

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

Run the isolated PostgreSQL and Alembic skeleton checks with:

```bash
./scripts/test_backend_db_docker.sh
```

This uses only the example Compose file and example credentials. Do not point
`DATABASE_URL` at a production database. Do not install the requirements in
the system Python or commit a real `.env` file.

## Run the example backend

```bash
docker compose -f docker-compose.example.yml up --build backend
```

The health endpoint is available at `http://127.0.0.1:8000/health`.
It continues to report `database: "not_configured"` and does not perform a
database connectivity check. Authentication, external integrations, business
models, and business modules are not included.
