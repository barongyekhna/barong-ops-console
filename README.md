# Barong Ops Console

Barong Ops Console is the control-panel foundation for the Barong Yekhna independent-site automation operating system.

This project must be built as an independent containerized console and must not modify existing production n8n, Filebrowser, MinIO, WooCommerce, or legacy Baisuwan containers directly.

Core rule:
- Build the empty foundation first.
- Add business modules one by one.
- Every module must be registered, isolated, testable, and removable.

## F05 backend foundation

The current backend is a minimal FastAPI foundation that provides only
`GET /health`. It does not include database access, authentication, external
service integrations, or business modules.

Run backend tests in the isolated Docker example environment. Do not install
the project dependencies into the server's system Python:

```bash
./scripts/test_backend_docker.sh
```

The script builds only the `backend` service from
`docker-compose.example.yml`, then runs the Compose v2 command below. It also
supports the legacy `docker-compose` command when Compose v2 is unavailable:

```bash
docker compose -f docker-compose.example.yml run --rm backend python -m pytest tests/backend/test_health.py
```

Start the example backend with:

```bash
docker compose -f docker-compose.example.yml up --build backend
```

The example configuration is separate from production Compose files and uses
no real secrets or production mounts. The backend still exposes only
`GET /health`; database, authentication, n8n, and WooCommerce integrations
remain intentionally absent.
