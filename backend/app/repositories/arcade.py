from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models.arcade import ArcadeHighScoreRecord


@dataclass(frozen=True)
class ArcadeHighScoreWriteResult:
    record: ArcadeHighScoreRecord
    is_new_high_score: bool


def _score_query(
    *,
    org_id: str,
    game_id: str,
) -> Select[tuple[ArcadeHighScoreRecord]]:
    return (
        select(ArcadeHighScoreRecord)
        .where(
            ArcadeHighScoreRecord.org_id == org_id,
            ArcadeHighScoreRecord.game_id == game_id,
        )
        .execution_options(populate_existing=True)
    )


def list_arcade_high_scores(
    db: Session,
    *,
    org_id: str,
) -> list[ArcadeHighScoreRecord]:
    return list(
        db.scalars(
            select(ArcadeHighScoreRecord)
            .where(ArcadeHighScoreRecord.org_id == org_id)
            .order_by(ArcadeHighScoreRecord.game_id)
        )
    )


def submit_arcade_high_score(
    db: Session,
    *,
    org_id: str,
    game_id: str,
    score: int,
    holder_user_id: int,
    username_snapshot: str,
) -> ArcadeHighScoreWriteResult:
    dialect_name = db.get_bind().dialect.name
    values = {
        "org_id": org_id,
        "game_id": game_id,
        "score": score,
        "holder_user_id": holder_user_id,
        "username_snapshot": username_snapshot,
    }

    if dialect_name == "postgresql":
        insert_statement = postgresql_insert(ArcadeHighScoreRecord).values(**values)
    elif dialect_name == "sqlite":
        insert_statement = sqlite_insert(ArcadeHighScoreRecord).values(**values)
    else:
        raise RuntimeError(
            "Arcade high-score writes require PostgreSQL or SQLite."
        )

    upsert_statement = insert_statement.on_conflict_do_update(
        index_elements=[
            ArcadeHighScoreRecord.org_id,
            ArcadeHighScoreRecord.game_id,
        ],
        set_={
            "score": insert_statement.excluded.score,
            "holder_user_id": insert_statement.excluded.holder_user_id,
            "username_snapshot": insert_statement.excluded.username_snapshot,
            "updated_at": func.now(),
        },
        where=ArcadeHighScoreRecord.score < insert_statement.excluded.score,
    ).returning(ArcadeHighScoreRecord.id)

    updated_id = db.execute(upsert_statement).scalar_one_or_none()
    record = db.scalar(_score_query(org_id=org_id, game_id=game_id))
    if record is None:
        raise RuntimeError("Arcade high-score upsert did not produce a record.")

    return ArcadeHighScoreWriteResult(
        record=record,
        is_new_high_score=updated_id is not None,
    )
