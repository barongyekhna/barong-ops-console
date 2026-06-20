from __future__ import annotations

import copy
import logging
import os
from collections import OrderedDict
from collections.abc import Hashable
from threading import Lock
from typing import Any

from fastapi import HTTPException, Request, status
from pydantic import BaseModel

from ..schemas.common import ApiErrorInfo

MAX_API_SNAPSHOTS = 256


class _ApiSnapshotCache:
    def __init__(self) -> None:
        self._values: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = Lock()

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            value = self._values.get(key)
            if value is None:
                return None
            self._values.move_to_end(key)
            return _clone(value)

    def set(self, key: Hashable, value: Any) -> None:
        snapshot = _clone(value)
        with self._lock:
            self._values[key] = snapshot
            self._values.move_to_end(key)
            while len(self._values) > MAX_API_SNAPSHOTS:
                self._values.popitem(last=False)


_SNAPSHOTS = _ApiSnapshotCache()


def _clone(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_copy(deep=True)
    return copy.deepcopy(value)


def api_snapshot_key(namespace: str, *parts: object) -> tuple[object, ...]:
    return (namespace, os.environ.get("PYTEST_CURRENT_TEST", ""), *parts)


def save_api_snapshot(key: Hashable, value: Any) -> None:
    _SNAPSHOTS.set(key, value)


def get_api_snapshot(key: Hashable) -> Any | None:
    return _SNAPSHOTS.get(key)


def request_id_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    value = getattr(request.state, "context_id", None)
    if value is None:
        value = getattr(request.state, "request_id", None)
    return str(value) if value is not None else None


def api_error_info(
    *,
    code: str,
    message: str,
    request: Request | None = None,
    retryable: bool = True,
) -> ApiErrorInfo:
    return ApiErrorInfo(
        code=code,
        message=message,
        request_id=request_id_from_request(request),
        retryable=retryable,
    )


def degraded_snapshot(
    snapshot: Any,
    *,
    code: str,
    message: str,
    request: Request | None = None,
) -> Any:
    error = api_error_info(code=code, message=message, request=request)
    if isinstance(snapshot, BaseModel):
        update = {
            "degraded": True,
            "source": "snapshot",
            "error": error,
        }
        return snapshot.model_copy(deep=True, update=update)
    return _clone(snapshot)


def stable_read_failure(
    *,
    logger: logging.Logger,
    route: str,
    exc: Exception,
    request: Request | None = None,
    code: str = "stable_read_failed",
) -> None:
    logger.exception(
        "Stable read failed for %s request_id=%s code=%s",
        route,
        request_id_from_request(request),
        code,
        exc_info=True,
    )


def raise_structured_api_error(
    *,
    code: str,
    message: str,
    request: Request | None = None,
    status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE,
    retryable: bool = True,
) -> None:
    error = api_error_info(
        code=code,
        message=message,
        request=request,
        retryable=retryable,
    )
    raise HTTPException(
        status_code=status_code,
        detail=error.model_dump(mode="json"),
    )
