"""K 外部精修通道 —— MCP 服务器(Streamable HTTP,无状态)。

Codex 桌面版配置(token 走环境变量,Codex 不让贴进配置文件)::

    [mcp_servers.barong_k_images]
    url = "https://ops.barongyekhna.com/mcp/k-images"
    bearer_token_env_var = "BARONG_K_MCP_TOKEN"

鉴权(2026-08-28 起):每个真人账号一把 **个人钥匙**(``mcp_access_tokens``,只存哈希),
Bearer 认出是谁,再按那个人现有的 K 权限放行;交上去的图记在他名下。见 ``auth.py``。

环境变量(sidecar 侧,.env.production):
- ``K_MCP_FILE_SIGNING_KEY`` 参考图下载链接的签名密钥(必填;缺=启动失败)
- ``K_MCP_PUBLIC_BASE_URL``  对外基址,默认 https://ops.barongyekhna.com
- ``K_MCP_PORT``             默认 8095

路由(全部挂在 ``/mcp/k-images`` 前缀下,nginx 一个 location 直达本进程):
- ``/mcp/k-images``                 MCP 端点(Bearer 个人钥匙必须对)
- ``/mcp/k-images/files/{asset}``   参考图/成图字节(HMAC 签名 URL 含用户 id,1 小时;给 Codex 的 shell curl 用)
- ``/mcp/k-images/health``          存活探针(无鉴权,不泄漏任何业务信息)

业务全在 ``mcp_channel``;这里只做鉴权、线程化和把结果转成 MCP 内容块。
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

import anyio
from sqlalchemy import text
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from ..db.session import SessionLocal
from ..models.user import User
from ..modules.k_series.product_knowledge import mcp_channel as channel
from ..modules.k_series.product_knowledge.image_render_jobs import (
    KImageRenderError,
    _asset_file_bytes,
)
from .auth import TokenGuard, actor_user_id
from ..services.data_isolation import SKIP_ORG_DATA_ISOLATION

# FastMCP 用 typing.get_type_hints 解析工具签名;本文件开了 future annotations,
# ``ctx: Context`` 是字符串,必须在模块作用域能找到 Context。主后端镜像没装 mcp
# (它从不跑这个服务),所以兜底成 Any 让模块仍可导入。
try:
    from mcp.server.fastmcp import Context
except ImportError:  # pragma: no cover - backend image without the mcp SDK
    Context = Any  # type: ignore[assignment,misc]

_LOGGER = logging.getLogger("k-mcp")

MCP_PATH = "/mcp/k-images"
FILE_URL_TTL_SECONDS = 3600


class _Config:
    def __init__(self) -> None:
        signing = (os.getenv("K_MCP_FILE_SIGNING_KEY") or "").strip()
        self.file_signing_key = signing.encode()
        self.public_base_url = (
            os.getenv("K_MCP_PUBLIC_BASE_URL") or "https://ops.barongyekhna.com"
        ).rstrip("/")
        self.port = int(os.getenv("K_MCP_PORT") or "8095")
        allowed = os.getenv("K_MCP_ALLOWED_HOSTS") or "ops.barongyekhna.com,127.0.0.1:*,localhost:*,k-mcp:*"
        self.allowed_hosts = [h.strip() for h in allowed.split(",") if h.strip()]

    def validate(self) -> None:
        if len(self.file_signing_key) < 32:
            raise SystemExit("K_MCP_FILE_SIGNING_KEY 未配置或太短(至少 32 字符);拒绝启动。")


CONFIG = _Config()


# --- 签名文件链接 ---------------------------------------------------------------


def _sign(asset_id: str, user_id: int, expires: int) -> str:
    message = f"{asset_id}:{user_id}:{expires}".encode()
    return hmac.new(CONFIG.file_signing_key, message, hashlib.sha256).hexdigest()


def signed_file_url(asset_id: str, *, user_id: int, ttl: int = FILE_URL_TTL_SECONDS) -> str:
    """把用户 id 签进链接:文件面没有 Bearer,靠签名认人,服务时按他的作用域校验资产归属。"""
    expires = int(time.time()) + ttl
    return (
        f"{CONFIG.public_base_url}{MCP_PATH}/files/{asset_id}"
        f"?u={user_id}&exp={expires}&sig={_sign(asset_id, user_id, expires)}"
    )


async def serve_file(request: Request) -> Response:
    asset_id = str(request.path_params.get("asset_id") or "")
    try:
        expires = int(request.query_params.get("exp") or "0")
        user_id = int(request.query_params.get("u") or "0")
    except ValueError:
        expires, user_id = 0, 0
    sig = str(request.query_params.get("sig") or "")
    if (
        user_id <= 0
        or expires < int(time.time())
        or not hmac.compare_digest(sig, _sign(asset_id, user_id, expires))
    ):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    def _load() -> tuple[bytes, str, str] | None:
        with SessionLocal() as db:
            actor = _actor(db, user_id)
            channel.require_k_access(db, actor.user, write=False)
            asset, _product = channel.asset_file_for_download(
                db, asset_id=asset_id, scope=actor.scopes
            )
            loaded = _asset_file_bytes(asset)
            if loaded is None:
                return None
            name, contents, mime = loaded
            return contents, mime, name

    try:
        loaded = await anyio.to_thread.run_sync(_load)
    except KImageRenderError as exc:
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status_code)
    if loaded is None:
        return JSONResponse({"error": "FILE_MISSING"}, status_code=404)
    contents, mime, name = loaded
    return Response(
        contents,
        media_type=mime,
        headers={
            "Content-Disposition": f'inline; filename="{name}"',
            "Cache-Control": "private, max-age=600",
        },
    )


def _actor(db: Any, user_id: int) -> channel.ExternalActor:
    """TokenGuard 认出来的 user_id → 执行者(账号停用/没组织都 fail-closed)。"""
    user = db.get(User, user_id)
    if user is None:
        raise KImageRenderError("ACTOR_NOT_FOUND", "账号不存在。", status_code=401)
    return channel.actor_for_user(db, user)


async def health(_request: Request) -> Response:
    return JSONResponse({"ok": True, "service": "k-mcp"})


# --- 装机脚本(不含秘密;令牌由用户从控制台复制的那一行命令作为参数传入) ------

SETUP_SH = r"""#!/usr/bin/env bash
# Barong Yekhna 控制台 · K 外部精修通道 —— 把这台 Mac 上的 Codex 接到 K。
# 用法: curl -fsSL <url>/setup.sh | bash -s -- <token>
set -euo pipefail
TOKEN="${1:-}"
[ -n "$TOKEN" ] || { echo "缺令牌:请从控制台「新电脑接入 Codex」复制整行命令再运行。" >&2; exit 2; }
URL="__URL__"
VAR="__VAR__"
NAME="__NAME__"

