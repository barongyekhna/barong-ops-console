from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.arcade import ArcadeHighScoreRecord
from ...models.user import User
from ...repositories.arcade import (
    list_arcade_high_scores,
    submit_arcade_high_score,
)
from ...schemas.arcade import (
    ARCADE_GAME_IDS,
    ArcadeGameId,
    ArcadeHighScoreListResponse,
    ArcadeHighScoreRead,
    ArcadeHighScoreSubmitResponse,
    ArcadeScoreSubmit,
)
from ..deps import get_current_user

router = APIRouter(prefix="/arcade", tags=["arcade"])
_GAME_ORDER = {game_id: index for index, game_id in enumerate(ARCADE_GAME_IDS)}


def _request_org_id(request: Request) -> str:
    org_id = getattr(request.state, "org_id", None)
    if not isinstance(org_id, str) or not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization context is required.",
        )
    return org_id


def _read_score(record: ArcadeHighScoreRecord) -> ArcadeHighScoreRead:
    return ArcadeHighScoreRead(
        game_id=record.game_id,
        score=record.score,
        username=record.username_snapshot,
        updated_at=record.updated_at,
    )


@router.get("/high-scores", response_model=ArcadeHighScoreListResponse)
def get_arcade_high_scores(
    request: Request,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ArcadeHighScoreListResponse:
    org_id = _request_org_id(request)
    records = list_arcade_high_scores(db, org_id=org_id)
    records.sort(
        key=lambda record: _GAME_ORDER.get(record.game_id, len(_GAME_ORDER))
    )
    return ArcadeHighScoreListResponse(
        items=[_read_score(record) for record in records]
    )


@router.post(
    "/high-scores/{game_id}",
    response_model=ArcadeHighScoreSubmitResponse,
)
def post_arcade_high_score(
    game_id: ArcadeGameId,
    payload: ArcadeScoreSubmit,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ArcadeHighScoreSubmitResponse:
    org_id = _request_org_id(request)
    result = submit_arcade_high_score(
        db,
        org_id=org_id,
        game_id=game_id,
        score=payload.score,
        holder_user_id=user.id,
        username_snapshot=user.username,
    )
    score = _read_score(result.record)
    return ArcadeHighScoreSubmitResponse(
        **score.model_dump(),
        is_new_high_score=result.is_new_high_score,
    )
