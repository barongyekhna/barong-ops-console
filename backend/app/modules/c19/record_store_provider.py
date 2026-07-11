"""Request-scoped C19 record-store construction and lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping

from .http_record_store import HttpChatRecordStore, HttpChatRecordStoreConfig
from .storage import (
    UNCONFIGURED_CHAT_RECORD_STORE,
    ChatRecordStore,
)


def build_chat_record_store(
    environ: Mapping[str, str] | None = None,
) -> ChatRecordStore:
    """Build a configured client or the explicit fail-closed implementation."""

    try:
        config = HttpChatRecordStoreConfig.from_environment(environ)
    except (TypeError, ValueError, OverflowError):
        return UNCONFIGURED_CHAT_RECORD_STORE
    if config is None:
        return UNCONFIGURED_CHAT_RECORD_STORE
    return HttpChatRecordStore(config)


async def get_chat_record_store() -> AsyncIterator[ChatRecordStore]:
    """FastAPI dependency that closes each owned async client deterministically."""

    store = build_chat_record_store()
    try:
        yield store
    finally:
        if isinstance(store, HttpChatRecordStore):
            await store.aclose()


__all__ = ["build_chat_record_store", "get_chat_record_store"]
