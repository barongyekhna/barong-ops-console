from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def table_exists(db: Session, table_name: str) -> bool:
    return inspect(db.get_bind()).has_table(table_name)


def column_exists(db: Session, table_name: str, column_name: str) -> bool:
    inspector = inspect(db.get_bind())
    if not inspector.has_table(table_name):
        return False
    return any(
        column.get("name") == column_name
        for column in inspector.get_columns(table_name)
    )


def is_missing_table_error(exc: BaseException, table_name: str) -> bool:
    if not isinstance(exc, SQLAlchemyError):
        return False
    message = str(exc).lower()
    return table_name.lower() in message and (
        "undefinedtable" in message or "does not exist" in message
    )
