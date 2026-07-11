"""Aggregate router for C19 control metadata and external chat records.

Message records remain behind a fail-closed external-store contract.  Assets
and Moments are deliberately absent.
"""

from fastapi import APIRouter

from .conversation_router import router as conversation_router
from .identity_social_router import router as identity_social_router
from .message_router import router as message_router


router = APIRouter()
router.include_router(identity_social_router)
router.include_router(conversation_router)
router.include_router(message_router)


__all__ = ["router"]