# 1) 令牌进环境变量:给 Dock 启动的 Codex(launchctl)+ 终端(zshrc/bashrc)
if command -v launchctl >/dev/null 2>&1; then launchctl setenv "$VAR" "$TOKEN" || true; fi
for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
  touch "$rc"
  if grep -q "^export $VAR=" "$rc"; then
    sed -i.bak "s|^export $VAR=.*|export $VAR=$TOKEN|" "$rc" && rm -f "$rc.bak"
  else
    printf '\nexport %s=%s\n' "$VAR" "$TOKEN" >> "$rc"
  fi
done

# 2) Codex 配置:已有同名服务就不重复追加
mkdir -p "$HOME/.codex"
CFG="$HOME/.codex/config.toml"
touch "$CFG"
if ! grep -q "^\[mcp_servers\.$NAME\]" "$CFG"; then
  printf '\n[mcp_servers.%s]\nurl = "%s"\nbearer_token_env_var = "%s"\n' "$NAME" "$URL" "$VAR" >> "$CFG"
  echo "已写入 $CFG"
else
  echo "$CFG 里已有 [mcp_servers.$NAME],未重复写入"
fi

# 3) 立刻验一下令牌能不能开门
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' || echo 000)
if [ "$code" = "200" ]; then
  echo "✔ 令牌有效,服务器已应答。"
