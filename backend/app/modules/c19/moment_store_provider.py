"""Request-scoped construction for Stage 5 Moment record/asset ports."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import cast

from .http_asset_store import HttpChatAssetStore, HttpChatAssetStoreConfig
from .http_record_store import HttpChatRecordStore, HttpChatRecordStoreConfig
from .moment_storage import (
    MomentAssetStore,
    MomentStore,
    UNCONFIGURED_MOMENT_ASSET_STORE,
    UNCONFIGURED_MOMENT_STORE,
)


def build_moment_store(
    environ: Mapping[str, str] | None = None,
) -> MomentStore:
    try:
        config = HttpChatRecordStoreConfig.from_environment(environ)
    except (TypeError, ValueError, OverflowError):
        return UNCONFIGURED_MOMENT_STORE
    if config is None:
        return UNCONFIGURED_MOMENT_STORE
    return cast(MomentStore, HttpChatRecordStore(config))


def build_moment_asset_store(
    environ: Mapping[str, str] | None = None,
) -> MomentAssetStore:
    try:
        config = HttpChatAssetStoreConfig.from_environment(environ)
    except (TypeError, ValueError, OverflowError):
        return UNCONFIGURED_MOMENT_ASSET_STORE
    if config is None:
        return UNCONFIGURED_MOMENT_ASSET_STORE
    return cast(MomentAssetStore, HttpChatAssetStore(config))


async def get_moment_store() -> AsyncIterator[MomentStore]:
    store = build_moment_store()
    try:
        yield store
    finally:
        if isinstance(store, HttpChatRecordStore):
            await store.aclose()


async def get_moment_asset_store() -> AsyncIterator[MomentAssetStore]:
    store = build_moment_asset_store()
    try:
        yield store
    finally:
        if isinstance(store, HttpChatAssetStore):
            await store.aclose()


__all__ = [
    "build_moment_asset_store",
    "build_moment_store",
    "get_moment_asset_store",
    "get_moment_store",
]
