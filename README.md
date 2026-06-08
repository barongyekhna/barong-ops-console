# Barong Ops Console

Barong Ops Console is the control-panel foundation for the Barong Yekhna independent-site automation operating system.

This project must be built as an independent containerized console and must not modify existing production n8n, Filebrowser, MinIO, WooCommerce, or legacy Baisuwan containers directly.

Core rule:
- Build the empty foundation first.
- Add business modules one by one.
- Every module must be registered, isolated, testable, and removable.

## F07 core foundation tables

The current backend includes the F05 FastAPI foundation, the F06 PostgreSQL /
SQLAlchemy / Alembic migration foundation, and the F07 core foundation tables.
F07 adds SQLAlchemy models and one Alembic revision for the 14 reviewed tables:
users, the Module / Agent / Workflow registries, Jobs and Job Events,
Artifacts, Reviews, Errors, Memory records, Operation Logs, and Context
Packets.

These tables contain schema and constraints only. F07 does not initialize an
owner, implement authentication or login, add business APIs, add frontend
code, seed real data, or connect any real business or external service. F08
will add controlled owner initialization and the authentication foundation.

Do not install project dependencies into the server's system Python and do
not create a virtual environment for these checks. Run the health test in the
isolated Docker example environment:

```bash
./scripts/test_backend_docker.sh
```

Run the F07 schema and Alembic migration checks with:

```bash
./scripts/test_backend_db_docker.sh
```

This second script uses only `docker-compose.example.yml`. It starts an
ephemeral example PostgreSQL service, runs the backend schema tests, executes
`alembic upgrade head`, `alembic downgrade base`, and `alembic upgrade head`
again, then runs `alembic check`. The script removes the isolated test
containers, volume, and network when it exits.

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

The backend still exposes only `GET /health`. The endpoint currently reports
`database: "not_configured"` and does not test or claim a live database
connection. Authentication APIs, login, business APIs, frontend code, owner
initialization, and real business integrations remain intentionally absent.
