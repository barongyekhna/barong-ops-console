import pytest
from fastapi.testclient import TestClient

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.user import User
from tests.fixtures.organization_fixtures import DEFAULT_TEST_ORG_DB_ID

OWNER_USERNAME = "f10_api_owner"
SECOND_USERNAME = "arcade_score_challenger"
SECOND_PASSWORD = "example-only-arcade-challenger-password"


def _create_second_user() -> None:
    with SessionLocal() as db:
        user = User(
            username=SECOND_USERNAME,
            password_hash=hash_password(SECOND_PASSWORD),
            role="viewer",
            organization_id=DEFAULT_TEST_ORG_DB_ID,
            must_change_password=False,
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(
            OrgMembershipRecord(
                membership_id="membership_arcade_challenger",
                user_id=str(user.id),
                org_id=DEFAULT_TEST_ORG_DB_ID,
                role="member",
                status="active",
            )
        )
        db.commit()


def test_arcade_high_score_create_and_strictly_higher_replacement(
    owner_client: TestClient,
) -> None:
    initial = owner_client.get("/api/app/arcade/high-scores")
    assert initial.status_code == 200
    assert initial.json() == {"items": []}

    created = owner_client.post(
        "/api/app/arcade/high-scores/snake",
        json={"score": 120},
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["game_id"] == "snake"
    assert created_payload["score"] == 120
    assert created_payload["username"] == OWNER_USERNAME
    assert created_payload["is_new_high_score"] is True
    assert created_payload["updated_at"]

    lower = owner_client.post(
        "/api/app/arcade/high-scores/snake",
        json={"score": 80},
    )
    tied = owner_client.post(
        "/api/app/arcade/high-scores/snake",
        json={"score": 120},
    )

    assert lower.status_code == 200
    assert tied.status_code == 200
    for response in (lower, tied):
        payload = response.json()
        assert payload["score"] == 120
        assert payload["username"] == OWNER_USERNAME
        assert payload["updated_at"] == created_payload["updated_at"]
        assert payload["is_new_high_score"] is False

    _create_second_user()
    login = owner_client.post(
        "/api/public/auth/login",
        json={"username": SECOND_USERNAME, "password": SECOND_PASSWORD},
    )
    assert login.status_code == 200

    higher = owner_client.post(
        "/api/app/arcade/high-scores/snake",
        json={"score": 121},
    )
    assert higher.status_code == 200
    higher_payload = higher.json()
    assert higher_payload["score"] == 121
    assert higher_payload["username"] == SECOND_USERNAME
    assert higher_payload["is_new_high_score"] is True

    listed = owner_client.get("/api/app/arcade/high-scores")
    assert listed.status_code == 200
    assert listed.json()["items"] == [
        {
            "game_id": "snake",
            "score": 121,
            "username": SECOND_USERNAME,
            "updated_at": higher_payload["updated_at"],
        }
    ]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/app/arcade/high-scores/snake", {"score": -1}),
        (
            "/api/app/arcade/high-scores/snake",
            {"score": 9_007_199_254_740_992},
        ),
        ("/api/app/arcade/high-scores/not-a-game", {"score": 10}),
    ],
)
def test_arcade_high_score_rejects_invalid_submission(
    owner_client: TestClient,
    path: str,
    payload: dict[str, int],
) -> None:
    response = owner_client.post(path, json=payload)

    assert response.status_code == 422
