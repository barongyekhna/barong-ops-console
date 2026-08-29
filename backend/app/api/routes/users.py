import logging
from contextlib import nullcontext

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.roles import is_owner_role, list_standard_role_metadata, normalize_role
from ...db.session import get_db
from ...models.organization import OrganizationRecord
from ...models.user import User
from ...schemas.common import ListResponse
from ...schemas.user import (
    McpTokenIssueResponse,
    McpTokenLogItem,
    McpTokenLogResponse,
    McpTokenSummary,
    UserCreateResponse,
    BotCreate,
    PasswordResetRequest,
    UserCreate,
    UserPurgeResponse,
    UserResponse,
    UserRolesResponse,
    UserUpdate,
    is_user_manager_role,
    user_management_role_metadata,
)
from ...services.data_isolation import without_org_data_isolation
from ...services.org_membership_service import (
    OrgMembershipConflictError,
    add_org_member,
)
from ...schemas.org_membership import OrgMemberAddRequest
from ...services.user_management_service import (
    BotOperationNotAllowedError,
    DuplicateUsernameError,
    ManagedUserNotFoundError,
    OwnerRoleNotAllowedError,
    SelfDisableNotAllowedError,
    SelfPasswordResetNotAllowedError,
    UserManagementPermissionDeniedError,
    UserOrganizationNotFoundError,
    UserPurgeBlockedError,
    create_bot_user,
    create_managed_user,
    disable_managed_user,
    enable_managed_user,
    get_managed_user,
    list_users,
    purge_managed_user,
    reset_managed_user_password,
    update_managed_user,
)
from ...services import mcp_token_service
from ...services.api_stability import (
    api_snapshot_key,
    degraded_snapshot,
    get_api_snapshot,
    raise_structured_api_error,
    save_api_snapshot,
    stable_read_failure,
)
from ..deps import get_audit_context, get_current_user

router = APIRouter(prefix="/users", tags=["users"])
logger = logging.getLogger(__name__)


def _actor_org_id(actor: User) -> str | None:
    organization_id = actor.organization_id
    if organization_id is None:
        return None
    organization_id = organization_id.strip()
    return organization_id or None


def _scoped_organization_id(
    actor: User,
    requested_org_id: str | None,
) -> str | None:
    if is_user_manager_role(actor.role):
        return requested_org_id
    actor_org_id = _actor_org_id(actor)
    if actor_org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization context is required.",
        )
    if requested_org_id is not None and requested_org_id != actor_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Users outside the current organization are not visible.",
        )
    return actor_org_id


def _ensure_user_visible(actor: User, target: User) -> None:
    if is_user_manager_role(actor.role):
        return
    actor_org_id = _actor_org_id(actor)
    if actor_org_id is None or target.organization_id != actor_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Users outside the current organization are not visible.",
        )


