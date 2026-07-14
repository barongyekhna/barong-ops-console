from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ArcadeGameId = Literal[
    "shmup",
    "snake",
    "tetris",
    "tank",
    "asteroids",
    "breakout",
    "2048",
    "runner",
    "match3",
    "mines",
    "flappy",
    "pong",
]

ARCADE_GAME_IDS: tuple[ArcadeGameId, ...] = (
    "shmup",
    "snake",
    "tetris",
    "tank",
    "asteroids",
    "breakout",
    "2048",
    "runner",
    "match3",
    "mines",
    "flappy",
    "pong",
)


class ArcadeScoreSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=9_007_199_254_740_991)


class ArcadeHighScoreRead(BaseModel):
    game_id: ArcadeGameId
    score: int = Field(ge=0)
    username: str
    updated_at: datetime


class ArcadeHighScoreSubmitResponse(ArcadeHighScoreRead):
    is_new_high_score: bool


class ArcadeHighScoreListResponse(BaseModel):
    items: list[ArcadeHighScoreRead]
