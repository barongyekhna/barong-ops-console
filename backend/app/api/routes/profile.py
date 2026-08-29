"""Self-service profile settings for the current user.

Lets any authenticated user read/update their own nickname + theme preference
and upload an avatar — none of which the admin-only user-management routes cover.
Nickname/theme live on the C19 profile row (the app's per-user profile); the
avatar image bytes live in ``user_avatars`` and are served inline.
"""

from __future__ import annotations

import hashlib
import io

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from ...models.c19 import UserAvatarRecord
from ...models.user import User
from ...modules.c19.identity_sync_service import sync_profile_for_user
from ...schemas.profile import McpAccessRead, ProfileRead, ProfileUpdate
from ...schemas.user import McpTokenIssueResponse, McpTokenSummary
from ...services import mcp_token_service
from ...services.user_management_service import BotOperationNotAllowedError
from ..deps import get_audit_context, get_current_user, get_db

router = APIRouter(prefix="/profile", tags=["profile"])

VALID_THEMES = {"light", "dark", "system"}
MAX_AVATAR_BYTES = 8 * 1024 * 1024
AVATAR_SIDE = 256


def _avatar_url(user_id: int, sha256: str) -> str:
    return f"/api/backend/profile/avatar/{user_id}?v={sha256[:8]}"


def _serialize(user: User, profile) -> ProfileRead:
    return ProfileRead(
        user_id=user.id,
        username=user.username,
        display_name=profile.display_name,
        nickname=profile.nickname,
        avatar_url=profile.avatar_ref,
        theme_pref=(profile.theme_pref or "dark"),
        bio=profile.bio,
    )


@router.get("/me", response_model=ProfileRead)
def get_my_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileRead:
    profile = sync_profile_for_user(db, user=user)
    db.commit()
    return _serialize(user, profile)


@router.patch("/me", response_model=ProfileRead)
def update_my_profile(
    payload: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileRead:
    profile = sync_profile_for_user(db, user=user)
    data = payload.model_dump(exclude_unset=True)
    if "nickname" in data:
        nickname = (data["nickname"] or "").strip()
        profile.nickname = nickname or None
    if "theme_pref" in data:
        theme = data["theme_pref"]
        if theme not in VALID_THEMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="未知的主题偏好。",
            )
        profile.theme_pref = theme
    db.commit()
    return _serialize(user, profile)


@router.post("/me/avatar", response_model=ProfileRead)
async def upload_my_avatar(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
) -> ProfileRead:
    raw = await file.read()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="没有收到图片。"
        )
    if len(raw) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="图片过大,请控制在 8MB 以内。",
        )

    # Normalize to a square 256px WebP so avatars are uniform and small.
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad upload
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="无法识别的图片格式。"
        ) from exc
    image = image.convert("RGB")
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    image = image.crop((left, top, left + side, top + side)).resize(
        (AVATAR_SIDE, AVATAR_SIDE)
    )
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=88, method=6)
    data = buffer.getvalue()
    sha256 = hashlib.sha256(data).hexdigest()

    row = db.get(UserAvatarRecord, user.id)
    if row is None:
        db.add(
            UserAvatarRecord(
                user_id=user.id,
                content_bytes=data,
                mime_type="image/webp",
                sha256=sha256,
            )
        )
    else:
        row.content_bytes = data
        row.mime_type = "image/webp"
        row.sha256 = sha256

    profile = sync_profile_for_user(db, user=user)
    profile.avatar_ref = _avatar_url(user.id, sha256)
    db.commit()
    return _serialize(user, profile)


@router.get("/me/mcp", response_model=McpAccessRead)
def my_mcp_access(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> McpAccessRead:
    """本人 MCP 钥匙状态(永不含明文)。"""
    row = mcp_token_service.get_token_row(db, user.id)
    return McpAccessRead(
        summary=McpTokenSummary.model_validate(mcp_token_service.token_summary(row)),
        eligible=not user.is_bot,
        server_name=mcp_token_service.MCP_SERVER_NAME,
        server_url=mcp_token_service.mcp_endpoint_url(),
        verify_hint=mcp_token_service.VERIFY_HINT,
    )


@router.post("/me/mcp/reset", response_model=McpTokenIssueResponse)
def reset_my_mcp_token(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> McpTokenIssueResponse:
    """本人生成/重置自己的钥匙:明文 + 装机命令只回这一次。被管理员停用的不能自救。"""
    try:
        issued = mcp_token_service.reset_own_token(
            db, user=user, audit=get_audit_context(request)
        )
    except BotOperationNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from None
    commands = mcp_token_service.install_commands(issued.token)
    return McpTokenIssueResponse(
        token=issued.token,
        summary=McpTokenSummary.model_validate(mcp_token_service.token_summary(issued.row)),
        setup_command_mac=commands["mac"],
        setup_command_windows=commands["windows"],
        server_name=mcp_token_service.MCP_SERVER_NAME,
        server_url=mcp_token_service.mcp_endpoint_url(),
        verify_hint=mcp_token_service.VERIFY_HINT,
    )


@router.get("/avatar/{user_id}")
def get_avatar(
    user_id: int,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    row = db.get(UserAvatarRecord, user_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="该用户没有头像。"
        )
    return Response(
        content=row.content_bytes,
        media_type=row.mime_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "ETag": f'"{row.sha256}"',
        },
    )
