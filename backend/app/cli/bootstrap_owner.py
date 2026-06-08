import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..core.config import EXAMPLE_DATABASE_URL, get_settings
from ..core.security import hash_password
from ..db.session import SessionLocal
from ..repositories.operation_logs import create_operation_log
from ..repositories.users import (
    create_owner,
    get_owner,
    get_user_by_username,
)

OWNER_BOOTSTRAP_LOCK_ID = 803081891


class OwnerBootstrapError(RuntimeError):
    pass


def _record_failure(
    db: Session,
    *,
    error_code: str,
    outcome: str,
) -> None:
    create_operation_log(
        db,
        actor_type="system",
        actor_id="owner-bootstrap",
        action="auth.owner_bootstrap",
        target_type="user",
        target_id="owner",
        result="failure",
        error_code=error_code,
        details={"outcome": outcome},
    )
    db.commit()


def bootstrap_owner(
    db: Session,
    *,
    owner_username: str | None,
    owner_password: str | None,
) -> str:
    username = owner_username.strip() if owner_username else ""
    if not username or len(username) > 255:
        _record_failure(
            db,
            error_code="owner_username_required",
            outcome="invalid_configuration",
        )
        raise OwnerBootstrapError("OWNER_USERNAME is required.")

    if not owner_password:
        _record_failure(
            db,
            error_code="owner_password_required",
            outcome="invalid_configuration",
        )
        raise OwnerBootstrapError("OWNER_PASSWORD is required.")
    if len(owner_password) < 12:
        _record_failure(
            db,
            error_code="owner_password_invalid",
            outcome="invalid_configuration",
        )
        raise OwnerBootstrapError(
            "OWNER_PASSWORD does not meet security requirements."
        )

    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": OWNER_BOOTSTRAP_LOCK_ID},
        )

    existing_owner = get_owner(db)
    if existing_owner is not None:
        create_operation_log(
            db,
            actor_type="system",
            actor_id="owner-bootstrap",
            action="auth.owner_bootstrap",
            target_type="user",
            target_id=str(existing_owner.id),
            result="skipped",
            details={"outcome": "owner_already_exists"},
        )
        db.commit()
        return "skipped"

    if get_user_by_username(db, username) is not None:
        _record_failure(
            db,
            error_code="owner_username_conflict",
            outcome="username_conflict",
        )
        raise OwnerBootstrapError(
            "Configured owner username is unavailable."
        )

    try:
        password_hash = hash_password(owner_password)
    except ValueError:
        _record_failure(
            db,
            error_code="owner_password_invalid",
            outcome="invalid_configuration",
        )
        raise OwnerBootstrapError(
            "OWNER_PASSWORD does not meet security requirements."
        ) from None

    owner = create_owner(
        db,
        username=username,
        password_hash=password_hash,
    )
    create_operation_log(
        db,
        actor_type="system",
        actor_id="owner-bootstrap",
        action="auth.owner_bootstrap",
        target_type="user",
        target_id=str(owner.id),
        result="success",
        details={"outcome": "created", "role": "owner"},
    )
    db.commit()
    return "created"


def main() -> int:
    settings = get_settings()
    if settings.database_url != EXAMPLE_DATABASE_URL:
        print(
            "Owner bootstrap requires the example database configuration.",
            file=sys.stderr,
        )
        return 1

    owner_password = (
        settings.owner_password.get_secret_value()
        if settings.owner_password is not None
        else None
    )

    with SessionLocal() as db:
        try:
            result = bootstrap_owner(
                db,
                owner_username=settings.owner_username,
                owner_password=owner_password,
            )
        except OwnerBootstrapError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except Exception:
            db.rollback()
            print("Owner bootstrap failed.", file=sys.stderr)
            return 1

    print(f"Owner bootstrap {result}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
