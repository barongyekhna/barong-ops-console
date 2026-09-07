from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.session_cookies import (
    clear_session_cookie,
    get_session_id_from_request,
    set_session_cookie,
)
from ...core.roles import normalize_role
from ...db.session import get_db, get_read_db
from ...middleware.org_context import build_org_context
from ...models.auth_session import AuthSession
from ...models.user import User
from ...schemas.auth import (
    AuthContextResponse,
    AuthenticatedUser,
    ChangePasswordRequest,
    ChangePasswordResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
)
from ...schemas.user import must_change_password_required
from ...services.auth_service import (
    AuthenticatedSession,
    AuthenticatedUserIdentity,
    InvalidCredentialsError,
    InvalidSessionError,
    LoginRateLimitError,
    change_password as change_user_password,
    login as login_user,
    logout as logout_user,
    validate_session,
    validate_session_identity_fast,
)
from ...services.permission_decision_engine import PermissionDecisionEngine
from ...services.session_seen_buffer import queue_session_seen
from ...services.unified_permission_engine import UnifiedPermissionRequest
from ..deps import get_audit_context, get_current_session

router = APIRouter(prefix="/auth", tags=["authentication"])


def _not_authenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated.",
    )


def _current_identity_fast(
    request: Request,
    db: Session = Depends(get_read_db),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUserIdentity:
    session_id = get_session_id_from_request(request, settings=settings)
    if session_id is None:
        raise _not_authenticated()
    try:
        identity = validate_session_identity_fast(db, session_id=session_id)
    except InvalidSessionError:
        raise _not_authenticated() from None
    queue_session_seen(identity.session_id_hash)
    request.state.user_id = str(identity.id)
    return identity


def _identity_response(identity: AuthenticatedUserIdentity) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=identity.id,
        username=identity.username,
        role=normalize_role(identity.role),
        organization_id=identity.organization_id,
        must_change_password=identity.must_change_password,
        is_active=identity.is_active,
        last_login_at=identity.last_login_at,
    )


def _user_response(user: User) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        role=normalize_role(user.role),
        organization_id=user.organization_id,
        must_change_password=must_change_password_required(
            role=user.role,
            must_change_password=user.must_change_password,
        ),
        is_active=user.is_active,
        last_login_at=user.last_login_at,
    )


def _identity_user(identity: AuthenticatedUserIdentity) -> User:
    user = User(
        username=identity.username,
        password_hash="",
        role=normalize_role(identity.role),
        organization_id=identity.organization_id,
        must_change_password=identity.must_change_password,
        is_active=identity.is_active,
    )
    user.id = identity.id
    user.last_login_at = identity.last_login_at
    return user


