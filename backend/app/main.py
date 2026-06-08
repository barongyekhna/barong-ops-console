from fastapi import FastAPI

from .api.routes.agents import router as agents_router
from .api.routes.artifacts import router as artifacts_router
from .api.routes.auth import router as auth_router
from .api.routes.errors import router as errors_router
from .api.routes.health import router as health_router
from .api.routes.jobs import router as jobs_router
from .api.routes.memory import router as memory_router
from .api.routes.modules import router as modules_router
from .api.routes.operation_logs import router as operation_logs_router
from .api.routes.reviews import router as reviews_router
from .api.routes.workflows import router as workflows_router
from .core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(modules_router)
app.include_router(agents_router)
app.include_router(workflows_router)
app.include_router(jobs_router)
app.include_router(artifacts_router)
app.include_router(reviews_router)
app.include_router(errors_router)
app.include_router(memory_router)
app.include_router(operation_logs_router)
