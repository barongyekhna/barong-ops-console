# Backend

This directory contains the F05 FastAPI foundation. It currently exposes only
`GET /health` and does not connect to a database or any external service.

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
docker compose -f docker-compose.example.yml run --rm backend python -m pytest tests/backend/test_health.py
```

The script falls back to the legacy `docker-compose` executable when the
Compose v2 plugin is unavailable.

## Run the example backend

```bash
docker compose -f docker-compose.example.yml up --build backend
```

The health endpoint is available at `http://127.0.0.1:8000/health`.
Database access, authentication, n8n, WooCommerce, and business modules are
not included.
