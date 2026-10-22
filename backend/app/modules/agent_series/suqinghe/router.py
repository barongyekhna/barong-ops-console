"""苏青禾办公室的接口。

看:任何登录的人(GET /office)。管:只有 owner(批卡、定目标、暂停/恢复、交代一句)。
前端按 ``can_command`` 决定显示哪些按钮;真正的闸在这里的 require_owner。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....api.deps import get_current_user, require_owner
from ....core.roles import is_owner_role
from ....db.session import get_db
from ....models.user import User
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from . import cards, memory, office
from . import snapshot as _snapshot  # noqa: F401 —— 导入即登记 product_gate 指纹,批卡前才能查数据变没变
from .models import SqhGoal

router = APIRouter(prefix="/suqinghe", tags=["suqinghe"])


class DecideBody(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=2000)


class GoalBody(BaseModel):
    text: str = Field(min_length=2, max_length=1000)
    metric: str | None = Field(default=None, max_length=64)
    target: float | None = None


class GoalPatch(BaseModel):
    status: Literal["active", "paused", "done", "dropped"] | None = None
    text: str | None = Field(default=None, min_length=2, max_length=1000)


class ControlBody(BaseModel):
    action: Literal["pause", "resume"]


class InstructBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.get("/office")
def get_office(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    payload = office.office_payload(db, can_command=is_owner_role(user.role or ""))
    db.commit()
    return payload


@router.post("/cards/{ref}/decide")
def decide(ref: str, body: DecideBody, db: Session = Depends(get_db), owner: User = Depends(require_owner)) -> dict[str, Any]:
    try:
        outcome = cards.decide_card(db, card_id=ref, decision=body.decision, actor=owner, channel="web", reason=body.reason)
    except cards.CardError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    db.commit()
    return {"changed": outcome.changed, "card": cards.card_payload(outcome.card)}


@router.post("/goals")
def add_goal(body: GoalBody, db: Session = Depends(get_db), owner: User = Depends(require_owner)) -> dict[str, Any]:
    metric: dict[str, Any] = {}
    if body.metric and body.target is not None:
        metric = {"metric": body.metric, "target": body.target}
    goal = SqhGoal(text=body.text.strip(), metric=metric, status="active", created_by_user_id=str(owner.id))
    db.add(goal)
    db.flush()
    memory.record(db, kind="decision", subject="新目标", body=f"老板定了目标:{goal.text}", refs={"goal_id": goal.id, **metric}, source="human", actor_user_id=str(owner.id))
    memory.log_activity(db, f"收到新目标:{goal.text[:80]}", kind="goal")
    db.commit()
    return {"id": goal.id, "text": goal.text, "metric": goal.metric, "status": goal.status}


@router.patch("/goals/{goal_id}")
def patch_goal(goal_id: int, body: GoalPatch, db: Session = Depends(get_db), owner: User = Depends(require_owner)) -> dict[str, Any]:
    goal = db.get(SqhGoal, goal_id, execution_options=SKIP_ORG_DATA_ISOLATION)
    if goal is None:
        raise HTTPException(status_code=404, detail={"code": "SQH_GOAL_NOT_FOUND", "message": "没有这个目标。"})
    if body.text:
        goal.text = body.text.strip()
    if body.status:
        goal.status = body.status
    db.add(goal)
    memory.record(db, kind="decision", subject="目标调整", body=f"老板把目标「{goal.text[:80]}」改成 {goal.status}", refs={"goal_id": goal.id}, source="human", actor_user_id=str(owner.id))
    db.commit()
    return {"id": goal.id, "text": goal.text, "metric": goal.metric, "status": goal.status}


@router.post("/control")
def control(body: ControlBody, db: Session = Depends(get_db), owner: User = Depends(require_owner)) -> dict[str, Any]:
    state = office.get_state(db)
    paused = body.action == "pause"
    state.paused = paused
    state.paused_by_user_id = str(owner.id) if paused else None
    db.add(state)
    memory.log_activity(db, "老板让我先停一停。" if paused else "老板让我接着干。", kind="control")
    memory.record(db, kind="decision", subject="暂停" if paused else "恢复", body="老板暂停了苏青禾" if paused else "老板恢复了苏青禾", source="human", actor_user_id=str(owner.id))
    db.commit()
    return {"paused": paused}


@router.post("/instruct")
def instruct(body: InstructBody, db: Session = Depends(get_db), owner: User = Depends(require_owner)) -> dict[str, Any]:
    row = memory.record(db, kind="dictation", subject="老板交代", body=body.text.strip(), refs={"handled": False, "channel": "web"}, source="human", actor_user_id=str(owner.id))
    memory.log_activity(db, f"老板交代:{body.text.strip()[:80]}", kind="instruct")
    db.commit()
    return {"id": row.id, "queued": True}
