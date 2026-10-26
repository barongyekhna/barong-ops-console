"""苏青禾办公室的接口。

看:任何登录的人(GET /office)。管:只有 owner(批卡、定目标、暂停/恢复、交代一句)。
前端按 ``can_command`` 决定显示哪些按钮;真正的闸在这里的 require_owner。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....api.deps import get_current_user, require_owner
from ....core.roles import is_owner_role
from ....db.session import get_db
from ....models.user import User
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from . import cards, dossiers, memory, office
from . import snapshot as _snapshot  # noqa: F401 —— 导入即登记 product_gate 指纹,批卡前才能查数据变没变
from .constants import MEMORY_KINDS
from .models import SqhDossier, SqhGoal, SqhMemory, SqhSnapshot

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


def _memory_item(row: SqhMemory) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "subject": row.subject,
        "body": row.body,
        "refs": row.refs or {},
        "source": row.source,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _headline(payload: Any) -> str | None:
    return payload.get("headline") if isinstance(payload, dict) else None


@router.get("/memory")
def get_memory(
    kind: str | None = Query(default=None, max_length=16),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """书柜:她的硬记忆。任何登录的人都能翻(办公室本来就全站可看)。"""
    del user
    if kind is not None and kind not in MEMORY_KINDS:
        raise HTTPException(status_code=422, detail={"code": "SQH_MEMORY_KIND_INVALID", "message": f"没有这种记忆:{kind}"})
    question = (q or "").strip()
    if question:
        rows = memory.relevant(db, question, limit=200 if kind else limit)
        if kind:
            rows = [row for row in rows if row.kind == kind][:limit]
    else:
        rows = memory.recent(db, limit=limit, kinds=(kind,) if kind else None)
    return {"items": [_memory_item(row) for row in rows]}


@router.get("/snapshots")
def list_snapshots(
    limit: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """日历:每天一份全局快照的标题。"""
    del user
    rows = db.scalars(
        select(SqhSnapshot).order_by(SqhSnapshot.snapshot_date.desc()).limit(limit),
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    return {
        "items": [
            {
                "date": row.snapshot_date.isoformat(),
                "headline": _headline(row.payload),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.get("/snapshots/{snapshot_date}")
def get_snapshot(snapshot_date: date, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    del user
    row = db.get(SqhSnapshot, snapshot_date, execution_options=SKIP_ORG_DATA_ISOLATION)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "SQH_SNAPSHOT_NOT_FOUND", "message": "那天没有快照。"})
    return {"date": row.snapshot_date.isoformat(), "headline": _headline(row.payload), "payload": row.payload}


@router.post("/cards/{ref}/decide")
def decide(ref: str, body: DecideBody, db: Session = Depends(get_db), owner: User = Depends(require_owner)) -> dict[str, Any]:
    try:
        outcome = cards.decide_card(db, card_id=ref, decision=body.decision, actor=owner, channel="web", reason=body.reason)
    except cards.CardError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    db.commit()
    return {"changed": outcome.changed, "card": cards.card_payload(outcome.card), "execution": outcome.execution}


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


# ---------------------------------------------------------------- 1688 → K 档案


class DossierBody(BaseModel):
    url: str = Field(min_length=8, max_length=1000)


@router.post("/dossiers")
def submit_dossier(body: DossierBody, db: Session = Depends(get_db), owner: User = Depends(require_owner)) -> dict[str, Any]:
    try:
        dossier, created, position = dossiers.enqueue(db, url=body.url, actor_user_id=str(owner.id), channel="web")
    except dossiers.DossierError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "SQH_DOSSIER_NOT_1688", "message": str(exc)}) from exc
    db.commit()
    return {
        **dossiers.summary_payload(dossier),
        "created": created,
        "position": position,
        "reply": dossiers.queue_reply(position, created=created, status=dossier.status),
    }


@router.post("/dossiers/{dossier_id}/redo")
def redo_dossier(dossier_id: int, db: Session = Depends(get_db), owner: User = Depends(require_owner)) -> dict[str, Any]:
    try:
        dossier, created, position = dossiers.redo(db, dossier_id=dossier_id, actor=owner)
    except dossiers.DossierError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "SQH_DOSSIER_REDO_REFUSED", "message": str(exc)}) from exc
    except cards.CardError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    db.commit()
    return {
        **dossiers.summary_payload(dossier),
        "created": created,
        "position": position,
        "reply": dossiers.queue_reply(position, created=created, status=dossier.status),
    }


@router.get("/dossiers")
def list_dossiers(
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    rows = db.scalars(
        select(SqhDossier).order_by(SqhDossier.id.desc()).limit(limit),
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    return {"items": [dossiers.summary_payload(row) for row in rows]}


@router.get("/dossiers/{dossier_id}")
def get_dossier(dossier_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = db.get(SqhDossier, dossier_id, execution_options=SKIP_ORG_DATA_ISOLATION)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "SQH_DOSSIER_NOT_FOUND", "message": "没有这份档案。"})
    return dossiers.detail_payload(row)
