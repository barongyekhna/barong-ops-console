from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.user import User


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def list_users(
    db: Session,
    *,
    limit: int,
    offset: int,
) -> list[User]:
    return list(
        db.scalars(select(User).order_by(User.id).limit(limit).offset(offset))
    )


def get_owner(db: Session) -> User | None:
    return db.scalar(
        select(User)
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
    is_active: bool,
) -> User:
    user = User(
        username=username,
        password_hash=password_hash,
        role=role,
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
) -> User:
    user.password_hash = password_hash
    db.add(user)
    db.flush()
    return user


def update_last_login(db: Session, user: User, logged_in_at: datetime) -> None:
    user.last_login_at = logged_in_at
    db.add(user)
