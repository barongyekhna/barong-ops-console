"""Aggregate C19 control, external-record and external-asset JSON routes.

Message records and asset metadata remain behind separate fail-closed stores.
Moment content and images remain behind their fail-closed external stores.
"""

from fastapi import APIRouter, Depends

from .asset_router import router as asset_router
from .conversation_router import router as conversation_router
from .identity_social_router import router as identity_social_router
from .message_router import router as message_router
from .moment_router import router as moment_router
from .rate_limit import enforce_c19_rate_limit


router = APIRouter(dependencies=[Depends(enforce_c19_rate_limit)])
router.include_router(identity_social_router)
router.include_router(conversation_router)
router.include_router(message_router)
router.include_router(asset_router)
router.include_router(moment_router)


__all__ = ["router"]
