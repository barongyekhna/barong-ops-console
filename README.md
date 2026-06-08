# Barong Ops Console

Barong Ops Console is the control-panel foundation for the Barong Yekhna independent-site automation operating system.

This project must be built as an independent containerized console and must not modify existing production n8n, Filebrowser, MinIO, WooCommerce, or legacy Baisuwan containers directly.

Core rule:
- Build the empty foundation first.
- Add business modules one by one.
- Every module must be registered, isolated, testable, and removable.

## F06 database migration foundation

The current backend includes the F05 FastAPI foundation and the F06
PostgreSQL / SQLAlchemy / Alembic migration foundation. F06 provides only
database configuration, an empty SQLAlchemy metadata registry, Alembic
configuration, and an example-only PostgreSQL service.

F06 does not create any core business tables or migration revisions. The core
tables defined by the reviewed schema are reserved for F07.

Do not install project dependencies into the server's system Python and do
not create a virtual environment for these checks. Run the health test in the
isolated Docker example environment:

```bash
./scripts/test_backend_docker.sh
```

Run the F06 database and Alembic skeleton checks with:

```bash
./scripts/test_backend_db_docker.sh
```

This second script uses only `docker-compose.example.yml`. It starts an
ephemeral example PostgreSQL service, runs `alembic current`,
`alembic upgrade head`, `alembic check`, and the backend configuration tests,
then removes the isolated test containers. The Alembic commands operate on
empty metadata and therefore create no business tables.

Equivalent Alembic commands inside the example backend container are:

```bash
docker compose -f docker-compose.example.yml run --rm backend \
  python -m alembic -c backend/alembic.ini current
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
or external services. Never point this migration skeleton at a production
database and never commit a real `.env` file.

The backend still exposes only `GET /health`. The endpoint currently reports
`database: "not_configured"` and does not test or claim a live database
connection. Authentication, external integrations, business APIs, business
models, and core tables remain intentionally absent.
