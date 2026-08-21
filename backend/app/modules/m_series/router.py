"""M 系列路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from .inventory.router import router as inventory_router

router = APIRouter()
router.include_router(inventory_router)
