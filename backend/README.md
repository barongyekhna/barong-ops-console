# Backend

This directory contains the F05 FastAPI foundation. It currently exposes only
`GET /health` and does not connect to a database or any external service.

## Run locally

From the repository root:

```bash
python3 -m venv /tmp/barong-ops-console-venv
source /tmp/barong-ops-console-venv/bin/activate
python3 -m pip install -r backend/requirements.txt
PYTHONPATH=backend uvicorn app.main:app --reload
```

The health endpoint is available at `http://127.0.0.1:8000/health`.
