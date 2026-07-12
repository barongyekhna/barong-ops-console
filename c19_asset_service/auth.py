"""Constant-time authentication for the two private HTTP trust boundaries."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


bearer = HTTPBearer(auto_error=False)


async def _require(request: Request, expected: str) -> None:
    credentials: HTTPAuthorizationCredentials | None = await bearer(request)
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="service authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_service_token(request: Request) -> None:
    await _require(request, request.app.state.settings.service_token)


async def require_gateway_token(request: Request) -> None:
    await _require(request, request.app.state.settings.gateway_token)
