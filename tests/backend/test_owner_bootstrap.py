import json

import pytest
from sqlalchemy import func, select

from backend.app.cli.bootstrap_owner import (
    OwnerBootstrapError,
    bootstrap_owner,
)
from backend.app.core.security import verify_password
from backend.app.db.session import SessionLocal
from backend.app.models.operation_log import OperationLog
from backend.app.models.user import User

OWNER_USERNAME = "example_owner"
OWNER_PASSWORD = "example-only-owner-password"


def test_owner_bootstrap_creates_one_owner_and_audit_log(
    clean_auth_tables: None,
) -> None:
    with SessionLocal() as db:
        result = bootstrap_owner(
            db,
            owner_username=OWNER_USERNAME,
            owner_password=OWNER_PASSWORD,
        )

        owner = db.scalar(select(User).where(User.role == "owner"))
        operation_log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "auth.owner_bootstrap"
            )
        )

    assert result == "created"
    assert owner is not None
    assert owner.username == OWNER_USERNAME
    assert owner.is_active is True
    assert owner.password_hash != OWNER_PASSWORD
    assert verify_password(OWNER_PASSWORD, owner.password_hash)
    assert operation_log is not None
    assert operation_log.result == "success"

    serialized_log = json.dumps(operation_log.details, sort_keys=True)
    assert OWNER_PASSWORD not in serialized_log
    assert owner.password_hash not in serialized_log
    assert "password_hash" not in serialized_log


def test_owner_bootstrap_is_idempotent(clean_auth_tables: None) -> None:
    with SessionLocal() as db:
        first_result = bootstrap_owner(
            db,
            owner_username=OWNER_USERNAME,
            owner_password=OWNER_PASSWORD,
        )
        second_result = bootstrap_owner(
            db,
            owner_username=OWNER_USERNAME,
            owner_password=OWNER_PASSWORD,
        )

        owner_count = db.scalar(
            select(func.count()).select_from(User).where(User.role == "owner")
        )
        results = list(
            db.scalars(
                select(OperationLog.result)
                .where(OperationLog.action == "auth.owner_bootstrap")
                .order_by(OperationLog.id)
            )
        )

    assert first_result == "created"
    assert second_result == "skipped"
    assert owner_count == 1
    assert results == ["success", "skipped"]


def test_owner_bootstrap_missing_password_fails_without_sensitive_log_data(
    clean_auth_tables: None,
) -> None:
    with SessionLocal() as db:
        with pytest.raises(
            OwnerBootstrapError,
            match="OWNER_PASSWORD is required",
        ):
            bootstrap_owner(
                db,
                owner_username=OWNER_USERNAME,
                owner_password=None,
            )

        user_count = db.scalar(select(func.count()).select_from(User))
        operation_log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "auth.owner_bootstrap"
            )
        )

    assert user_count == 0
    assert operation_log is not None
    assert operation_log.result == "failure"
    serialized_log = json.dumps(operation_log.details, sort_keys=True)
    assert "password" not in serialized_log.lower()
    assert "hash" not in serialized_log.lower()
