import pytest

from backend.app.core.roles import (
    ASSIGNABLE_USER_ROLES,
    ROLE_BOT_AGENT,
    ROLE_MODULE_ADMIN,
    ROLE_OPERATOR,
    ROLE_OWNER,
    ROLE_REVIEWER,
    ROLE_SUPER_ADMIN,
    ROLE_VIEWER,
    STANDARD_ROLES,
    UNASSIGNABLE_USER_ROLES,
    get_role_display_metadata,
    is_assignable_user_role,
    is_owner_role,
    is_standard_role,
    normalize_role,
    validate_assignable_user_role,
)
from backend.app.schemas.user import (
    initial_must_change_password_for_role,
    must_change_password_required,
    role_bypasses_password_reset,
)


@pytest.mark.parametrize(
    "role",
    [
        ROLE_OWNER,
        ROLE_SUPER_ADMIN,
        ROLE_MODULE_ADMIN,
        ROLE_OPERATOR,
        ROLE_REVIEWER,
        ROLE_VIEWER,
        ROLE_BOT_AGENT,
    ],
)
def test_standard_roles(role: str) -> None:
    assert role in STANDARD_ROLES
    assert is_standard_role(role)
    assert get_role_display_metadata(role)["name"] == role


@pytest.mark.parametrize(
    "role",
    [ROLE_VIEWER, ROLE_OPERATOR, ROLE_REVIEWER],
)
def test_assignable_user_roles(role: str) -> None:
    assert role in ASSIGNABLE_USER_ROLES
    assert is_assignable_user_role(role)
    assert validate_assignable_user_role(role) == role


@pytest.mark.parametrize(
    "role",
    [ROLE_OWNER, ROLE_SUPER_ADMIN, ROLE_MODULE_ADMIN, ROLE_BOT_AGENT],
)
def test_unassignable_user_roles(role: str) -> None:
    assert role in UNASSIGNABLE_USER_ROLES
    assert not is_assignable_user_role(role)
    with pytest.raises(ValueError):
        validate_assignable_user_role(role)


def test_role_normalization_and_owner_helper() -> None:
    assert normalize_role(" Viewer ") == ROLE_VIEWER
    assert validate_assignable_user_role(" Operator ") == ROLE_OPERATOR
    assert is_owner_role(" Owner ")


@pytest.mark.parametrize(
    ("role", "bypasses_reset", "initial_must_change_password"),
    [
        (ROLE_OWNER, True, False),
        (ROLE_SUPER_ADMIN, False, True),
        (ROLE_OPERATOR, False, True),
        (ROLE_VIEWER, False, True),
        (ROLE_REVIEWER, False, True),
    ],
)
def test_password_reset_policy_only_owner_bypasses_reset(
    role: str,
    bypasses_reset: bool,
    initial_must_change_password: bool,
) -> None:
    assert role_bypasses_password_reset(role) is bypasses_reset
    assert (
        initial_must_change_password_for_role(role)
        is initial_must_change_password
    )
    assert (
        must_change_password_required(role=role, must_change_password=True)
        is initial_must_change_password
    )
    assert (
        must_change_password_required(role=role, must_change_password=False)
        is False
    )
