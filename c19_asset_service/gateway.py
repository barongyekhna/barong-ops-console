"""Streaming byte plane. This role has no database credentials or ORM imports."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from .config import GatewaySettings
from .schemas import (
    GatewayDownloadAuthorizeResponse,
    GatewayUploadAuthorizeResponse,
)


_OPAQUE_TICKET_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


class GatewayControlError(RuntimeError):
    pass


class GatewayControl(Protocol):
    async def authorize_upload(
        self, ticket: str, content_length: int | None
    ) -> GatewayUploadAuthorizeResponse: ...

    async def complete_upload(
        self, ticket: str, size_bytes: int, sha256_hex: str
    ) -> None: ...

    async def authorize_download(
        self, ticket: str, method: str
    ) -> GatewayDownloadAuthorizeResponse: ...

    async def close(self) -> None: ...


class HttpGatewayControl:
    def __init__(self, settings: GatewaySettings) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.api_url,
            headers={"Authorization": f"Bearer {settings.gateway_token}"},
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )

    async def _post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        try:
            response = await self._client.post(path, json=body)
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):
                raise GatewayControlError("invalid control response")
            return value
        except (httpx.HTTPError, ValueError) as exc:
            raise GatewayControlError("control operation failed") from exc

    async def authorize_upload(
        self, ticket: str, content_length: int | None
    ) -> GatewayUploadAuthorizeResponse:
        try:
            return GatewayUploadAuthorizeResponse.model_validate(
                await self._post(
                    "/internal/uploads/authorize",
                    {"ticket": ticket, "method": "PUT", "content_length": content_length},
                )
            )
        except ValidationError as exc:
            raise GatewayControlError("invalid control response") from exc

    async def complete_upload(
        self, ticket: str, size_bytes: int, sha256_hex: str
    ) -> None:
        await self._post(
            "/internal/uploads/complete",
            {"ticket": ticket, "size_bytes": size_bytes, "sha256_hex": sha256_hex},
        )

    async def authorize_download(
        self, ticket: str, method: str
    ) -> GatewayDownloadAuthorizeResponse:
        try:
            return GatewayDownloadAuthorizeResponse.model_validate(
                await self._post(
                    "/internal/downloads/authorize",
                    {"ticket": ticket, "method": method},
                )
            )
        except ValidationError as exc:
            raise GatewayControlError("invalid control response") from exc

    async def close(self) -> None:
        await self._client.aclose()


def _safe_path(root: Path, object_key: str) -> Path:
    root = root.resolve()
    candidate = (root / object_key).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise GatewayControlError("invalid object location") from exc
    return candidate


def _content_length(request: Request, hard_max_bytes: int) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request") from exc
    if value < 0 or value > hard_max_bytes:
        raise HTTPException(status_code=413, detail="upload exceeds limit")
    return value


def _parse_range(value: str | None, size: int) -> tuple[int, int] | None:
    if value is None:
        return None
    if not value.startswith("bytes=") or "," in value:
        raise ValueError("invalid range")
    spec = value[6:]
    if "-" not in spec:
        raise ValueError("invalid range")
    start_raw, end_raw = spec.split("-", 1)
    if not start_raw:
        try:
            suffix = int(end_raw)
        except ValueError as exc:
            raise ValueError("invalid range") from exc
        if suffix <= 0:
            raise ValueError("invalid range")
        start = max(0, size - suffix)
        return start, size - 1
    try:
        start = int(start_raw)
        end = size - 1 if not end_raw else int(end_raw)
    except ValueError as exc:
        raise ValueError("invalid range") from exc
    if start < 0 or end < start or start >= size:
        raise ValueError("invalid range")
    return start, min(end, size - 1)


async def _file_chunks(path: Path, start: int, length: int) -> AsyncIterator[bytes]:
    remaining = length
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining:
            block = handle.read(min(1024 * 1024, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def _download_headers(
    metadata: GatewayDownloadAuthorizeResponse,
    *,
    start: int,
    end: int,
    partial: bool,
) -> dict[str, str]:
    length = end - start + 1
    disposition = metadata.disposition
    if disposition == "attachment":
        encoded = quote(metadata.filename, safe="")
        content_disposition = f"attachment; filename=download; filename*=UTF-8''{encoded}"
    else:
        content_disposition = "inline"
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": content_disposition,
        "Content-Length": str(length),
        "ETag": f'"sha256-{metadata.sha256_hex}"',
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{metadata.size_bytes}"
    return headers


def create_gateway_app(
    settings: GatewaySettings, *, control: GatewayControl | None = None
) -> FastAPI:
    settings.incoming_root.mkdir(parents=True, exist_ok=True)
    if not settings.active_root.is_dir():
        raise GatewayControlError("active object root is unavailable")
    owned_control = control is None
    control_runtime: GatewayControl = control or HttpGatewayControl(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        del application
        yield
        if owned_control:
            await control_runtime.close()

    app = FastAPI(
        title="C19 Asset Gateway",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        del request, exc
        return JSONResponse(status_code=404, content={"detail": "transfer not found"})

    @app.put("/api/backend/c19-assets/u/{ticket}", status_code=202)
    async def upload(ticket: str, request: Request) -> JSONResponse:
        if _OPAQUE_TICKET_RE.fullmatch(ticket) is None:
            raise HTTPException(status_code=404, detail="transfer not found")
        declared_length = _content_length(request, settings.hard_max_bytes)
        try:
            authorization = await control_runtime.authorize_upload(
                ticket, declared_length
            )
        except GatewayControlError as exc:
            raise HTTPException(status_code=404, detail="transfer not found") from exc
        if authorization.upload_state == "completed":
            return JSONResponse(status_code=202, content={"status": "uploaded"})
        if authorization.object_key is None:
            raise HTTPException(status_code=404, detail="transfer not found")
        path = _safe_path(settings.incoming_root, authorization.object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # A process crash may leave a partial. A fresh random staging name makes
        # the same idempotent ticket immediately retryable without overwriting a
        # concurrently streaming request.
        partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
        digest = hashlib.sha256()
        total = 0
        if path.is_file() and not path.is_symlink():
            existing_digest = hashlib.sha256()
            existing_size = 0
            with path.open("rb") as existing:
                while True:
                    block = existing.read(1024 * 1024)
                    if not block:
                        break
                    existing_size += len(block)
                    existing_digest.update(block)
            if existing_size != authorization.expected_size_bytes:
                raise HTTPException(status_code=409, detail="upload conflict")
            try:
                await control_runtime.complete_upload(
                    ticket, existing_size, existing_digest.hexdigest()
                )
            except GatewayControlError as exc:
                raise HTTPException(status_code=422, detail="upload rejected") from exc
            return JSONResponse(status_code=202, content={"status": "uploaded"})
        try:
            with partial.open("xb") as handle:
                async for chunk in request.stream():
                    total += len(chunk)
                    if (
                        total > settings.hard_max_bytes
                        or total > authorization.maximum_size_bytes
                        or total > authorization.expected_size_bytes
                    ):
                        raise HTTPException(status_code=413, detail="upload exceeds limit")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if total != authorization.expected_size_bytes:
                raise HTTPException(status_code=422, detail="upload size mismatch")
            os.replace(partial, path)
            directory_fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            try:
                await control_runtime.complete_upload(ticket, total, digest.hexdigest())
            except GatewayControlError as exc:
                # The completed bytes intentionally remain in incoming storage so the
                # worker can quarantine a digest mismatch or other rejected upload.
                raise HTTPException(status_code=422, detail="upload rejected") from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="upload conflict") from exc
        except Exception:
            if partial.exists():
                partial.unlink()
            raise
        return JSONResponse(status_code=202, content={"status": "uploaded"})

    async def download(ticket: str, request: Request) -> Response:
        if _OPAQUE_TICKET_RE.fullmatch(ticket) is None:
            raise HTTPException(status_code=404, detail="transfer not found")
        try:
            metadata = await control_runtime.authorize_download(ticket, request.method)
            path = _safe_path(settings.active_root, metadata.object_key)
        except GatewayControlError as exc:
            raise HTTPException(status_code=404, detail="transfer not found") from exc
        try:
            stat = path.stat()
        except OSError as exc:
            raise HTTPException(status_code=404, detail="transfer not found") from exc
        if not path.is_file() or stat.st_size != metadata.size_bytes:
            raise HTTPException(status_code=404, detail="transfer not found")
        try:
            byte_range = _parse_range(request.headers.get("range"), metadata.size_bytes)
        except ValueError as exc:
            return Response(
                status_code=416,
                headers={
                    "Content-Range": f"bytes */{metadata.size_bytes}",
                    "Cache-Control": "private, no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                },
            )
        partial_response = byte_range is not None
        start, end = byte_range or (0, metadata.size_bytes - 1)
        headers = _download_headers(
            metadata, start=start, end=end, partial=partial_response
        )
        status_code = 206 if partial_response else 200
        if request.method == "HEAD":
            return Response(
                status_code=status_code,
                headers=headers,
                media_type=metadata.media_type,
            )
        return StreamingResponse(
            _file_chunks(path, start, end - start + 1),
            status_code=status_code,
            headers=headers,
            media_type=metadata.media_type,
        )

    app.add_api_route(
        "/api/backend/c19-assets/d/{ticket}", download, methods=["GET", "HEAD"]
    )

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "c19-asset-gateway"}
    return app


def create_gateway_app_from_env() -> FastAPI:
    return create_gateway_app(GatewaySettings.from_environment())
