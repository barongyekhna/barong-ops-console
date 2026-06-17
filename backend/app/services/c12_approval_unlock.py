from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.approval import ApprovalRequestRecord
from ..models.ops import OpsExecutionUnlockTokenRecord
from ..schemas.live_gate import ApprovalUnlockDecision

UNLOCK_TOKEN_TTL_MINUTES = 30
APPROVED_STATES = frozenset(("approved", "auto_approved"))
BLOCKED_STATES = frozenset(("rejected",))
PENDING_STATES = frozenset(("pending",))


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_unlock_id() -> str:
    return f"unlock-{uuid4()}"


def _new_token() -> str:
    return f"live-unlock-{token_urlsafe(32)}"


def _token_hash(
    *,
    org_id: str,
    approval_id: str,
    execution_id: str,
    token: str,
) -> str:
    payload = "|".join((org_id, approval_id, execution_id, token))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class C12ApprovalUnlockTokenController:
    """Binds C12 terminal approval state to explicit live unlock tokens."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def sync_from_approval(
        self,
        *,
        org_id: str,
        approval_id: str,
        reveal_token: bool = False,
    ) -> ApprovalUnlockDecision:
        approval = self._approval_record(org_id=org_id, approval_id=approval_id)
        if approval is None:
            return self._decision(
                decision="missing",
                status="missing",
                approval_id=approval_id,
                execution_id=None,
                reason="C12 approval record was not found.",
            )

        if approval.status in PENDING_STATES:
            record = self._upsert_status_record(
                org_id=org_id,
                approval=approval,
                status="pending",
                reason="C12 approval is pending; live unlock is denied.",
            )
            return self._decision_from_record(
                record,
                decision="denied",
                reason="C12 approval is pending; live unlock is denied.",
            )

        if approval.status in BLOCKED_STATES:
            record = self._upsert_status_record(
                org_id=org_id,
                approval=approval,
                status="rejected",
                reason="C12 approval was rejected; live execution is blocked.",
            )
            return self._decision_from_record(
                record,
                decision="blocked",
                reason="C12 approval was rejected; live execution is blocked.",
            )

        if approval.status not in APPROVED_STATES:
            record = self._upsert_status_record(
                org_id=org_id,
                approval=approval,
                status=approval.status,
                reason=f"C12 approval status '{approval.status}' cannot unlock live.",
            )
            return self._decision_from_record(
                record,
                decision="denied",
                reason=f"C12 approval status '{approval.status}' cannot unlock live.",
            )

        existing = self._active_unlock_record(
            org_id=org_id,
            approval_id=approval.approval_id,
            execution_id=approval.execution_id,
        )
        if existing is not None:
            return self._decision_from_record(
                existing,
                decision="unlocked",
                reason="C12 approval is approved and already bound to an unlock token.",
                unlock_token=None,
            )

        token = _new_token()
        issued_at = _utc_now()
        expires_at = issued_at + timedelta(minutes=UNLOCK_TOKEN_TTL_MINUTES)
        record = OpsExecutionUnlockTokenRecord(
            org_id=org_id,
            unlock_id=_new_unlock_id(),
            approval_id=approval.approval_id,
            execution_id=approval.execution_id,
            token_hash=_token_hash(
                org_id=org_id,
                approval_id=approval.approval_id,
                execution_id=approval.execution_id,
                token=token,
            ),
            status="approved",
            reason="C12 approval granted explicit live execution unlock.",
            issued_at=issued_at,
            expires_at=expires_at,
            payload={
                "approval_status": approval.status,
                "module_key": approval.module_key,
                "adapter_key": approval.adapter_key,
                "action_key": approval.action_key,
                "risk_level": approval.risk_level,
            },
        )
        self.db.add(record)
        self.db.flush()
        return self._decision_from_record(
            record,
            decision="unlocked",
            reason="C12 approval granted explicit live execution unlock.",
            unlock_token=token if reveal_token else None,
        )

    def validate_unlock(
        self,
        *,
        org_id: str,
        approval_id: str | None,
        execution_id: str | None,
        unlock_token: str | None,
    ) -> ApprovalUnlockDecision:
        if not approval_id:
            return self._decision(
                decision="missing",
                status="missing",
                approval_id=None,
                execution_id=execution_id,
                reason="Live execution requires a C12 approval_id.",
            )
        approval = self._approval_record(org_id=org_id, approval_id=approval_id)
        if approval is None:
            return self._decision(
                decision="missing",
                status="missing",
                approval_id=approval_id,
                execution_id=execution_id,
                reason="C12 approval record was not found.",
            )
        if approval.status in PENDING_STATES:
            self.sync_from_approval(org_id=org_id, approval_id=approval_id)
            return self._decision(
                decision="denied",
                status="pending",
                approval_id=approval_id,
                execution_id=approval.execution_id,
                reason="C12 approval is pending; live execution is denied.",
            )
        if approval.status in BLOCKED_STATES:
            self.sync_from_approval(org_id=org_id, approval_id=approval_id)
            return self._decision(
                decision="blocked",
                status="rejected",
                approval_id=approval_id,
                execution_id=approval.execution_id,
                reason="C12 approval was rejected; live execution is blocked.",
            )
        if approval.status not in APPROVED_STATES:
            return self._decision(
                decision="denied",
                status=approval.status,
                approval_id=approval_id,
                execution_id=approval.execution_id,
                reason=f"C12 approval status '{approval.status}' cannot unlock live.",
            )
        if execution_id and execution_id != approval.execution_id:
            return self._decision(
                decision="invalid",
                status=approval.status,
                approval_id=approval_id,
                execution_id=execution_id,
                reason="Unlock execution_id does not match the C12 approval binding.",
            )
        if not unlock_token:
            return self._decision(
                decision="missing",
                status=approval.status,
                approval_id=approval_id,
                execution_id=approval.execution_id,
                reason="Live execution requires an explicit unlock token.",
            )

        record = self._active_unlock_record(
            org_id=org_id,
            approval_id=approval.approval_id,
            execution_id=approval.execution_id,
        )
        if record is None:
            return self._decision(
                decision="missing",
                status=approval.status,
                approval_id=approval_id,
                execution_id=approval.execution_id,
                reason="Approved C12 request has no active unlock token.",
            )
        if record.expires_at is not None and record.expires_at <= _utc_now():
            record.status = "expired"
            record.reason = "C12 unlock token expired."
            self.db.flush()
            return self._decision_from_record(
                record,
                decision="denied",
                reason="C12 unlock token expired.",
            )
        expected = _token_hash(
            org_id=org_id,
            approval_id=approval.approval_id,
            execution_id=approval.execution_id,
            token=unlock_token,
        )
        if not record.token_hash or not hmac.compare_digest(record.token_hash, expected):
            return self._decision_from_record(
                record,
                decision="invalid",
                reason="C12 unlock token does not match the approval binding.",
            )
        return self._decision_from_record(
            record,
            decision="unlocked",
            reason="C12 approval and unlock token are valid.",
        )

    def describe_approval(
        self,
        *,
        org_id: str,
        approval_id: str,
    ) -> ApprovalUnlockDecision:
        approval = self._approval_record(org_id=org_id, approval_id=approval_id)
        if approval is None:
            return self._decision(
                decision="missing",
                status="missing",
                approval_id=approval_id,
                execution_id=None,
                reason="C12 approval record was not found.",
            )
        if approval.status in PENDING_STATES:
            return self._decision(
                decision="denied",
                status="pending",
                approval_id=approval_id,
                execution_id=approval.execution_id,
                reason="C12 approval is pending; live unlock is denied.",
            )
        if approval.status in BLOCKED_STATES:
            return self._decision(
                decision="blocked",
                status="rejected",
                approval_id=approval_id,
                execution_id=approval.execution_id,
                reason="C12 approval was rejected; live execution is blocked.",
            )
        if approval.status in APPROVED_STATES:
            record = self._active_unlock_record(
                org_id=org_id,
                approval_id=approval.approval_id,
                execution_id=approval.execution_id,
            )
            if record is None:
                return self._decision(
                    decision="missing",
                    status=approval.status,
                    approval_id=approval_id,
                    execution_id=approval.execution_id,
                    reason="Approved C12 request has no active unlock token.",
                )
            return self._decision_from_record(
                record,
                decision="unlocked",
                reason="C12 approval is bound to an active unlock token.",
            )
        return self._decision(
            decision="denied",
            status=approval.status,
            approval_id=approval_id,
            execution_id=approval.execution_id,
            reason=f"C12 approval status '{approval.status}' cannot unlock live.",
        )

    @staticmethod
    def not_required(*, execution_id: str | None = None) -> ApprovalUnlockDecision:
        return ApprovalUnlockDecision(
            decision="not_required",
            approval_id=None,
            execution_id=execution_id,
            unlock_id=None,
            unlock_token=None,
            status="not_required",
            reason="C12 live unlock is not required for mock or staging mode.",
        )

    def _approval_record(
        self,
        *,
        org_id: str,
        approval_id: str,
    ) -> ApprovalRequestRecord | None:
        return self.db.scalar(
            select(ApprovalRequestRecord).where(
                ApprovalRequestRecord.org_id == org_id,
                ApprovalRequestRecord.approval_id == approval_id,
            )
        )

    def _active_unlock_record(
        self,
        *,
        org_id: str,
        approval_id: str,
        execution_id: str,
    ) -> OpsExecutionUnlockTokenRecord | None:
        return self.db.scalar(
            select(OpsExecutionUnlockTokenRecord)
            .where(
                OpsExecutionUnlockTokenRecord.org_id == org_id,
                OpsExecutionUnlockTokenRecord.approval_id == approval_id,
                OpsExecutionUnlockTokenRecord.execution_id == execution_id,
                OpsExecutionUnlockTokenRecord.status == "approved",
            )
            .order_by(OpsExecutionUnlockTokenRecord.id.desc())
        )

    def _upsert_status_record(
        self,
        *,
        org_id: str,
        approval: ApprovalRequestRecord,
        status: str,
        reason: str,
    ) -> OpsExecutionUnlockTokenRecord:
        record = self.db.scalar(
            select(OpsExecutionUnlockTokenRecord)
            .where(
                OpsExecutionUnlockTokenRecord.org_id == org_id,
                OpsExecutionUnlockTokenRecord.approval_id == approval.approval_id,
                OpsExecutionUnlockTokenRecord.execution_id == approval.execution_id,
            )
            .order_by(OpsExecutionUnlockTokenRecord.id.desc())
        )
        if record is None:
            record = OpsExecutionUnlockTokenRecord(
                org_id=org_id,
                unlock_id=_new_unlock_id(),
                approval_id=approval.approval_id,
                execution_id=approval.execution_id,
                token_hash=None,
                status=status,
                reason=reason,
                payload={"approval_status": approval.status},
            )
        else:
            record.status = status
            record.reason = reason
            record.token_hash = None
        self.db.add(record)
        self.db.flush()
        return record

    def _decision_from_record(
        self,
        record: OpsExecutionUnlockTokenRecord,
        *,
        decision: str,
        reason: str,
        unlock_token: str | None = None,
    ) -> ApprovalUnlockDecision:
        return ApprovalUnlockDecision(
            decision=decision,  # type: ignore[arg-type]
            approval_id=record.approval_id,
            execution_id=record.execution_id,
            unlock_id=record.unlock_id,
            unlock_token=unlock_token,
            status=record.status,
            reason=reason,
            issued_at=record.issued_at,
            expires_at=record.expires_at,
        )

    def _decision(
        self,
        *,
        decision: str,
        status: str,
        approval_id: str | None,
        execution_id: str | None,
        reason: str,
    ) -> ApprovalUnlockDecision:
        return ApprovalUnlockDecision(
            decision=decision,  # type: ignore[arg-type]
            approval_id=approval_id,
            execution_id=execution_id,
            unlock_id=None,
            unlock_token=None,
            status=status,
            reason=reason,
        )
