import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import json
from math import ceil
from hashlib import sha256
from threading import Lock

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.security import (
    InvalidSessionIdError,
    generate_session_id,
    hash_session_id,
    hash_password,
    verify_password,
)
from ..core.roles import normalize_role
from ..db.compatibility import is_missing_table_error, table_exists
from ..models.auth_session import AuthSession
from ..models.user import User
from ..repositories.auth_sessions import (
    create_auth_session,
    get_auth_session_by_hash,
    invalidate_auth_session,
)
from ..repositories.operation_logs import create_operation_log
from ..repositories.users import (
    get_user_by_id,
    get_login_user_by_username,
    update_password_hash,
)
from ..schemas.user import must_change_password_required
from .event_collector import emit_event
from .data_isolation import SKIP_ORG_DATA_ISOLATION
from .login_side_effects import (
    LoginFailureSideEffect,
    LoginSuccessSideEffect,
    queue_login_failure_side_effect,
    queue_login_success_side_effect,
)
from .rate_limiter import register_login_rate_limit_attempt


class InvalidCredentialsError(ValueError):
    pass


class InvalidSessionError(ValueError):
    pass


class LoginRateLimitError(ValueError):
    def __init__(
        self,
        message: str = "Too many login attempts. Try again later.",
        *,
        retry_after_seconds: int,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class AuditContext:
    request_id: str
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True)
class LoginResult:
    session_id: str
    user: User
    auth_session: AuthSession


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    auth_session: AuthSession


@dataclass(frozen=True)
class AuthenticatedUserIdentity:
    id: int
    username: str
    role: str
    organization_id: str | None
    must_change_password: bool
    is_active: bool
    last_login_at: datetime | None
    session_expires_at: datetime
    session_id_hash: str
    # 这个会话选定的组织。**必须一路带到中间件** —— 中间件读的是
    # auth_session.active_org_id，而 auth_session 是由这个 identity 重建出来的。
    # 漏掉这一个字段，前面加列、登录挑默认组织、切换端点写库就全都白做。
    active_org_id: str | None = None


@dataclass(frozen=True)
class SessionRotationResult:
    session_id: str
    auth_session: AuthSession


@dataclass(frozen=True)
class _CachedSessionIdentity:
    identity: AuthenticatedUserIdentity
    cached_until: datetime


LEGACY_SESSION_PREFIX = "legacy-v1"
LEGACY_SESSION_HASH_MARKER = "legacy-v1:c05b-compat"
LEGACY_SESSION_COMPAT_REVISIONS = frozenset(
    (
        "c05b_permissions_001",
        "user_module_schema_repair_001",
    )
)
SESSION_IDENTITY_CACHE_TTL_SECONDS = 5
SESSION_IDENTITY_CACHE_MAX_ENTRIES = 4096
_session_identity_cache: dict[str, _CachedSessionIdentity] = {}
_session_identity_cache_lock = Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _legacy_session_cache_key(session_id: str) -> str:
    digest = sha256(session_id.encode("utf-8")).hexdigest()
    return f"{LEGACY_SESSION_HASH_MARKER}:{digest}"


def _cache_key_for_session_id(session_id: str) -> str:
    if session_id.startswith(f"{LEGACY_SESSION_PREFIX}."):
        return _legacy_session_cache_key(session_id)
    return hash_session_id(session_id)


def _identity_from_cache(
    cache_key: str,
    *,
    now: datetime,
) -> AuthenticatedUserIdentity | None:
    with _session_identity_cache_lock:
        cached = _session_identity_cache.get(cache_key)
        if cached is None:
            return None
        if cached.cached_until <= now:
            _session_identity_cache.pop(cache_key, None)
            return None
        if _as_aware(cached.identity.session_expires_at) <= now:
            _session_identity_cache.pop(cache_key, None)
            return None
        return cached.identity


def _cache_session_identity(
    identity: AuthenticatedUserIdentity,
    *,
    now: datetime,
) -> None:
    cached_until = min(
        _as_aware(identity.session_expires_at),
        now + timedelta(seconds=SESSION_IDENTITY_CACHE_TTL_SECONDS),
    )
    if cached_until <= now:
        return
    with _session_identity_cache_lock:
        if len(_session_identity_cache) >= SESSION_IDENTITY_CACHE_MAX_ENTRIES:
            _session_identity_cache.clear()
        _session_identity_cache[identity.session_id_hash] = _CachedSessionIdentity(
            identity=identity,
            cached_until=cached_until,
        )


