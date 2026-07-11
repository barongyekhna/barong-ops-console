"""Constant-time service authentication for the internal HTTP boundary."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


bearer = HTTPBearer(auto_error=False)


async def require_service_token(request: Request) -> None:
    credentials: HTTPAuthorizationCredentials | None = await bearer(request)
    expected: str = request.app.state.settings.service_token
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
