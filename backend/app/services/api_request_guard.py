from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256
from threading import Lock
from time import monotonic
from typing import Iterator

from fastapi import Depends, HTTPException, Request, status

from ..core.config import Settings, get_settings
from ..core.session_cookies import get_session_id_from_request

DEFAULT_HEAVY_REQUEST_LIMIT = 12
DEFAULT_HEAVY_REQUEST_WINDOW_SECONDS = 1.0
IN_FLIGHT_REQUEST_MAX_AGE_SECONDS = 30.0


@dataclass(frozen=True)
class ApiRequestGuardToken:
    duplicate_key: tuple[str, str, str, str]


_lock = Lock()
_request_windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_in_flight_requests: dict[tuple[str, str, str, str], float] = {}


def _stable_identity(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _session_identity(request: Request, settings: Settings) -> str:
    session_id = get_session_id_from_request(request, settings=settings)
    if session_id:
        return f"session:{_stable_identity(session_id)}"

    if request.client and request.client.host:
        return f"ip:{request.client.host[:45]}"

    return "anonymous"


def _request_query(request: Request) -> str:
    return str(request.url.query or "")


def _prune_window(window: deque[float], now: float, window_seconds: float) -> None:
    while window and now - window[0] > window_seconds:
        window.popleft()


def _prune_stale_in_flight(now: float) -> None:
    stale_keys = [
        key
        for key, started_at in _in_flight_requests.items()
        if now - started_at > IN_FLIGHT_REQUEST_MAX_AGE_SECONDS
    ]
    for key in stale_keys:
        _in_flight_requests.pop(key, None)


def enter_heavy_api_request(
    request: Request,
    *,
    settings: Settings,
    scope: str,
    limit: int = DEFAULT_HEAVY_REQUEST_LIMIT,
    window_seconds: float = DEFAULT_HEAVY_REQUEST_WINDOW_SECONDS,
) -> ApiRequestGuardToken:
    identity = _session_identity(request, settings)
    now = monotonic()
    normalized_limit = max(1, int(limit))
    normalized_window = max(0.1, float(window_seconds))
    throttle_key = (identity, scope)
    duplicate_key = (
        identity,
        request.method.upper(),
        request.url.path,
        _request_query(request),
    )

    with _lock:
        _prune_stale_in_flight(now)
        window = _request_windows[throttle_key]
        _prune_window(window, now, normalized_window)

        if len(window) >= normalized_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests for this session.",
                headers={"Retry-After": "1"},
            )

        if duplicate_key in _in_flight_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Duplicate request already in progress.",
                headers={"Retry-After": "1"},
            )

        window.append(now)
        _in_flight_requests[duplicate_key] = now

    return ApiRequestGuardToken(duplicate_key=duplicate_key)


def exit_heavy_api_request(token: ApiRequestGuardToken) -> None:
    with _lock:
        _in_flight_requests.pop(token.duplicate_key, None)


def guarded_heavy_api_request(scope: str):
    def dependency(
        request: Request,
        settings: Settings = Depends(get_settings),
    ) -> Iterator[None]:
        token = enter_heavy_api_request(
            request,
            settings=settings,
            scope=scope,
        )
        try:
            yield
        finally:
            exit_heavy_api_request(token)

    return dependency


def get_api_request_guard_stats() -> dict[str, int]:
    with _lock:
        return {
            "in_flight": len(_in_flight_requests),
            "session_windows": len(_request_windows),
        }


def reset_api_request_guard_state() -> None:
    with _lock:
        _in_flight_requests.clear()
        _request_windows.clear()