def forget_cached_session_identity_hash(session_id_hash: str) -> None:
    with _session_identity_cache_lock:
        _session_identity_cache.pop(session_id_hash, None)


def forget_cached_session_identity(session_id: str) -> None:
    try:
        cache_key = _cache_key_for_session_id(session_id)
    except InvalidSessionIdError:
        return
    forget_cached_session_identity_hash(cache_key)


def clear_session_identity_cache() -> None:
    with _session_identity_cache_lock:
        _session_identity_cache.clear()


def get_cached_session_identity(
    session_id: str,
) -> AuthenticatedUserIdentity | None:
    try:
        cache_key = _cache_key_for_session_id(session_id)
    except InvalidSessionIdError:
        raise InvalidSessionError("Invalid session.") from None
    return _identity_from_cache(cache_key, now=_now())


def _retry_after_seconds(until: datetime, now: datetime) -> int:
    return max(1, ceil((_as_aware(until) - now).total_seconds()))


def _failed_login_delay_seconds(
    failed_login_count: int,
    settings: Settings,
) -> int:
    if failed_login_count <= 0:
        return 0
    base = settings.login_failed_attempt_base_delay_seconds
    if base <= 0:
        return 0
    exponent = min(failed_login_count - 1, 30)
    return min(
        base * (2**exponent),
        settings.login_failed_attempt_max_delay_seconds,
    )


def _user_retry_after_seconds(
    user: User,
    *,
    settings: Settings,
    now: datetime,
) -> int | None:
    if user.locked_until is not None:
        locked_until = _as_aware(user.locked_until)
        if locked_until > now:
            return _retry_after_seconds(locked_until, now)

    if user.last_failed_login_at is None:
        return None

    delay_seconds = _failed_login_delay_seconds(
        user.failed_login_count,
        settings,
    )
    if delay_seconds <= 0:
        return None

    retry_until = _as_aware(user.last_failed_login_at) + timedelta(
        seconds=delay_seconds
    )
    if retry_until > now:
        return _retry_after_seconds(retry_until, now)
    return None


def _lockout_until_for_failure(
    user: User,
    *,
    settings: Settings,
    failed_at: datetime,
) -> datetime | None:
    next_count = user.failed_login_count + 1
    if next_count < settings.login_failed_attempt_lockout_threshold:
        return None
    return failed_at + timedelta(minutes=settings.login_account_lockout_minutes)


def _record_login_rate_limit(
    db: Session,
    *,
    audit: AuditContext,
    reason: str,
    retry_after_seconds: int,
    user: User | None = None,
) -> None:
    create_operation_log(
        db,
        actor_type="user" if user is not None else "anonymous",
        actor_id=str(user.id) if user is not None else "anonymous",
        action="auth.login_rate_limited",
        target_type="session",
        target_id="current",
        result="failure",
        error_code="login_rate_limited",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={
            "outcome": "rate_limited",
            "reason": reason,
            "retry_after_seconds": retry_after_seconds,
        },
    )
    db.commit()


def _auth_sessions_table_available(db: Session) -> bool:
    try:
        rows = db.execute(text("SELECT version_num FROM alembic_version"), execution_options=SKIP_ORG_DATA_ISOLATION)
        revisions = {str(row[0]) for row in rows if row[0]}
    except SQLAlchemyError:
        db.rollback()
        revisions = set()
    if revisions & LEGACY_SESSION_COMPAT_REVISIONS:
        return False
    if not table_exists(db, "auth_sessions"):
        return False
    try:
        db.execute(text("SELECT 1 FROM auth_sessions LIMIT 1"), execution_options=SKIP_ORG_DATA_ISOLATION)
    except SQLAlchemyError as exc:
        db.rollback()
        if is_missing_table_error(exc, "auth_sessions"):
            return False
        raise
    return True


def _legacy_secret(settings: Settings) -> bytes:
    secret_parts = [settings.app_name, settings.database_url]
    if settings.owner_password is not None:
        secret_parts.append(settings.owner_password.get_secret_value())
    return "|".join(secret_parts).encode("utf-8")


def _base64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _base64url_decode(payload: str) -> bytes:
    padding = "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode(f"{payload}{padding}".encode("ascii"))


