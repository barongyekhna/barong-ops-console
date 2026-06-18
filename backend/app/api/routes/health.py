from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()

LIGHTWEIGHT_HEALTH_ENDPOINTS = frozenset(
    (
        "/health",
        "/api/backend/health",
        "/api/public/health",
    )
)
LIGHTWEIGHT_HEALTH_CONTENT = {
    "status": "ok",
    "service": "barong-ops-console",
    "mode": "lightweight",
    "db": "not_checked",
}


class HealthResponse(BaseModel):
    status: str
    service: str
    mode: str
    db: str


def is_lightweight_health_path(path: str) -> bool:
    return path in LIGHTWEIGHT_HEALTH_ENDPOINTS


def lightweight_health_payload() -> dict[str, str]:
    return dict(LIGHTWEIGHT_HEALTH_CONTENT)


def lightweight_health_response() -> JSONResponse:
    return JSONResponse(content=lightweight_health_payload())


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(**lightweight_health_payload())