def _raise_user_management_error(exc: Exception) -> None:
    if isinstance(exc, ManagedUserNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    if isinstance(exc, DuplicateUsernameError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    if isinstance(exc, OwnerRoleNotAllowedError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    if isinstance(exc, UserOrganizationNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    if isinstance(exc, UserManagementPermissionDeniedError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from None
    if isinstance(exc, (BotOperationNotAllowedError, UserPurgeBlockedError)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    if isinstance(
        exc,
        (SelfDisableNotAllowedError, SelfPasswordResetNotAllowedError),
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    raise exc


def _organization_name_map(
    db: Session,
    users: list[User],
) -> dict[str, str]:
    org_ids = sorted(
        {
            organization_id
            for user in users
            for organization_id in [(user.organization_id or "").strip()]
            if organization_id
        }
    )
    if not org_ids:
        return {}
    with without_org_data_isolation():
        rows = list(
            db.scalars(
                select(OrganizationRecord).where(
                    OrganizationRecord.org_id.in_(org_ids)
                )
            )
        )
    return {row.org_id: row.org_name for row in rows}


def _display_name_map(
    db: Session, users: list[User]
) -> dict[int, tuple[str | None, str | None, str | None]]:
    """中文显示名 + 昵称 + 头像都来自 C19 资料;登录名只是账号。

    返回 {user_id: (display_name, nickname, avatar_ref)},用户管理据此显示
    「昵称(真名)」;「接入钥匙」总览据此显示头像。
    """
    from ...models.c19 import C19ProfileRecord

    user_ids = [user.id for user in users if user.id is not None]
    if not user_ids:
        return {}
    with without_org_data_isolation():
        rows = db.execute(
            select(
                C19ProfileRecord.user_id,
                C19ProfileRecord.display_name,
                C19ProfileRecord.nickname,
                C19ProfileRecord.avatar_ref,
            ).where(C19ProfileRecord.user_id.in_(user_ids))
        ).all()
    return {
        int(user_id): (name, nickname, avatar_ref)
        for user_id, name, nickname, avatar_ref in rows
    }


def _user_response(
    user: User,
    organization_names: dict[str, str],
    display_names: dict[int, tuple[str | None, str | None, str | None]] | None = None,
) -> UserResponse:
    response = UserResponse.model_validate(user)
    if response.organization_id:
        response.organization = organization_names.get(
            response.organization_id,
            response.organization_id,
        )
    if display_names:
        entry = display_names.get(user.id)
        if entry is not None:
            display_name, nickname, avatar_ref = entry
            if display_name:
                response.display_name = display_name
            response.nickname = nickname
            response.avatar_url = avatar_ref or None
    return response


def _with_mcp_token(response: UserResponse, summary: dict | None) -> UserResponse:
    response.mcp_token = McpTokenSummary.model_validate(
        summary or mcp_token_service.token_summary(None)
    )
    return response


def _issue_response(issued: mcp_token_service.IssuedToken) -> McpTokenIssueResponse:
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


def require_user_manager(user: User = Depends(get_current_user)) -> User:
    if not is_user_manager_role(user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner or super admin role required.",
        )
    return user


@router.get("", response_model=ListResponse[UserResponse])
def users(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Query(default=None, max_length=40),
    role: str | None = Query(default=None, max_length=40),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ListResponse[UserResponse]:
    requested_org = organization_id.strip() if organization_id else None
    requested_org = requested_org or None
    requested_role = normalize_role(role) if role and role.strip() else None
    effective_org = _scoped_organization_id(actor, requested_org or None)

    cache_key = api_snapshot_key(
        "users.list",
        actor.id,
        actor.role,
        effective_org,
        requested_role,
        limit,
        offset,
    )

    try:
        read_context = (
            without_org_data_isolation()
            if is_user_manager_role(actor.role)
            else nullcontext()
        )
        with read_context:
            result = list_users(
                db,
                limit=limit,
                offset=offset,
                organization_id=effective_org,
                role=requested_role,
            )
        organization_names = _organization_name_map(db, result.items)
        display_names = _display_name_map(db, result.items)
        token_summaries = mcp_token_service.summaries_for_users(
            db, [item.id for item in result.items]
        )
        response = ListResponse(
            items=[
                _with_mcp_token(
                    _user_response(item, organization_names, display_names),
                    token_summaries.get(item.id),
                )
                for item in result.items
            ],
            count=result.count,
            limit=limit,
            offset=offset,
        )
        save_api_snapshot(cache_key, response)
        return response
    except Exception as exc:
        db.rollback()
        stable_read_failure(
            logger=logger,
            route="/users",
            exc=exc,
            request=request,
            code="users_list_failed",
        )
        snapshot = get_api_snapshot(cache_key)
        if snapshot is not None:
            return degraded_snapshot(
                snapshot,
                code="users_list_failed",
                message="User list is using the last successful snapshot because the live read failed.",
                request=request,
            )
        raise_structured_api_error(
            code="users_list_failed",
            message="User list is temporarily unavailable.",
            request=request,
            retryable=True,
        )


@router.post(
    "",
    response_model=UserCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def user_create(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserCreateResponse:
    try:
        user, initial_password = create_managed_user(
            db,
            payload=payload,
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    # C18H: give a non-owner user an active org membership so they can actually
    # enter business modules — the org-context middleware reads memberships, not
    # users.organization_id. add_org_member also syncs the C19 affiliation. This
    # is the correct entry point (create_managed_user itself stays membership-free
    # by design). owner has organization_id=None → skip.
    if user.organization_id is not None:
        membership_role = (
            "admin" if normalize_role(user.role) == "super_admin" else "member"
        )
        try:
            add_org_member(
                db,
                org_id=user.organization_id,
                payload=OrgMemberAddRequest(
                    user_id=str(user.id), role=membership_role
                ),
                actor=owner,
                audit=get_audit_context(request),
            )
        except OrgMembershipConflictError:
            pass  # already a member — idempotent
    # 每个真人账号自动配一把 MCP 个人钥匙;明文与初始密码一起只回给创建者一次。
    mcp_token_secret: str | None = None
    if not user.is_bot:
        issued = mcp_token_service.mint_token(
            db, user=user, actor=owner, audit=get_audit_context(request), reason="user_create"
        )
        db.commit()
        mcp_token_secret = issued.token
    base = _with_mcp_token(
        _user_response(user, _organization_name_map(db, [user]), _display_name_map(db, [user])),
        mcp_token_service.token_summary(mcp_token_service.get_token_row(db, user.id)),
    )
    # Surface the one-time initial password to the creator (returned once only).
    return UserCreateResponse.model_validate(
        {
            **base.model_dump(),
            "initial_password": initial_password,
            "mcp_token_secret": mcp_token_secret,
        }
    )


@router.post(
    "/bots",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def bot_register(
    payload: BotCreate,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserResponse:
    """注册数字员工(2026-08-22 拍板:以后的机器人必须在用户管理里注册)。"""
    try:
        user = create_bot_user(
            db,
            payload=payload,
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return _user_response(user, _organization_name_map(db, [user]), _display_name_map(db, [user]))


@router.get("/roles", response_model=UserRolesResponse)
def user_roles(
    actor: User = Depends(get_current_user),
) -> UserRolesResponse:
    if not is_user_manager_role(actor.role):
        return UserRolesResponse(
            assignable_roles=[],
            standard_roles=list_standard_role_metadata(),
        )
    role_metadata = user_management_role_metadata()
    return UserRolesResponse(
        assignable_roles=role_metadata,
        standard_roles=list_standard_role_metadata(),
    )


@router.get("/mcp-token-log", response_model=McpTokenLogResponse)
def users_mcp_token_log(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: User = Depends(require_user_manager),
) -> McpTokenLogResponse:
    """「接入钥匙」总览的操作记录:谁在什么时候发/重置/停用/启用了谁的钥匙。

    静态路径必须声明在 ``/{user_id}`` 之前(FastAPI 按声明顺序匹配,家规)。
    owner 看全部;super_admin 只看目标在本组织的记录。
    """
    from ...models.operation_log import OperationLog

    with without_org_data_isolation():
        rows = db.scalars(
            select(OperationLog)
            .where(OperationLog.action.like("mcp_token.%"))
            .order_by(OperationLog.id.desc())
            .limit(limit * 3 if not is_owner_role(actor.role) else limit)
        ).all()
        ids: set[int] = set()
        for row in rows:
            for raw in (row.actor_id, row.target_id):
                if raw and str(raw).isdigit():
                    ids.add(int(raw))
        users_by_id = {
            u.id: u
            for u in db.scalars(select(User).where(User.id.in_(ids or {0}))).all()
        }
    actor_org = _actor_org_id(actor)
    items: list[McpTokenLogItem] = []
    for row in rows:
        target = users_by_id.get(int(row.target_id)) if str(row.target_id or "").isdigit() else None
        if not is_owner_role(actor.role):
            if target is None or target.organization_id != actor_org:
                continue
        who = users_by_id.get(int(row.actor_id)) if str(row.actor_id or "").isdigit() else None
        items.append(
            McpTokenLogItem(
                id=row.id,
                action=row.action,
                actor_id=row.actor_id,
                actor_username=who.username if who else None,
                target_id=row.target_id,
                target_username=target.username if target else None,
                details=row.details if isinstance(row.details, dict) else None,
                ip_address=row.ip_address,
                created_at=row.created_at,
            )
        )
        if len(items) >= limit:
            break
    return McpTokenLogResponse(items=items, count=len(items))


@router.get("/{user_id}", response_model=UserResponse)
def user_detail(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> UserResponse:
    try:
        if is_user_manager_role(actor.role):
            with without_org_data_isolation():
                user = get_managed_user(db, user_id)
        else:
            user = get_managed_user(db, user_id)
    except Exception as exc:
        _raise_user_management_error(exc)
    _ensure_user_visible(actor, user)
    return _with_mcp_token(
        _user_response(user, _organization_name_map(db, [user]), _display_name_map(db, [user])),
        mcp_token_service.token_summary(mcp_token_service.get_token_row(db, user.id)),
    )


@router.patch("/{user_id}", response_model=UserResponse)
def user_update(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserResponse:
    try:
        user = update_managed_user(
            db,
            user_id=user_id,
            payload=payload,
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return _user_response(user, _organization_name_map(db, [user]), _display_name_map(db, [user]))


@router.post("/{user_id}/reset-password", response_model=UserResponse)
def user_reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserResponse:
    try:
        user = reset_managed_user_password(
            db,
            user_id=user_id,
            new_password=payload.new_password.get_secret_value(),
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return _user_response(user, _organization_name_map(db, [user]), _display_name_map(db, [user]))


@router.post("/{user_id}/disable", response_model=UserResponse)
def user_disable(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserResponse:
    try:
        user = disable_managed_user(
            db,
            user_id=user_id,
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return _user_response(user, _organization_name_map(db, [user]), _display_name_map(db, [user]))


@router.post("/{user_id}/mcp-token-reset", response_model=McpTokenIssueResponse)
def user_mcp_token_reset(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> McpTokenIssueResponse:
    """管理者给某人换一把新钥匙(明文只回这一次,由管理者转交)。"""
    try:
        issued = mcp_token_service.reset_token_for_user(
            db, user_id=user_id, actor=owner, audit=get_audit_context(request)
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return _issue_response(issued)


@router.post("/{user_id}/mcp-token-disable", response_model=McpTokenSummary)
def user_mcp_token_disable(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> McpTokenSummary:
    try:
        row = mcp_token_service.disable_token_for_user(
            db, user_id=user_id, actor=owner, audit=get_audit_context(request)
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return McpTokenSummary.model_validate(mcp_token_service.token_summary(row))


@router.post("/{user_id}/mcp-token-enable", response_model=McpTokenSummary)
def user_mcp_token_enable(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> McpTokenSummary:
    try:
        row = mcp_token_service.enable_token_for_user(
            db, user_id=user_id, actor=owner, audit=get_audit_context(request)
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return McpTokenSummary.model_validate(mcp_token_service.token_summary(row))


@router.post("/{user_id}/enable", response_model=UserResponse)
def user_enable(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserResponse:
    try:
        user = enable_managed_user(
            db,
            user_id=user_id,
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return _user_response(user, _organization_name_map(db, [user]), _display_name_map(db, [user]))


@router.delete("/{user_id}", response_model=UserPurgeResponse)
def user_purge(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserPurgeResponse:
    """彻底删除:只删已停用、非 owner、无业务记录引用的账号;否则 409。"""
    try:
        result = purge_managed_user(
            db,
            user_id=user_id,
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return UserPurgeResponse(**result)
