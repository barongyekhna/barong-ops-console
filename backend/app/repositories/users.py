from datetime import datetime

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, load_only

from ..db.compatibility import table_exists
from ..models.user import User


C05B_USER_COLUMNS = (
    User.id,
    User.username,
    User.password_hash,
    User.role,
    User.job_title,
    User.organization_id,
    User.must_change_password,
    User.is_active,
    User.last_login_at,
    User.created_at,
    User.updated_at,
)
LOGIN_LOCKOUT_COLUMNS = (
    "failed_login_count",
    "last_failed_login_at",
    "locked_until",
)


def _user_select():
    return select(User).options(load_only(*C05B_USER_COLUMNS))


def login_lockout_columns_available(db: Session) -> bool:
    if not table_exists(db, "users"):
        return False
    columns = {
        column["name"]
        for column in inspect(db.get_bind()).get_columns("users")
    }
    return set(LOGIN_LOCKOUT_COLUMNS).issubset(columns)


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.scalar(_user_select().where(User.id == user_id))


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(_user_select().where(User.username == username))


def list_users(
    db: Session,
    *,
    limit: int,
    offset: int,
) -> list[User]:
    rows = list(db.scalars(_user_select().order_by(User.id).limit(limit + offset)))
    return rows[offset : offset + limit]


def get_owner(db: Session) -> User | None:
    return db.scalar(
        _user_select()
        .where(User.role == "owner")
        .order_by(User.id)
        .limit(1)
    )


def create_owner(
    db: Session,
    *,
    username: str,
    password_hash: str,
) -> User:
    user = User(
        username=username,
        password_hash=password_hash,
        role="owner",
        must_change_password=False,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_user(
    db: Session,
    *,
    username: str,
    password_hash: str,
    role: str,
    job_title: str | None,
    organization_id: str | None,
    is_active: bool,
) -> User:
    user = User(
        username=username,
        password_hash=password_hash,
        role=role,
        job_title=job_title,
        organization_id=organization_id,
        must_change_password=True,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    return user


def update_user(
    db: Session,
    user: User,
    *,
    role: str | None = None,
    is_active: bool | None = None,
) -> User:
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    db.add(user)
    db.flush()
    return user


def update_password_hash(
    db: Session,
    user: User,
    password_hash: str,
    *,
    must_change_password: bool | None = None,
) -> User:
    user.password_hash = password_hash
    if must_change_password is not None:
        user.must_change_password = must_change_password
    db.add(user)
    db.flush()
    return user


def update_last_login(db: Session, user: User, logged_in_at: datetime) -> None:
    user.last_login_at = logged_in_at
    db.add(user)


def record_failed_login(
    db: Session,
    user: User,
    *,
    failed_at: datetime,
    locked_until: datetime | None,
) -> User:
    if not login_lockout_columns_available(db):
        return user
    user.failed_login_count += 1
    user.last_failed_login_at = failed_at
    user.locked_until = locked_until
    db.add(user)
    db.flush()
    return user


def reset_login_failures(db: Session, user: User) -> User:
    if not login_lockout_columns_available(db):
        return user
    user.failed_login_count = 0
    user.last_failed_login_at = None
    user.locked_until = None
    db.add(user)
    db.flush()
    return user
