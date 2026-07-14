from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import OrgScopedMixin, PrimaryKeyMixin, TimestampMixin


def _big_integer_type() -> BigInteger:
    return BigInteger().with_variant(Integer, "sqlite")


class ArcadeHighScoreRecord(
    OrgScopedMixin,
    PrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "arcade_high_scores"
    __table_args__ = (
        CheckConstraint(
            "game_id IN ('shmup', 'snake', 'tetris', 'tank', 'asteroids', "
            "'breakout', '2048', 'runner', 'match3', 'mines', 'flappy', "
            "'pong')",
            name="game_id_allowed",
        ),
        CheckConstraint("score >= 0", name="score_non_negative"),
        CheckConstraint(
            "score <= 9007199254740991",
            name="score_safe_integer_max",
        ),
        UniqueConstraint(
            "org_id",
            "game_id",
            name="uq_arcade_high_scores_org_id_game_id",
        ),
    )

    game_id: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[int] = mapped_column(_big_integer_type(), nullable=False)
    holder_user_id: Mapped[int | None] = mapped_column(
        _big_integer_type(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    username_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
