import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.arcade import ArcadeHighScoreRecord
from backend.app.models.user import User
from backend.app.repositories.arcade import (
    list_arcade_high_scores,
    submit_arcade_high_score,
)


@pytest.mark.unit
def test_arcade_high_score_upsert_only_accepts_a_strictly_higher_score() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    ArcadeHighScoreRecord.__table__.create(engine)

    with Session(engine) as db:
        created = submit_arcade_high_score(
            db,
            org_id="org_0123456789abcdef0123456789abcdef",
            game_id="snake",
            score=100,
            holder_user_id=1,
            username_snapshot="alice",
        )
        assert created.is_new_high_score is True
        tied = submit_arcade_high_score(
            db,
            org_id="org_0123456789abcdef0123456789abcdef",
            game_id="snake",
            score=100,
            holder_user_id=2,
            username_snapshot="bob",
        )
        assert tied.is_new_high_score is False
        assert tied.record.score == 100
        assert tied.record.username_snapshot == "alice"
        lower = submit_arcade_high_score(
            db,
            org_id="org_0123456789abcdef0123456789abcdef",
            game_id="snake",
            score=80,
            holder_user_id=2,
            username_snapshot="bob",
        )
        assert lower.is_new_high_score is False
        assert lower.record.score == 100
        assert lower.record.username_snapshot == "alice"
        higher = submit_arcade_high_score(
            db,
            org_id="org_0123456789abcdef0123456789abcdef",
            game_id="snake",
            score=120,
            holder_user_id=2,
            username_snapshot="bob",
        )
        assert higher.is_new_high_score is True
        assert higher.record.score == 120
        assert higher.record.username_snapshot == "bob"

        other_org = submit_arcade_high_score(
            db,
            org_id="org_abcdef0123456789abcdef0123456789",
            game_id="snake",
            score=40,
            holder_user_id=3,
            username_snapshot="carol",
        )
        assert other_org.is_new_high_score is True
        assert [
            (record.score, record.username_snapshot)
            for record in list_arcade_high_scores(
                db,
                org_id="org_0123456789abcdef0123456789abcdef",
            )
        ] == [(120, "bob")]
        assert [
            (record.score, record.username_snapshot)
            for record in list_arcade_high_scores(
                db,
                org_id="org_abcdef0123456789abcdef0123456789",
            )
        ] == [(40, "carol")]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("game_id", "score"),
    [
        ("not-a-game", 10),
        ("snake", 9_007_199_254_740_992),
    ],
)
def test_arcade_high_score_rejects_invalid_data_at_the_database(
    game_id: str,
    score: int,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    ArcadeHighScoreRecord.__table__.create(engine)

    with Session(engine) as db, pytest.raises(IntegrityError):
        submit_arcade_high_score(
            db,
            org_id="org_0123456789abcdef0123456789abcdef",
            game_id=game_id,
            score=score,
            holder_user_id=1,
            username_snapshot="alice",
        )
