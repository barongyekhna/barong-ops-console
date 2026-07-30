"""Aggregate router export for B2B modules."""

from fastapi import APIRouter

from .outreach.router import router as outreach_router
from .prospects.router import router as prospects_router
from .store_types.router import router as store_types_router
from .wholesale.router import router as wholesale_router

router = APIRouter()
router.include_router(wholesale_router)
router.include_router(prospects_router)
router.include_router(store_types_router)
router.include_router(outreach_router)

__all__ = ["router"]
