from fastapi import FastAPI

from .api.routes.auth import router as auth_router
from .api.routes.health import router as health_router
from .core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)
app.include_router(health_router)
app.include_router(auth_router)
