"""审批卡:建卡、按 owner 的决定改状态。网页 / C19 / MCP 只有 decide_card 这一个入口。

规矩(10-20 用户定):
- 只有 owner 能批;驳回必须写原因(原因进记忆,同类连驳就该提议定规矩)。
- 幂等、先到先得:已经决定过的卡,原样返回第一次的结果(谁、哪个渠道)。
- 批之前看底层数据变没变:卡上存了建卡时的数据指纹,现在重算一遍,不一样就作废成 stale。
- 影子期(10-22 起):批了只记账,不执行任何动作。执行器是第四步的事。
- 一件事只发一张卡(10-26):早间计划的卡上记着快照里那件事的编号(evidence["issue"]),
  卡还没了结就不再发;那件事从快照里消失过,下次再出现才算新的一回。
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ....core.roles import is_owner_role
from ....models.user import User
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from . import memory
from .constants import CARD_CHANNELS, DOSSIER_CARD_KIND
from .models import SqhCard

# 重算指纹的函数:evidence["recheck"]["type"] → fn(db, recheck) -> 指纹。
# 没登记 recheck 的卡不依赖具体数据(比如「今天的计划」),不做这一步。
FINGERPRINTERS: dict[str, Callable[[Session, dict[str, Any]], str]] = {}


class CardError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class DecideOutcome:
    card: SqhCard
    # True = 这一次真的改了状态;False = 早就决定过了(或已作废),原样返回。
    changed: bool
    # 批准后真的动了手(目前只有「建 K 档案」卡):{"ok": bool, "note": str, ...}。
    execution: dict[str, Any] | None = None


def fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def register_fingerprinter(kind: str, fn: Callable[[Session, dict[str, Any]], str]) -> None:
    FINGERPRINTERS[kind] = fn


def _new_ref(db: Session) -> str:
    for _ in range(20):
        ref = secrets.token_hex(2)
        exists = db.scalar(select(SqhCard.id).where(SqhCard.ref == ref), execution_options=SKIP_ORG_DATA_ISOLATION)
        if exists is None:
            return ref
    return secrets.token_hex(4)


def create_card(
    db: Session,
    *,
    dedupe_key: str,
    kind: str,
    title: str,
    conclusion: str,
    why: str = "",
    if_not: str = "",
    reversible: bool = True,
    confidence: str = "medium",
    evidence: dict[str, Any] | None = None,
) -> tuple[SqhCard, bool]:
    """同一个 dedupe_key 只建一次。返回 (卡, 是不是新建的)。"""
    existing = db.scalar(select(SqhCard).where(SqhCard.dedupe_key == dedupe_key[:160]), execution_options=SKIP_ORG_DATA_ISOLATION)
    if existing is not None:
        return existing, False
    evidence = evidence or {}
    recheck = evidence.get("recheck") if isinstance(evidence.get("recheck"), dict) else None
    data_fp = ""
    if recheck and recheck.get("type") in FINGERPRINTERS:
        data_fp = FINGERPRINTERS[recheck["type"]](db, recheck)
    card = SqhCard(
        ref=_new_ref(db),
        dedupe_key=dedupe_key[:160],
        kind=kind[:32],
        title=title[:200],
        conclusion=conclusion,
        why=why,
        if_not=if_not,
        reversible=reversible,
        confidence=confidence if confidence in {"low", "medium", "high"} else "medium",
        evidence=evidence,
        data_fingerprint=data_fp,
        status="pending",
    )
    db.add(card)
    db.flush()
    memory.record(db, kind="suggestion", subject=card.title, body=card.conclusion, refs={"card_ref": card.ref, "kind": card.kind})
    return card, True


def find_card(db: Session, card_id_or_ref: str | int) -> SqhCard | None:
    """只认短号(ref)。短号是 4 位十六进制,可能全是数字,所以不拿它去猜自增 id。"""
    value = str(card_id_or_ref).strip().lstrip("#").lower()
    return db.scalar(select(SqhCard).where(SqhCard.ref == value), execution_options=SKIP_ORG_DATA_ISOLATION)


def decide_card(
    db: Session,
    *,
    card_id: str | int,
    decision: str,
    actor: User,
    channel: str,
    reason: str | None = None,
) -> DecideOutcome:
    if decision not in {"approve", "reject"}:
        raise CardError("SQH_CARD_DECISION_INVALID", "只能批或驳。")
    if channel not in CARD_CHANNELS:
        raise CardError("SQH_CARD_CHANNEL_INVALID", f"未知渠道 {channel}。")
    if not is_owner_role(getattr(actor, "role", "") or ""):
        raise CardError("SQH_OWNER_REQUIRED", "只有老板能批苏青禾的卡。", status_code=403)
    card = find_card(db, card_id)
    if card is None:
        raise CardError("SQH_CARD_NOT_FOUND", "没有这张卡。", status_code=404)
    # 先看是不是已经决定过了:C19 里一句不带原因的「驳 #ref」碰上网页已批的卡,
    # 该告诉老板「已经批过了」,而不是让他补原因。
    if card.status != "pending":
        return DecideOutcome(card=card, changed=False)
    reason = (reason or "").strip()
    if decision == "reject" and not reason:
        raise CardError("SQH_REJECT_REASON_REQUIRED", "驳回要写原因——她会记住,下次不再犯。")

    recheck = card.evidence.get("recheck") if isinstance(card.evidence, dict) else None
    if decision == "approve" and card.data_fingerprint and isinstance(recheck, dict):
        fn = FINGERPRINTERS.get(str(recheck.get("type")))
        current = fn(db, recheck) if fn else None
        if current is not None and current != card.data_fingerprint:
            _transition(db, card, status="stale", actor=actor, channel=channel, reason="建卡后底层数据变了,这张卡作废,她会按新数据重出。")
            return DecideOutcome(card=card, changed=True)

    new_status = "approved" if decision == "approve" else "rejected"
    changed = _transition(db, card, status=new_status, actor=actor, channel=channel, reason=reason or None)
    if changed:
        verdict = "批了" if decision == "approve" else "驳了"
        memory.record(
            db,
            kind="decision",
            subject=card.title,
            body=f"老板{verdict}「{card.title}」" + (f",原因:{reason}" if reason else "") + f"(渠道 {channel})",
            refs={"card_ref": card.ref, "kind": card.kind, "decision": decision, "channel": channel},
            source="human",
            actor_user_id=str(actor.id),
        )
        memory.log_activity(db, f"老板{verdict} #{card.ref}「{card.title}」", kind="decision")
    execution = None
    if changed and card.kind == DOSSIER_CARD_KIND:
        execution = _after_dossier_decision(db, card, decision=decision, actor=actor)
    return DecideOutcome(card=card, changed=changed, execution=execution)


BUILD_QUEUED_NOTE = "我这就把它建进 K,几秒钟;建好在档案柜里能看到 SKU。"


def _after_dossier_decision(db: Session, card: SqhCard, *, decision: str, actor: User) -> dict[str, Any]:
    """「建 K 档案」卡决定之后:驳 → 档案标 rejected;批 → 只落「已批」,真的去建交给 worker(executor.build_approved)。

    10-26:原来在这个请求里同步建 —— K 建档 + 从 1688 CDN 一张张下参考图,老板点一下「批」要等 3–9 秒。
    档案不在「待批」(没得建)照样记一笔执行失败,别让卡悄悄停在「已批」。
    """
    from .executor import record_failure
    from .models import SqhDossier

    dossier_id = (card.evidence or {}).get("dossier_id") if isinstance(card.evidence, dict) else None
    if not dossier_id:
        return {"ok": False, "note": "卡上没有档案号,没法执行。"}
    dossier = db.get(SqhDossier, int(dossier_id), execution_options=SKIP_ORG_DATA_ISOLATION)
    if decision == "reject":
        if dossier is not None and dossier.status == "ready":
            dossier.status = "rejected"
            db.add(dossier)
            db.flush()
        return {"ok": True, "note": "档案已驳回,不建。"}
    if dossier is None or dossier.status != "ready":
        state = "不存在" if dossier is None else f"状态是 {dossier.status}"
        return record_failure(db, card=card, dossier_id=int(dossier_id), message=f"档案 #{dossier_id} {state},不是「待批」,不建。")
    return {"ok": True, "queued": True, "note": BUILD_QUEUED_NOTE}


def _transition(db: Session, card: SqhCard, *, status: str, actor: User, channel: str, reason: str | None) -> bool:
    """条件更新:只有还在 pending 的卡才改。两个渠道同时批,只有一个改得动(先到先得)。"""
    result = db.execute(
        update(SqhCard)
        .where(SqhCard.id == card.id, SqhCard.status == "pending")
        .values(
            status=status,
            decided_by_user_id=str(actor.id),
            decided_via=channel,
            decision_reason=reason,
            decided_at=datetime.now(UTC),
        ),
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    db.flush()
    db.refresh(card)
    return bool(result.rowcount)


# ---------------------------------------------------------------- 一件事一张卡(早间计划的卡)

# 作废原因会原样出现在 C19 里,用她的口吻写。
LEGACY_REASON = "同一件事以前天天发一张,规矩改了:一件事只留一张卡。这张合并掉了,事情要是还在,今天按新规矩重出一张。"
GONE_REASON = "这件事今天的快照里已经没有了,不用再定。"
RETIRE_REASONS = (LEGACY_REASON, GONE_REASON)
_OPEN = ("pending", "approved", "rejected")


def issue_category(issue: str) -> str:
    return issue.split(":", 1)[0]


def _issue_of(card: SqhCard) -> str | None:
    issue = card.evidence.get("issue") if isinstance(card.evidence, dict) else None
    return str(issue) if issue else None


def _open_plan_cards(db: Session) -> list[SqhCard]:
    # 档案卡按档案号管,不走这一套
    return list(
        db.scalars(
            select(SqhCard).where(SqhCard.kind != DOSSIER_CARD_KIND, SqhCard.status.in_(_OPEN)),
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
    )


def raised_issues(db: Session) -> set[str]:
    """已经发过卡、还没了结的事:卡还在等批,或者批过/驳过而那件事还没消失过。"""
    return {
        issue
        for card in _open_plan_cards(db)
        if (issue := _issue_of(card)) and not card.evidence.get("settled_on")
    }


def _retire(db: Session, card: SqhCard, *, status: str, reason: str) -> int:
    """系统作废一张还在等批的卡(不是老板的决定,所以不记人、不记渠道)。条件更新,和 _transition 一样先到先得。"""
    result = db.execute(
        update(SqhCard)
        .where(SqhCard.id == card.id, SqhCard.status == "pending")
        .values(status=status, decision_reason=reason, decided_at=datetime.now(UTC)),
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    return int(result.rowcount or 0)


def settle_issues(db: Session, *, live: set[str], readable: set[str], today: str) -> dict[str, int]:
    """每天早上出计划前对一遍账。

    - 旧规矩发的卡(没有事情编号)还在等批 → expired;那件事要是还在,今天最多再出一张。
    - 卡上那件事今天没了(而且那一类今天读得到)→ 等批的 stale;批过/驳过的记 settled_on,
      以后再出现算新的一回,可以重新发卡。读不到的类别一律不动(读不到 ≠ 没了)。
    """
    counts = {"merged": 0, "gone": 0, "settled": 0}
    for card in _open_plan_cards(db):
        issue = _issue_of(card)
        if issue is None:
            if card.status == "pending":
                counts["merged"] += _retire(db, card, status="expired", reason=LEGACY_REASON)
            continue
        if issue in live or issue_category(issue) not in readable:
            continue
        if card.status == "pending":
            counts["gone"] += _retire(db, card, status="stale", reason=GONE_REASON)
        elif not card.evidence.get("settled_on"):
            card.evidence = {**card.evidence, "settled_on": today}
            db.add(card)
            counts["settled"] += 1
    db.flush()
    return counts


def pending_cards(db: Session, *, limit: int = 50) -> list[SqhCard]:
    return list(
        db.scalars(
            select(SqhCard).where(SqhCard.status == "pending").order_by(SqhCard.created_at.desc()).limit(limit),
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
    )


def card_payload(card: SqhCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "ref": card.ref,
        "kind": card.kind,
        "title": card.title,
        "conclusion": card.conclusion,
        "why": card.why,
        "if_not": card.if_not,
        "reversible": card.reversible,
        "confidence": card.confidence,
        "evidence": card.evidence,
        "status": card.status,
        "decided_via": card.decided_via,
        "decision_reason": card.decision_reason,
        "decided_at": card.decided_at.isoformat() if card.decided_at else None,
        "created_at": card.created_at.isoformat() if card.created_at else None,
    }
