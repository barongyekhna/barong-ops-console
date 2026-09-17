"""A 系列图片通道 —— MCP 服务器(Streamable HTTP,无状态)。照 k_images_server 的模式,业务全在 amz_series.images。

Codex 桌面版配置::

    [mcp_servers.barong_amz_images]
    url = "https://ops.barongyekhna.com/mcp/amz-images"
    bearer_token_env_var = "BARONG_K_MCP_TOKEN"   # 同一把个人钥匙(mcp_access_tokens),按 A 系列权限放行

鉴权:Bearer 个人钥匙认出是谁 → owner 或有店铺授权才能看;交稿要该店「操作」角色。
环境变量:``AMZ_MCP_FILE_SIGNING_KEY``(必填)、``AMZ_MCP_PUBLIC_BASE_URL``、``AMZ_MCP_PORT``(默认 8096)、``AMZ_MEDIA_ROOT``。
路由(前缀 ``/mcp/amz-images``):MCP 端点、``/files/{asset}``(签名 URL)、``/health``。
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID

import anyio
from sqlalchemy import text
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from ..core.roles import is_owner_role
from ..db.session import SessionLocal
from ..models.user import User
from ..modules.amz_series import images
from ..modules.amz_series.constants import STORE_ROLE_OPERATE, STORE_ROLE_RANK
from ..modules.amz_series.deps import granted_store_codes
from ..modules.amz_series.models import AmzImageAsset, AmzImageBrief, AmzStoreGrant
from ..modules.amz_series.service import AmzServiceError
from ..services.data_isolation import SKIP_ORG_DATA_ISOLATION
from .auth import TokenGuard, actor_user_id

try:
    from mcp.server.fastmcp import Context
except ImportError:  # pragma: no cover - backend image without the mcp SDK
    Context = Any  # type: ignore[assignment,misc]

_LOGGER = logging.getLogger("amz-mcp")

MCP_PATH = "/mcp/amz-images"
FILE_URL_TTL_SECONDS = 3600


class _Config:
    def __init__(self) -> None:
        self.file_signing_key = (os.getenv("AMZ_MCP_FILE_SIGNING_KEY") or "").strip().encode()
        self.public_base_url = (os.getenv("AMZ_MCP_PUBLIC_BASE_URL") or "https://ops.barongyekhna.com").rstrip("/")
        self.port = int(os.getenv("AMZ_MCP_PORT") or "8096")
        allowed = os.getenv("AMZ_MCP_ALLOWED_HOSTS") or "ops.barongyekhna.com,127.0.0.1:*,localhost:*,amz-mcp:*"
        self.allowed_hosts = [h.strip() for h in allowed.split(",") if h.strip()]

    def validate(self) -> None:
        if len(self.file_signing_key) < 32:
            raise SystemExit("AMZ_MCP_FILE_SIGNING_KEY 未配置或太短(至少 32 字符);拒绝启动。")


CONFIG = _Config()


# ---------------------------------------------------------------- 权限


class Actor:
    def __init__(self, user: User, store_codes: list[str] | None, operate_codes: set[str]) -> None:
        self.user = user
        self.store_codes = store_codes  # None = owner 全部
        self.operate_codes = operate_codes

    def can_view(self, store_code: str) -> bool:
        return self.store_codes is None or store_code in self.store_codes

    def can_operate(self, store_code: str) -> bool:
        return self.store_codes is None or store_code in self.operate_codes


def _actor(db: Any, user_id: int) -> Actor:
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise PermissionError("账号不存在或已停用。")
    codes = granted_store_codes(db, user)
    if codes is not None and not codes:
        raise PermissionError("这个账号没有任何亚马逊店铺授权。")
    operate: set[str] = set()
    if not is_owner_role(user.role):
        for code, role in db.execute(text("SELECT store_code, role FROM amz_store_grants WHERE user_id = :uid"), {"uid": int(user.id)}).all():
            if STORE_ROLE_RANK.get(role, 0) >= STORE_ROLE_RANK[STORE_ROLE_OPERATE]:
                operate.add(code)
    return Actor(user, codes, operate)


def _brief_for(db: Any, actor: Actor, brief_id: str, *, write: bool = False) -> AmzImageBrief:
    try:
        brief = db.get(AmzImageBrief, UUID(str(brief_id)))
    except ValueError as exc:
        raise AmzServiceError("brief_id 不是合法的 UUID", status_code=422, code="amz_brief_id_invalid") from exc
    if brief is None or not actor.can_view(brief.store_code):
        raise AmzServiceError("brief 不存在或无权查看", status_code=404, code="amz_brief_not_found")
    if write and not actor.can_operate(brief.store_code):
        raise AmzServiceError(f"交稿需要 {brief.store_code} 的「操作」角色", status_code=403, code="amz_store_forbidden")
    return brief


# ---------------------------------------------------------------- 签名文件


def _sign(asset_id: str, user_id: int, expires: int) -> str:
    return hmac.new(CONFIG.file_signing_key, f"{asset_id}:{user_id}:{expires}".encode(), hashlib.sha256).hexdigest()


def signed_file_url(asset_id: str, *, user_id: int, ttl: int = FILE_URL_TTL_SECONDS) -> str:
    expires = int(time.time()) + ttl
    return f"{CONFIG.public_base_url}{MCP_PATH}/files/{asset_id}?u={user_id}&exp={expires}&sig={_sign(asset_id, user_id, expires)}"


async def serve_file(request: Request) -> Response:
    asset_id = str(request.path_params.get("asset_id") or "")
    try:
        expires = int(request.query_params.get("exp") or "0")
        user_id = int(request.query_params.get("u") or "0")
    except ValueError:
        expires, user_id = 0, 0
    sig = str(request.query_params.get("sig") or "")
    if user_id <= 0 or expires < int(time.time()) or not hmac.compare_digest(sig, _sign(asset_id, user_id, expires)):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    def _load() -> tuple[bytes, str] | None:
        with SessionLocal() as db:
            actor = _actor(db, user_id)
            asset = db.get(AmzImageAsset, UUID(asset_id))
            if asset is None:
                return None
            _brief_for(db, actor, str(asset.brief_id))
            blob = images.asset_bytes(asset)
            return (blob, asset.mime_type) if blob else None

    try:
        loaded = await anyio.to_thread.run_sync(_load)
    except (AmzServiceError, PermissionError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    if loaded is None:
        return JSONResponse({"error": "FILE_MISSING"}, status_code=404)
    contents, mime = loaded
    return Response(contents, media_type=mime, headers={"Cache-Control": "private, max-age=600"})


async def health(_request: Request) -> Response:
    return JSONResponse({"ok": True, "service": "amz-mcp"})


def _run(fn: Callable[[], Any]) -> Any:
    def _call() -> Any:
        try:
            return fn()
        except AmzServiceError as exc:
            return {"error": exc.code, "message": str(exc)}
        except PermissionError as exc:
            return {"error": "UNAUTHENTICATED", "message": str(exc)}

    return anyio.to_thread.run_sync(_call)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------- 工具


def build_mcp() -> Any:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.utilities.types import Image
    from mcp.server.transport_security import TransportSecuritySettings
    from mcp.types import TextContent

    mcp = FastMCP(
        "barong-amz-images",
        instructions=(
            "Barong Yekhna console — Amazon (A series) listing images. Workflow: "
            "amz_list_briefs → amz_get_image_brief(brief_id) → amz_get_reference_images(brief_id) → "
            "render ONE image for the brief's position → amz_submit_image(brief_id, image_base64) → "
            "amz_get_submission_status(brief_id): fix only what the gates flag, resubmit (max 4 rounds). "
            "Nothing you submit goes to Amazon; a human picks and uploads."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path=MCP_PATH,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=CONFIG.allowed_hosts, allowed_origins=[]),
    )

    @mcp.tool(name="amz_list_briefs")
    async def amz_list_briefs(ctx: Context, status: str = "queued", limit: int = 20) -> str:
        """List image briefs waiting for a render (status queued / in_review). Returns JSON: id, store_code, sku, asin, position, title, rounds, max_rounds, status."""
        uid = actor_user_id(ctx)

        def _do() -> Any:
            with SessionLocal() as db:
                actor = _actor(db, uid)
                rows = images.list_briefs(db, store_codes=actor.store_codes, status=status if status != "open" else None)
                if status == "open":
                    rows = [r for r in rows if r.status in ("queued", "in_review")]
                return [images.brief_view(r) for r in rows[:limit]]

        return _dumps(await _run(_do))

    @mcp.tool(name="amz_get_image_brief")
    async def amz_get_image_brief(ctx: Context, brief_id: str) -> str:
        """Get the full brief (Markdown): evidence (which search term we lose on, to whom), product facts (hard constraints), position duty, must-have / forbidden lists, sibling-store differentiation rule, and reference image download URLs (1 hour)."""
        uid = actor_user_id(ctx)

        def _do() -> Any:
            with SessionLocal() as db:
                actor = _actor(db, uid)
                brief = _brief_for(db, actor, brief_id)
                md = brief.brief_md
                refs = images.references(db, brief)
                if refs:
                    md += "\n\n## Reference image download URLs (valid 1 hour)\n\n"
                    for r in refs:
                        md += f"- {r.id} · {images.REFERENCE_LABELS.get(r.kind, r.kind)}{' · ' + r.note if r.note else ''}: {signed_file_url(str(r.id), user_id=uid)}\n"
                subs = images.submissions(db, brief)
                if subs:
                    md += f"\n\n## Rounds so far: {brief.rounds}/{brief.max_rounds}\n"
                    for s in subs[:3]:
                        md += f"- round {s.round}: {s.review_json.get('verdict')} — {'; '.join(s.review_json.get('fix') or [])[:300]}\n"
                return md

        result = await _run(_do)
        return result if isinstance(result, str) else _dumps(result)

    @mcp.tool(name="amz_get_reference_images", structured_output=False)
    async def amz_get_reference_images(ctx: Context, brief_id: str):  # noqa: ANN202
        """Return the brief's reference images (product photos, current main image, sibling-store main images, competitor thumbnails) as image blocks plus signed download URLs."""
        uid = actor_user_id(ctx)

        def _do() -> Any:
            with SessionLocal() as db:
                actor = _actor(db, uid)
                brief = _brief_for(db, actor, brief_id)
                out = []
                for r in images.references(db, brief):
                    blob = images.asset_bytes(r)
                    if blob is None:
                        continue
                    out.append({"id": str(r.id), "kind": r.kind, "label": images.REFERENCE_LABELS.get(r.kind, r.kind), "note": r.note, "mime": r.mime_type, "bytes": images.thumbnail_bytes(blob, max_side=1024), "url": signed_file_url(str(r.id), user_id=uid)})
                return out

        result = await _run(_do)
        if isinstance(result, dict):
            return [TextContent(type="text", text=_dumps(result))]
        blocks: list[Any] = []
        for item in result:
            blocks.append(TextContent(type="text", text=f"{item['label']}{' · ' + item['note'] if item['note'] else ''} (id {item['id']}): {item['url']}"))
            blocks.append(Image(data=item["bytes"], format="jpeg").to_image_content())
        if not blocks:
            blocks.append(TextContent(type="text", text="(no reference images uploaded for this brief)"))
        return blocks

    @mcp.tool(name="amz_submit_image")
    async def amz_submit_image(ctx: Context, brief_id: str, image_base64: str, note: str = "") -> str:
        """Submit one rendered image (PNG/JPEG/WebP base64) for the brief. It is stored as a staged candidate and run through four gates (format, sibling-differentiation, same-screen, facts). Returns the gate results and what to fix. Max 4 rounds per brief."""
        uid = actor_user_id(ctx)

        def _do() -> Any:
            try:
                contents = base64.b64decode(image_base64, validate=True)
            except Exception as exc:  # noqa: BLE001
                raise AmzServiceError(f"image_base64 解不开:{type(exc).__name__}", status_code=422, code="amz_image_base64_invalid") from exc
            with SessionLocal() as db:
                actor = _actor(db, uid)
                brief = _brief_for(db, actor, brief_id, write=True)
                asset = images.submit(db, brief=brief, contents=contents, note=note, submitted_via="mcp", actor_user_id=uid)
                db.commit()
                return {"asset_id": str(asset.id), "round": asset.round, "max_rounds": brief.max_rounds, **asset.review_json}

        return _dumps(await _run(_do))

    @mcp.tool(name="amz_get_submission_status")
    async def amz_get_submission_status(ctx: Context, brief_id: str) -> str:
        """Gate results for every round submitted so far, newest first, plus whether a human has chosen one."""
        uid = actor_user_id(ctx)

        def _do() -> Any:
            with SessionLocal() as db:
                actor = _actor(db, uid)
                brief = _brief_for(db, actor, brief_id)
                return {"brief": images.brief_view(brief), "submissions": [images.asset_view(s) for s in images.submissions(db, brief)]}

        return _dumps(await _run(_do))

    return mcp


def build_app() -> Starlette:
    CONFIG.validate()
    mcp = build_mcp()
    mcp_app = mcp.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        def _check() -> None:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"), execution_options=SKIP_ORG_DATA_ISOLATION)

        await anyio.to_thread.run_sync(_check)
        _LOGGER.info("amz-mcp ready; endpoint %s", MCP_PATH)
        async with mcp.session_manager.run():
            yield

    app = Starlette(
        routes=[
            Route(f"{MCP_PATH}/health", health, methods=["GET"]),
            Route(f"{MCP_PATH}/files/{{asset_id}}", serve_file, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
        lifespan=lifespan,
    )
    return TokenGuard(app, open_prefixes=(f"{MCP_PATH}/files/", f"{MCP_PATH}/health"))  # type: ignore[return-value]


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(build_app(), host="0.0.0.0", port=CONFIG.port, proxy_headers=True, forwarded_allow_ips="*")  # noqa: S104


if __name__ == "__main__":
    main()


__all__ = ["CONFIG", "MCP_PATH", "build_app", "build_mcp", "main", "signed_file_url"]