def _identity_auth_session(identity: AuthenticatedUserIdentity) -> AuthSession:
    auth_session = AuthSession(
        session_id_hash=identity.session_id_hash,
        user_id=identity.id,
        issued_at=identity.session_expires_at,
        expires_at=identity.session_expires_at,
        last_seen_at=None,
        ip_address=None,
        user_agent=None,
    )
    auth_session.id = 0
    return auth_session


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    audit = get_audit_context(request)
    try:
        result = login_user(
            db,
            username=payload.username,
            password=payload.password.get_secret_value(),
            settings=settings,
            audit=audit,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from None
    except LoginRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from None

    request.state.user_id = str(result.user.id)
    set_session_cookie(
        response,
        session_id=result.session_id,
        settings=settings,
    )
    authenticated_user = _user_response(result.user)
    return LoginResponse(
        user=authenticated_user,
        session_token=result.session_id,
        auth_complete=True,
        require_password_change=authenticated_user.must_change_password,
        message=(
            "首次登录请先把一次性初始密码改成自己的密码"
            if authenticated_user.must_change_password
            else None
        ),
    )


@router.get("/me", response_model=AuthenticatedUser)
def me(
    identity: AuthenticatedUserIdentity = Depends(_current_identity_fast),
) -> AuthenticatedUser:
    return _identity_response(identity)


@router.get("/context", response_model=AuthContextResponse)
def auth_context(
    request: Request,
    db: Session = Depends(get_read_db),
    identity: AuthenticatedUserIdentity = Depends(_current_identity_fast),
) -> AuthContextResponse:
    request_id = str(getattr(request.state, "context_id", "")) or "auth-context"
    context, resolution_source = build_org_context(
        db,
        request=request,
        user=_identity_user(identity),
        auth_session=_identity_auth_session(identity),
        request_id=request_id,
    )
    if context is None:
        return AuthContextResponse(
            user_id=identity.id,
            org_id=None,
            role=None,
            module_scope=[],
            context_available=False,
            resolution_source=resolution_source,
        )
    return AuthContextResponse(
        user_id=identity.id,
        org_id=context.org_id,
        role=context.role,
        module_scope=context.module_scope,
        context_available=True,
        resolution_source=resolution_source,
    )


class OrgSwitchRequest(BaseModel):
    """切到哪个组织。"""

    org_id: str = Field(min_length=1, max_length=40)


class AvailableOrg(BaseModel):
    org_id: str
    org_name: str
    org_type: str
    role: str
    is_active_context: bool


class AvailableOrgsResponse(BaseModel):
    organizations: list[AvailableOrg]
    active_org_id: str | None


@router.get("/organizations", response_model=AvailableOrgsResponse)
def auth_available_organizations(
    request: Request,
    db: Session = Depends(get_read_db),
    identity: AuthenticatedUserIdentity = Depends(_current_identity_fast),
) -> AvailableOrgsResponse:
    """当前账号能切到哪些组织。

    前端的组织切换器用它填下拉。owner 看到全部 active 组织，
    其余人只看到自己有 active 成员关系的那些。
    """
    from ...models.organization import OrganizationRecord
    from ...models.org_membership import OrgMembershipRecord
    from ...core.roles import is_owner_role

    user = _identity_user(identity)
    auth_session = _identity_auth_session(identity)

    if is_owner_role(user.role):
        rows = list(
            db.scalars(
                select(OrganizationRecord)
                .where(OrganizationRecord.status == "active")
                .order_by(OrganizationRecord.org_name)
            )
        )
        roles = {row.org_id: "owner" for row in rows}
    else:
        memberships = list(
            db.scalars(
                select(OrgMembershipRecord).where(
                    OrgMembershipRecord.user_id == str(user.id),
                    OrgMembershipRecord.status == "active",
                )
            )
        )
        roles = {m.org_id: m.role for m in memberships}
        rows = (
            list(
                db.scalars(
                    select(OrganizationRecord)
                    .where(
                        OrganizationRecord.org_id.in_(list(roles)),
                        OrganizationRecord.status == "active",
                    )
                    .order_by(OrganizationRecord.org_name)
                )
            )
            if roles
            else []
        )

    active = getattr(auth_session, "active_org_id", None)
    return AvailableOrgsResponse(
        organizations=[
            AvailableOrg(
                org_id=row.org_id,
                org_name=row.org_name,
                org_type=row.org_type or "",
                role=roles.get(row.org_id, ""),
                is_active_context=(row.org_id == active),
            )
            for row in rows
        ],
        active_org_id=active,
    )


@router.post("/switch-organization", response_model=AuthContextResponse)
def auth_switch_organization(
    payload: OrgSwitchRequest,
    request: Request,
    db: Session = Depends(get_db),
    session: AuthenticatedSession = Depends(get_current_session),
) -> AuthContextResponse:
    """把当前会话切到指定组织。

    这是 middleware/org_context.py 里那条死分支缺的另一半：它一直在读
    `auth_session.active_org_id`，但从来没有地方写它。

    **安全要点**：必须确认这个人真的是目标组织的 active 成员，否则这个端点
    就成了越权入口 —— 它写的是后续所有请求的组织上下文。
    owner 例外，可切到任意 active 组织（与权限引擎里 owner 的全局语义一致）。
    """
    from ...core.roles import is_owner_role
    from ...models.org_membership import OrgMembershipRecord
    from ...models.organization import OrganizationRecord

    org_id = payload.org_id.strip()
    user = session.user

    organization = db.scalar(
        select(OrganizationRecord).where(
            OrganizationRecord.org_id == org_id,
            OrganizationRecord.status == "active",
        )
    )
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="找不到这个组织，或它已经停用。",
        )

    if not is_owner_role(user.role):
        membership = db.scalar(
            select(OrgMembershipRecord).where(
                OrgMembershipRecord.user_id == str(user.id),
                OrgMembershipRecord.org_id == org_id,
                OrgMembershipRecord.status == "active",
            )
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="这个账号不属于该组织。",
            )

    auth_session = session.auth_session
    auth_session.active_org_id = org_id
    db.add(auth_session)
    db.commit()

    # 组织上下文有会话级缓存（middleware/org_context.py），切换后必须让它失效，
    # 否则最多 5 秒内还停留在旧组织 —— 用户会以为切换没生效。
    from ...middleware.org_context import reset_org_context_cache_for_tests

    reset_org_context_cache_for_tests()

    request_id = str(getattr(request.state, "context_id", "")) or "auth-switch-org"
    context, resolution_source = build_org_context(
        db,
        request=request,
        user=user,
        auth_session=auth_session,
        request_id=request_id,
    )
    if context is None:
        return AuthContextResponse(
            user_id=user.id,
            org_id=None,
            role=None,
            module_scope=[],
            context_available=False,
            resolution_source=resolution_source,
        )
    return AuthContextResponse(
        user_id=user.id,
        org_id=context.org_id,
        role=context.role,
        module_scope=context.module_scope,
        context_available=True,
        resolution_source=resolution_source,
    )


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_session: AuthenticatedSession = Depends(get_current_session),
) -> ChangePasswordResponse:
    try:
        user = change_user_password(
            db,
            user=current_session.user,
            current_password=payload.current_password.get_secret_value(),
            new_password=payload.new_password.get_secret_value(),
            audit=get_audit_context(request),
            session_id_hash=current_session.auth_session.session_id_hash,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    return ChangePasswordResponse(
        user=_user_response(user),
        message="Password changed.",
    )


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LogoutResponse:
    session_id = get_session_id_from_request(request, settings=settings)
    current_session = None
    audit = get_audit_context(request)

    if session_id is not None:
        try:
            current_session = validate_session(
                db,
                session_id=session_id,
                audit=audit,
            )
        except InvalidSessionError:
            current_session = None

    if current_session is not None:
        user = current_session.user
        decision = PermissionDecisionEngine(
            db,
            request=request,
        ).decide_platform_metadata(
            UnifiedPermissionRequest(
                user_id=user.id,
                org_id=getattr(request.state, "org_id", None),
                module_id="AUTH",
                action="read",
                role=user.role,
                scope_type="global",
                scope_key="*",
                source="auth_logout",
            )
        )
        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied.",
            )
        logout_user(
            db,
            user=user,
            auth_session=current_session.auth_session,
            audit=audit,
        )

    clear_session_cookie(response, settings=settings)
    return LogoutResponse(message="Logged out.")