def _legacy_session_token(
    *,
    user_id: int,
    expires_at: datetime,
    settings: Settings,
) -> str:
    body = _base64url_encode(
        json.dumps(
            {
                "uid": user_id,
                "exp": int(expires_at.timestamp()),
                "nonce": generate_session_id(),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    signature = hmac.new(
        _legacy_secret(settings),
        body.encode("ascii"),
        sha256,
    ).hexdigest()
    return f"{LEGACY_SESSION_PREFIX}.{body}.{signature}"


def _parse_legacy_session_token(
    session_id: str,
    *,
    settings: Settings,
    now: datetime,
) -> tuple[int, datetime] | None:
    parts = session_id.split(".")
    if len(parts) != 3 or parts[0] != LEGACY_SESSION_PREFIX:
        return None
    body = parts[1]
    expected_signature = hmac.new(
        _legacy_secret(settings),
        body.encode("ascii"),
        sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, parts[2]):
        return None
    try:
        payload = json.loads(_base64url_decode(body))
        user_id = int(payload["uid"])
        expires_at = datetime.fromtimestamp(int(payload["exp"]), timezone.utc)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if expires_at <= now:
        return None
    return user_id, expires_at


def _transient_auth_session(
    *,
    user: User,
    issued_at: datetime,
    expires_at: datetime,
    audit: AuditContext,
) -> AuthSession:
    auth_session = AuthSession(
        session_id_hash=LEGACY_SESSION_HASH_MARKER,
        user_id=user.id,
        issued_at=issued_at,
        expires_at=expires_at,
        last_seen_at=issued_at,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
    )
    auth_session.id = 0
    auth_session.user = user
    return auth_session


def authenticated_session_from_identity(
    identity: AuthenticatedUserIdentity,
    *,
    audit: AuditContext,
) -> AuthenticatedSession:
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

    auth_session = AuthSession(
        session_id_hash=identity.session_id_hash,
        user_id=identity.id,
        issued_at=identity.session_expires_at,
        expires_at=identity.session_expires_at,
        # 中间件读的就是这一列；identity 里带过来的必须还原回去，
        # 否则「会话选定组织」那条分支照旧读到 None。
        active_org_id=identity.active_org_id,
        last_seen_at=None,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
    )
    auth_session.id = 0
    auth_session.invalidated_at = None
    auth_session.invalidation_reason = None
    auth_session.user = user
    return AuthenticatedSession(user=user, auth_session=auth_session)


def _is_legacy_auth_session(auth_session: AuthSession) -> bool:
    return auth_session.session_id_hash == LEGACY_SESSION_HASH_MARKER


def _default_active_org_for(db: Session, user: User) -> str | None:
    """登录时给这个会话挑一个默认组织。

    2026-09-01：加了 active_org_id 之后实测发现，新登录的**多组织**账号仍然整站
    403 —— 新会话这一列是空的，而解析链的「唯一 active 成员关系」那步因为有两个
    成员关系而落空。用户的体感是「能登录，然后什么都打不开」。

    规则按「最像他日常用的那个」排序，选不出来就返回 None
    （行为与从前完全一致，单组织用户不受任何影响）。
    """
    from ..models.org_membership import OrgMembershipRecord
    from ..models.organization import OrganizationRecord

    try:
        memberships = list(
            db.scalars(
                select(OrgMembershipRecord)
                .where(
                    OrgMembershipRecord.user_id == str(user.id),
                    OrgMembershipRecord.status == "active",
                )
                .order_by(OrgMembershipRecord.joined_at)
            )
        )
    except SQLAlchemyError:
        db.rollback()
        return None

    if not memberships:
        return None

    member_org_ids = [m.org_id for m in memberships]

    def _is_active_org(org_id: str) -> bool:
        return (
            db.scalar(
                select(OrganizationRecord.org_id).where(
                    OrganizationRecord.org_id == org_id,
                    OrganizationRecord.status == "active",
                )
            )
            is not None
        )

    # ① 管理员在用户管理里给他设的那个组织 —— 前提是他确实是成员。
    preferred = str(getattr(user, "organization_id", "") or "").strip()
    if preferred and preferred in member_org_ids and _is_active_org(preferred):
        return preferred

    # ② 否则取最早加入的那个 active 组织（通常是主职）。
    for org_id in member_org_ids:
        if _is_active_org(org_id):
            return org_id
    return None

def _new_session(
    db: Session,
    *,
    user: User,
    settings: Settings,
    audit: AuditContext,
    issued_at: datetime,
    auth_sessions_available: bool | None = None,
) -> tuple[str, AuthSession]:
    expires_at = issued_at + timedelta(minutes=settings.auth_session_expire_minutes)
    if auth_sessions_available is None:
        auth_sessions_available = _auth_sessions_table_available(db)
    if not auth_sessions_available:
        session_id = _legacy_session_token(
            user_id=user.id,
            expires_at=expires_at,
            settings=settings,
        )
        return (
            session_id,
            _transient_auth_session(
                user=user,
                issued_at=issued_at,
                expires_at=expires_at,
                audit=audit,
            ),
        )

    session_id = generate_session_id()
    try:
        auth_session = create_auth_session(
            db,
            session_id_hash=hash_session_id(session_id),
            user_id=user.id,
            issued_at=issued_at,
            expires_at=expires_at,
            ip_address=audit.ip_address,
            user_agent=audit.user_agent,
        )
        # 给会话挑个默认组织，否则多组织账号一登录就整站 403（实测）。
        # 选不出来就留空 —— 单组织用户走原来的解析链，行为不变。
        default_org = _default_active_org_for(db, user)
        if default_org is not None:
            auth_session.active_org_id = default_org
            db.add(auth_session)
    except SQLAlchemyError as exc:
        db.rollback()
        if not is_missing_table_error(exc, "auth_sessions"):
            raise
        session_id = _legacy_session_token(
            user_id=user.id,
            expires_at=expires_at,
            settings=settings,
        )
        auth_session = _transient_auth_session(
            user=user,
            issued_at=issued_at,
            expires_at=expires_at,
            audit=audit,
        )
    return session_id, auth_session


def _authenticated_identity_from_user(
    *,
    user: User,
    expires_at: datetime,
    session_id_hash: str,
    active_org_id: str | None = None,
) -> AuthenticatedUserIdentity:
    return AuthenticatedUserIdentity(
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
        session_expires_at=expires_at,
        session_id_hash=session_id_hash,
        active_org_id=active_org_id,
    )


def validate_session_identity_fast(
    db: Session,
    *,
    session_id: str,
) -> AuthenticatedUserIdentity:
    now = _now()
    try:
        cache_key = _cache_key_for_session_id(session_id)
    except InvalidSessionIdError:
        raise InvalidSessionError("Invalid session.") from None

    cached_identity = _identity_from_cache(cache_key, now=now)
    if cached_identity is not None:
        return cached_identity

    from ..core.config import get_settings

    legacy_session = _parse_legacy_session_token(
        session_id,
        settings=get_settings(),
        now=now,
    )
    if legacy_session is not None:
        user_id, expires_at = legacy_session
        row = db.execute(
            select(
                User.id,
                User.username,
                User.role,
                User.organization_id,
                User.must_change_password,
                User.is_active,
                User.last_login_at,
            ).where(User.id == user_id, User.is_active.is_(True))
        ).one_or_none()
        if row is None:
            raise InvalidSessionError("Invalid session.")
        identity = AuthenticatedUserIdentity(
            id=row.id,
            username=row.username,
            role=normalize_role(row.role),
            organization_id=row.organization_id,
            must_change_password=must_change_password_required(
                role=row.role,
                must_change_password=row.must_change_password,
            ),
            is_active=row.is_active,
            last_login_at=row.last_login_at,
            session_expires_at=expires_at,
            session_id_hash=cache_key,
        )
        _cache_session_identity(identity, now=now)
        return identity

    try:
        row = db.execute(
            select(
                User.id,
                User.username,
                User.role,
                User.organization_id,
                User.must_change_password,
                User.is_active,
                User.last_login_at,
                AuthSession.expires_at.label("session_expires_at"),
                AuthSession.active_org_id.label("session_active_org_id"),
            )
            .select_from(AuthSession)
            .join(User, AuthSession.user_id == User.id)
            .where(
                AuthSession.session_id_hash == cache_key,
                AuthSession.invalidated_at.is_(None),
                AuthSession.expires_at > now,
                User.is_active.is_(True),
            )
            .limit(1)
        ).one_or_none()
    except SQLAlchemyError as exc:
        db.rollback()
        if is_missing_table_error(exc, "auth_sessions"):
            forget_cached_session_identity_hash(cache_key)
            raise InvalidSessionError("Invalid session.") from None
        raise
    if row is None:
        forget_cached_session_identity_hash(cache_key)
        raise InvalidSessionError("Invalid session.")

    identity = AuthenticatedUserIdentity(
        id=row.id,
        username=row.username,
        role=normalize_role(row.role),
        organization_id=row.organization_id,
        must_change_password=must_change_password_required(
            role=row.role,
            must_change_password=row.must_change_password,
        ),
        is_active=row.is_active,
        last_login_at=row.last_login_at,
        session_expires_at=row.session_expires_at,
        session_id_hash=cache_key,
        active_org_id=row.session_active_org_id,
    )
    _cache_session_identity(identity, now=now)
    return identity


def login(
    db: Session,
    *,
    username: str,
    password: str,
    settings: Settings,
    audit: AuditContext,
) -> LoginResult:
    attempted_at = _now()

    # ① 三层桶限流（IP / 用户名 / 端点）。**放在密码哈希之前**——撞库的唯一成本
    # 就是那次 argon2 计算（约 0.5s 且可并发），先花掉它等于没有限流。
    rate_decision = register_login_rate_limit_attempt(
        db,
        username=username,
        audit=audit,
        settings=settings,
        now=attempted_at,
    )
    # **必须当场提交。** register_login_rate_limit_attempt 自己不 commit,计数只留在
    # 事务里;而登录失败会抛异常、事务被丢弃 —— 于是失败次数永远回到零,限流等于不存在。
    # 2026-08-31 实测:接回限流后连发 25 次错密码仍然全部 401,桶里只有成功登录留下的
    # 那两条记录。限流器要数的恰恰是失败,这一行 commit 才是它生效的前提。
    db.commit()
    if not rate_decision.allowed:
        retry_after = rate_decision.retry_after_seconds or 1
        _record_login_rate_limit(
            db,
            audit=audit,
            reason=rate_decision.reason or "login_rate_limited",
            retry_after_seconds=retry_after,
        )
        raise LoginRateLimitError(retry_after_seconds=retry_after)

    user = get_login_user_by_username(db, username)

    # ② 账号级锁定 / 失败退避。这两个字段 login_side_effects 一直在写，
    # 但在此之前**没有任何地方读它们**，所以锁定形同虚设。
    if user is not None:
        account_retry_after = _user_retry_after_seconds(
            user,
            settings=settings,
            now=attempted_at,
        )
        if account_retry_after is not None:
            _record_login_rate_limit(
                db,
                audit=audit,
                reason="account_locked",
                retry_after_seconds=account_retry_after,
                user=user,
            )
            raise LoginRateLimitError(retry_after_seconds=account_retry_after)

    password_matches = False

    if user is None:
        hash_password(password)
    else:
        password_matches = verify_password(password, user.password_hash)

    if user is None or not password_matches or not user.is_active:
        queue_login_failure_side_effect(
            LoginFailureSideEffect(
                user_id=user.id if user is not None else None,
                failed_at=attempted_at,
                request_id=audit.request_id,
                ip_address=audit.ip_address,
                user_agent=audit.user_agent,
            )
        )
        raise InvalidCredentialsError("Invalid username or password.")

    logged_in_at = _now()
    session_id, auth_session = _new_session(
        db,
        user=user,
        settings=settings,
        audit=audit,
        issued_at=logged_in_at,
        auth_sessions_available=True,
    )
    _cache_session_identity(
        _authenticated_identity_from_user(
            user=user,
            expires_at=auth_session.expires_at,
            session_id_hash=_cache_key_for_session_id(session_id),
            # 登录时刚挑好的默认组织必须一起进缓存，否则 5 秒缓存窗口内
            # 中间件仍然读到 None —— 用户会看到「刚登录就什么都打不开」。
            active_org_id=auth_session.active_org_id,
        ),
        now=logged_in_at,
    )
    db.commit()
    queue_login_success_side_effect(
        LoginSuccessSideEffect(
            user_id=user.id,
            auth_session_id=auth_session.id,
            logged_in_at=logged_in_at,
            role=user.role,
            request_id=audit.request_id,
            ip_address=audit.ip_address,
            user_agent=audit.user_agent,
        )
    )
    return LoginResult(
        session_id=session_id,
        user=user,
        auth_session=auth_session,
    )


def validate_session(
    db: Session,
    *,
    session_id: str,
    audit: AuditContext,
) -> AuthenticatedSession:
    now = _now()
    from ..core.config import get_settings

    legacy_session = _parse_legacy_session_token(
        session_id,
        settings=get_settings(),
        now=now,
    )
    if legacy_session is not None:
        user_id, expires_at = legacy_session
        user = get_user_by_id(db, user_id)
        if user is None or not user.is_active:
            raise InvalidSessionError("Invalid session.")
        return AuthenticatedSession(
            user=user,
            auth_session=_transient_auth_session(
                user=user,
                issued_at=now,
                expires_at=expires_at,
                audit=audit,
            ),
        )

    try:
        session_id_hash = hash_session_id(session_id)
    except InvalidSessionIdError:
        raise InvalidSessionError("Invalid session.") from None
    try:
        auth_session = get_auth_session_by_hash(db, session_id_hash)
    except SQLAlchemyError as exc:
        db.rollback()
        if is_missing_table_error(exc, "auth_sessions"):
            forget_cached_session_identity_hash(session_id_hash)
            raise InvalidSessionError("Invalid session.") from None
        raise

    if auth_session is None or auth_session.invalidated_at is not None:
        raise InvalidSessionError("Invalid session.")

    if _as_aware(auth_session.expires_at) <= now:
        forget_cached_session_identity_hash(auth_session.session_id_hash)
        raise InvalidSessionError("Invalid session.")

    user = get_user_by_id(db, auth_session.user_id)
    if user is None or not user.is_active:
        forget_cached_session_identity_hash(auth_session.session_id_hash)
        raise InvalidSessionError("Invalid session.")

    return AuthenticatedSession(user=user, auth_session=auth_session)


def rotate_session(
    db: Session,
    *,
    auth_session: AuthSession,
    user: User,
    settings: Settings,
    audit: AuditContext,
) -> SessionRotationResult:
    rotated_at = _now()
    invalidate_auth_session(
        db,
        auth_session,
        invalidated_at=rotated_at,
        reason="rotated",
    )
    forget_cached_session_identity_hash(auth_session.session_id_hash)
    session_id, new_session = _new_session(
        db,
        user=user,
        settings=settings,
        audit=audit,
        issued_at=rotated_at,
    )
    _cache_session_identity(
        _authenticated_identity_from_user(
            user=user,
            expires_at=new_session.expires_at,
            session_id_hash=_cache_key_for_session_id(session_id),
        ),
        now=rotated_at,
    )
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(user.id),
        action="auth.session_rotate",
        target_type="session",
        target_id=str(new_session.id),
        result="success",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={"outcome": "session_rotated"},
    )
    db.commit()
    return SessionRotationResult(
        session_id=session_id,
        auth_session=new_session,
    )


def change_password(
    db: Session,
    *,
    user: User,
    current_password: str,
    new_password: str,
    audit: AuditContext,
    session_id_hash: str | None = None,
) -> User:
    if not verify_password(current_password, user.password_hash):
        create_operation_log(
            db,
            actor_type="user",
            actor_id=str(user.id),
            action="auth.change_password",
            target_type="user",
            target_id=str(user.id),
            result="failure",
            error_code="invalid_current_password",
            request_id=audit.request_id,
            ip_address=audit.ip_address,
            user_agent=audit.user_agent,
            details={"outcome": "invalid_current_password"},
        )
        db.commit()
        raise InvalidCredentialsError("Invalid current password.")

    user = update_password_hash(
        db,
        user,
        hash_password(new_password),
        must_change_password=False,
    )
    if session_id_hash is not None:
        forget_cached_session_identity_hash(session_id_hash)
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(user.id),
        action="auth.change_password",
        target_type="user",
        target_id=str(user.id),
        result="success",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={"outcome": "password_changed"},
    )
    db.commit()
    db.refresh(user)
    return user


def logout(
    db: Session,
    *,
    user: User,
    auth_session: AuthSession,
    audit: AuditContext,
) -> None:
    if not _is_legacy_auth_session(auth_session) and auth_session.invalidated_at is None:
        invalidate_auth_session(
            db,
            auth_session,
            invalidated_at=_now(),
            reason="logout",
        )
        forget_cached_session_identity_hash(auth_session.session_id_hash)

    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(user.id),
        action="auth.logout",
        target_type="session",
        target_id=str(auth_session.id),
        result="success",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={"outcome": "session_invalidated"},
    )
    db.commit()
    emit_event(
        event_type="auth.logout",
        module="system",
        action="auth.logout",
        source="backend",
        status="success",
        context_id=audit.request_id,
        user_id=str(user.id),
        payload={"outcome": "session_invalidated"},
    )
