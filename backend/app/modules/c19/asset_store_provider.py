"""Request-scoped C19 asset-store construction and lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping

from .http_asset_store import HttpChatAssetStore, HttpChatAssetStoreConfig
from .storage import UNCONFIGURED_CHAT_ASSET_STORE, ChatAssetStore


def build_chat_asset_store(
    environ: Mapping[str, str] | None = None,
) -> ChatAssetStore:
    """Build a configured client or the explicit fail-closed implementation."""

    try:
        config = HttpChatAssetStoreConfig.from_environment(environ)
    except (TypeError, ValueError, OverflowError):
        return UNCONFIGURED_CHAT_ASSET_STORE
    if config is None:
        return UNCONFIGURED_CHAT_ASSET_STORE
    return HttpChatAssetStore(config)


async def get_chat_asset_store() -> AsyncIterator[ChatAssetStore]:
    store = build_chat_asset_store()
    try:
        yield store
    finally:
        if isinstance(store, HttpChatAssetStore):
            await store.aclose()


__all__ = ["build_chat_asset_store", "get_chat_asset_store"]
