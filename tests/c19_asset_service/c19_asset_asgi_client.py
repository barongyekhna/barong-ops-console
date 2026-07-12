from __future__ import annotations

import asyncio

import httpx


class ASGIClient:
    """Sync facade over HTTPX's native async ASGI transport."""

    def __init__(self, app, *, base_url: str = "http://testserver"):
        self.app = app
        self.base_url = base_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async def execute() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=True)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=self.base_url,
                trust_env=False,
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(execute())

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def head(self, path: str, **kwargs) -> httpx.Response:
        return self.request("HEAD", path, **kwargs)
