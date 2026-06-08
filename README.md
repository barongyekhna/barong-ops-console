# Barong Ops Console

Barong Ops Console is the control-panel foundation for the Barong Yekhna independent-site automation operating system.

This project must be built as an independent containerized console and must not modify existing production n8n, Filebrowser, MinIO, WooCommerce, or legacy Baisuwan containers directly.

Core rule:
- Build the empty foundation first.
- Add business modules one by one.
- Every module must be registered, isolated, testable, and removable.

## F08 backend authentication foundation

The current backend includes the F05 FastAPI foundation, the F06 PostgreSQL /
SQLAlchemy / Alembic migration foundation, and the F07 core foundation tables.
F08 adds the minimum backend authentication foundation:

- Argon2id password hashing and verification.
- Controlled, idempotent initialization of the first active `owner`.
- JWT login tokens with configured expiration.
- `POST /auth/login`, `POST /auth/logout`, and `GET /auth/me`.
- Authentication operation logs for owner initialization, login, and logout.

The first version intentionally has no public registration endpoint. F08 also
does not add a frontend login page; that work remains in F09. It does not add
business APIs or connect real n8n, WooCommerce, Filebrowser, MinIO, or other
external services.

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
business integrations and frontend code remain intentionally absent.
