from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.user import User


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


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


def update_last_login(db: Session, user: User, logged_in_at: datetime) -> None:
    user.last_login_at = logged_in_at
    db.add(user)