else
  echo "✘ 服务器返回 $code —— 令牌可能已更换,回控制台重新复制。" >&2; exit 1
fi
echo
echo "完成。请彻底退出 Codex(⌘Q)再打开,新建对话输入 /mcp,应看到 $NAME 下 5 个工具。"
"""

SETUP_PS1 = r"""param([Parameter(Mandatory=$true)][string]$Token)
# Barong Yekhna 控制台 · K 外部精修通道 —— 把这台 Windows 电脑上的 Codex 接到 K。
$Url = "__URL__"; $Var = "__VAR__"; $Name = "__NAME__"
[Environment]::SetEnvironmentVariable($Var, $Token, "User")
$env:BARONG_K_MCP_TOKEN = $Token
$cfgDir = Join-Path $env:USERPROFILE ".codex"
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
$cfg = Join-Path $cfgDir "config.toml"
if (-not (Test-Path $cfg)) { New-Item -ItemType File -Path $cfg | Out-Null }
if (-not (Select-String -Path $cfg -Pattern ("^\[mcp_servers\." + [regex]::Escape($Name) + "\]") -Quiet)) {
  Add-Content -Path $cfg -Value ("`n[mcp_servers.$Name]`nurl = `"$Url`"`nbearer_token_env_var = `"$Var`"")
  Write-Host "已写入 $cfg"
} else { Write-Host "$cfg 里已有 [mcp_servers.$Name],未重复写入" }
try {
  $r = Invoke-WebRequest -Uri $Url -Method POST -Headers @{Authorization="Bearer $Token"; Accept="application/json, text/event-stream"} `
       -ContentType "application/json" -Body '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' -UseBasicParsing
  if ($r.StatusCode -eq 200) { Write-Host "✔ 令牌有效,服务器已应答。" }
} catch { Write-Host "✘ 服务器拒绝了令牌 —— 可能已更换,回控制台重新复制。"; exit 1 }
Write-Host "`n完成。请彻底退出 Codex 再打开,新建对话输入 /mcp,应看到 $Name 下 5 个工具。"
"""


def _render_setup_script(template: str) -> str:
    return (
        template.replace("__URL__", f"{CONFIG.public_base_url}{MCP_PATH}")
        .replace("__VAR__", "BARONG_K_MCP_TOKEN")
        .replace("__NAME__", "barong_k_images")
    )


async def setup_sh(_request: Request) -> Response:
    return Response(_render_setup_script(SETUP_SH), media_type="text/x-shellscript; charset=utf-8")


async def setup_ps1(_request: Request) -> Response:
    return Response(_render_setup_script(SETUP_PS1), media_type="text/plain; charset=utf-8")


# --- MCP 工具 ---------------------------------------------------------------------


def _run(fn: Callable[[], Any]) -> Any:
    """同步 SQLAlchemy 工作放线程;通道层错误转成给代理看的 JSON,不炸协议。"""

    def _call() -> Any:
        try:
            return fn()
        except KImageRenderError as exc:
            return {"error": exc.code, "message": exc.message}
        except PermissionError as exc:
            return {"error": "UNAUTHENTICATED", "message": str(exc)}

    return anyio.to_thread.run_sync(_call)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def build_mcp() -> Any:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.utilities.types import Image
    from mcp.server.transport_security import TransportSecuritySettings
    from mcp.types import TextContent

    mcp = FastMCP(
        "barong-k-images",
        instructions=(
            "Barong Yekhna console — K series product images. Workflow: "
            "k_list_products_awaiting_images → k_get_image_brief(sku) → "
            "k_get_reference_images(sku) → render one image per position with your "
            "image model using ALL reference photos → k_submit_image(sku, position, image_base64) "
            "→ k_get_submission_status(sku) and fix findings by re-submitting. "
            "Nothing you submit is published; a human saves it in the console."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path=MCP_PATH,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=CONFIG.allowed_hosts,
            allowed_origins=[],
        ),
    )

    @mcp.tool(name="k_list_products_awaiting_images")
    async def k_list_products_awaiting_images(ctx: Context, limit: int = 20) -> str:
        """List K products that have an image brief, with which positions still lack a saved image.

        Returns JSON: sku, product_name_en, positions_total, positions_missing (need a render),
        positions_staged (submitted, waiting for a human to save), reference_images count.
        """

        uid = actor_user_id(ctx)

        def _do() -> Any:
            with SessionLocal() as db:
                actor = _actor(db, uid)
                channel.require_k_access(db, actor.user, write=False)
                return channel.list_products_awaiting_images(db, scope=actor.scopes, limit=limit)

        return _dumps(await _run(_do))

    @mcp.tool(name="k_get_image_brief")
    async def k_get_image_brief(ctx: Context, sku: str) -> str:
        """Get the full image brief for one product SKU (Markdown).

        Contains: how the product works (hard constraints), the only accessories allowed,
        reference image ids, per-position prompt (use verbatim), aspect ratio and current status.
        Reference images: call k_get_reference_images(sku) for bytes and download URLs.
        """

        uid = actor_user_id(ctx)

        def _do() -> Any:
            with SessionLocal() as db:
                actor = _actor(db, uid)
                channel.require_k_access(db, actor.user, write=False)
                product = channel.get_product_by_sku(db, sku, actor.scopes)
                brief = channel.build_external_brief(db, product=product)
                refs = channel.reference_summaries(db, product)
                if refs:
                    brief += "\n## Reference image download URLs (valid 1 hour)\n\n"
                    for ref in refs:
                        color = f" · {ref['variant_color']}" if ref["variant_color"] else ""
                        brief += f"- {ref['asset_id']}{color}: {signed_file_url(ref['asset_id'], user_id=uid)}\n"
                return brief

        result = await _run(_do)
        return result if isinstance(result, str) else _dumps(result)

    # structured_output=False:否则 SDK 会把返回的内容块列表当结构化结果序列化成
    # 一段 JSON 文本,image 块就没了(协议集成测试抓出来的)。
    @mcp.tool(name="k_get_reference_images", structured_output=False)
    async def k_get_reference_images(ctx: Context, sku: str):  # noqa: ANN202 - content blocks, not data
        """Return the product's real reference photos as images plus signed download URLs.

        Feed ALL of them to your image model as references; the product's pixels must come
        from these photos. Each image is preceded by a text line with its asset id and variant color.
        """

        uid = actor_user_id(ctx)

        def _do() -> Any:
            with SessionLocal() as db:
                actor = _actor(db, uid)
                channel.require_k_access(db, actor.user, write=False)
                product = channel.get_product_by_sku(db, sku, actor.scopes)
                out: list[tuple[dict[str, Any], bytes, str]] = []
                for row in channel.reference_assets(db, product):
                    loaded = _asset_file_bytes(row)
                    if loaded is None:
                        continue
                    meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
                    info = {
                        "asset_id": str(row.id),
                        "variant_color": str(meta.get("variant_color") or "") or None,
                        "variant_sku": row.variant_sku,
                        "mime_type": loaded[2],
                        "download_url": signed_file_url(str(row.id), user_id=uid),
                    }
                    out.append((info, loaded[1], loaded[2]))
                return out

        result = await _run(_do)
        if isinstance(result, dict):
            return [TextContent(type="text", text=_dumps(result))]
        if not result:
            return [TextContent(type="text", text="No reference images available for this SKU.")]
        blocks: list[Any] = []
        for info, contents, mime in result:
            blocks.append(TextContent(type="text", text=_dumps(info)))
            fmt = mime.split("/", 1)[-1] or "webp"
            blocks.append(Image(data=contents, format=fmt))
        return blocks

    @mcp.tool(name="k_submit_image")
    async def k_submit_image(
        ctx: Context,
        sku: str,
        position: int,
        image_base64: str,
        note: str | None = None,
    ) -> str:
        """Submit ONE rendered image for a brief position. It is stored as 'staged' and reviewed.

        image_base64: the PNG/WebP/JPEG bytes, base64 (no data: prefix). One image per call, never
        a contact sheet, no text labels. The console converts to WebP and runs brand / geometry /
        physics review; a human must save it in the console before it is used anywhere.
        note: optional short text about what you did (e.g. which references you used).
        """

        uid = actor_user_id(ctx)

        def _do() -> Any:
            raw = image_base64.strip()
            if raw.startswith("data:"):
                raw = raw.split(",", 1)[-1]
            try:
                contents = base64.b64decode(raw, validate=True)
            except Exception as exc:  # noqa: BLE001
                return {"error": "IMAGE_BASE64_INVALID", "message": f"base64 解码失败: {exc}"}
            with SessionLocal() as db:
                actor = _actor(db, uid)
                channel.require_k_access(db, actor.user, write=True)
                product = channel.get_product_by_sku(db, sku, actor.scopes)
                result = channel.submit_rendered_image(
                    db,
                    product=product,
                    position=position,
                    image_bytes=contents,
                    user=actor.user,
                    scope=channel.scope_of_product(product, actor.scopes),
                    note=note,
                )
                db.commit()
                result["submitted_by"] = actor.user.username
                result["preview_url"] = signed_file_url(result["asset_id"], user_id=uid)
                return result

        return _dumps(await _run(_do))

    @mcp.tool(name="k_get_submission_status")
    async def k_get_submission_status(ctx: Context, sku: str) -> str:
        """Status of every brief position for a SKU plus review findings on submitted images.

        audit.pending=true means review is still running — wait a minute and call again.
        image_findings lists brand / geometry / physics problems per position; fix by re-rendering
        and calling k_submit_image again for that position.
        """

        uid = actor_user_id(ctx)

        def _do() -> Any:
            with SessionLocal() as db:
                actor = _actor(db, uid)
                channel.require_k_access(db, actor.user, write=False)
                product = channel.get_product_by_sku(db, sku, actor.scopes)
                status = channel.submission_status(db, product=product)
                for asset in status.get("assets") or []:
                    asset["preview_url"] = signed_file_url(asset["asset_id"], user_id=uid)
                return status

        return _dumps(await _run(_do))

    return mcp


def build_app() -> Starlette:
    CONFIG.validate()
    mcp = build_mcp()
    mcp_app = mcp.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        # 启动只验「数据库可连」;身份逐请求由个人钥匙决定,没有固定执行者。
        def _check() -> None:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"), execution_options=SKIP_ORG_DATA_ISOLATION)

        await anyio.to_thread.run_sync(_check)
        _LOGGER.info("k-mcp ready (per-user tokens); endpoint %s", MCP_PATH)
        async with mcp.session_manager.run():
            yield

    app = Starlette(
        routes=[
            Route(f"{MCP_PATH}/health", health, methods=["GET"]),
            Route(f"{MCP_PATH}/setup.sh", setup_sh, methods=["GET"]),
            Route(f"{MCP_PATH}/setup.ps1", setup_ps1, methods=["GET"]),
            Route(f"{MCP_PATH}/files/{{asset_id}}", serve_file, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
        lifespan=lifespan,
    )
    return TokenGuard(
        app,
        # 装机脚本不含秘密,可匿名拉取;钥匙是用户从控制台复制的那一行里带的参数。
        # /files/* 靠签名 URL(含用户 id)认人。
        open_prefixes=(
            f"{MCP_PATH}/files/",
            f"{MCP_PATH}/health",
            f"{MCP_PATH}/setup.sh",
            f"{MCP_PATH}/setup.ps1",
        ),
    )  # type: ignore[return-value]


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        build_app(),
        host="0.0.0.0",  # noqa: S104 - container-internal; nginx fronts it
        port=CONFIG.port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


__all__ = ["CONFIG", "build_app", "build_mcp", "main", "signed_file_url"]
