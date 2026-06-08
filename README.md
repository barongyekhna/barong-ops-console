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

Install the Python dependencies and run the test from the repository root:

```bash
python3 -m pip install -r backend/requirements.txt
python3 -m pytest tests/backend/test_health.py
```

Start the backend locally:

```bash
PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Alternatively, use the isolated example Compose configuration:

```bash
docker compose -f docker-compose.example.yml up --build backend
```
