from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db.migration_safety import build_migration_safety_report
from ..db.session import engine as default_engine
from ..models.ops import OpsRollbackGuardRecord
from ..schemas.live_gate import RollbackGuardDecision

DEFAULT_FAILURE_THRESHOLD = 3


class LiveRollbackGuard:
    """Failure detector and rollback trigger state machine for live rollout."""

    def __init__(
        self,
        db: Session | None = None,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    ) -> None:
        self.db = db
        self.failure_threshold = max(failure_threshold, 1)

    def record_failure(
        self,
        *,
        org_id: str,
        environment: str,
        service: str,
        current_version: str | None,
        previous_version: str | None,
        image_digest: str | None,
        db_revision: str | None,
        reason: str,
    ) -> RollbackGuardDecision:
        record = self._load_or_create(
            org_id=org_id,
            environment=environment,
            service=service,
            current_version=current_version,
            previous_version=previous_version,
            image_digest=image_digest,
            db_revision=db_revision,
        )
        record.failure_count = int(record.failure_count or 0) + 1
        record.status = "failure_detected"
        record.consistency_payload = {
            **dict(record.consistency_payload or {}),
            "last_failure_reason": reason,
            "last_failure_at": datetime.now(UTC).isoformat(),
        }
        decision = self._decision_for_record(record)
        if decision.action == "trigger_rollback":
            record.status = "rollback_triggered"
            record.rollback_triggered_at = datetime.now(UTC)
            record.restored_version = record.previous_version
        if self.db is not None:
            self.db.add(record)
            self.db.flush()
        return self._decision_for_record(record)

    def verify_consistency(
        self,
        *,
        org_id: str,
        environment: str,
        service: str,
        expected_image_digest: str | None = None,
        expected_db_revision: str | None = None,
    ) -> RollbackGuardDecision:
        record = self._latest(org_id=org_id, environment=environment, service=service)
        db_consistent = self._db_consistent(expected_db_revision)
        image_consistent = (
            expected_image_digest is None
            or record is None
            or record.image_digest == expected_image_digest
        )
        if record is not None:
            record.consistency_payload = {
                **dict(record.consistency_payload or {}),
                "db_consistent": db_consistent,
                "image_consistent": image_consistent,
                "checked_at": datetime.now(UTC).isoformat(),
            }
            if self.db is not None:
                self.db.add(record)
                self.db.flush()
        return RollbackGuardDecision(
            action="none" if db_consistent and image_consistent else "watch",
            reason=(
                "DB and image consistency checks passed."
                if db_consistent and image_consistent
                else "DB or image consistency check failed."
            ),
            failure_count=int(record.failure_count if record is not None else 0),
            previous_version=record.previous_version if record is not None else None,
            restored_version=record.restored_version if record is not None else None,
            db_consistent=db_consistent,
            image_consistent=image_consistent,
            rollback_triggered=(
                record is not None and record.rollback_triggered_at is not None
            ),
            metadata=dict(record.consistency_payload or {}) if record is not None else {},
        )

    def restore_previous_version(
        self,
        *,
        org_id: str,
        environment: str,
        service: str,
    ) -> RollbackGuardDecision:
        record = self._latest(org_id=org_id, environment=environment, service=service)
        if record is None or not record.previous_version:
            return RollbackGuardDecision(
                action="watch",
                reason="No previous version is available to restore.",
                failure_count=0,
                previous_version=None,
                restored_version=None,
                db_consistent=False,
                image_consistent=False,
                rollback_triggered=False,
                metadata={},
            )
        record.status = "previous_version_restored"
        record.restored_version = record.previous_version
        record.rollback_triggered_at = record.rollback_triggered_at or datetime.now(UTC)
        if self.db is not None:
            self.db.add(record)
            self.db.flush()
        return RollbackGuardDecision(
            action="restore_previous",
            reason="Previous version restore was recorded by rollback guard.",
            failure_count=int(record.failure_count or 0),
            previous_version=record.previous_version,
            restored_version=record.restored_version,
            db_consistent=self._db_consistent(record.db_revision),
            image_consistent=True,
            rollback_triggered=True,
            metadata=dict(record.consistency_payload or {}),
        )

    def _decision_for_record(
        self,
        record: OpsRollbackGuardRecord,
    ) -> RollbackGuardDecision:
        db_consistent = self._db_consistent(record.db_revision)
        image_consistent = bool(record.image_digest or record.current_version)
        threshold_met = int(record.failure_count or 0) >= self.failure_threshold
        return RollbackGuardDecision(
            action="trigger_rollback" if threshold_met else "watch",
            reason=(
                "Failure threshold reached; rollback trigger recorded."
                if threshold_met
                else "Failure detected; watching until rollback threshold is reached."
            ),
            failure_count=int(record.failure_count or 0),
            previous_version=record.previous_version,
            restored_version=record.restored_version,
            db_consistent=db_consistent,
            image_consistent=image_consistent,
            rollback_triggered=record.rollback_triggered_at is not None or threshold_met,
            metadata=dict(record.consistency_payload or {}),
        )

    def _load_or_create(
        self,
        *,
        org_id: str,
        environment: str,
        service: str,
        current_version: str | None,
        previous_version: str | None,
        image_digest: str | None,
        db_revision: str | None,
    ) -> OpsRollbackGuardRecord:
        record = self._latest(org_id=org_id, environment=environment, service=service)
        if record is not None:
            record.current_version = current_version or record.current_version
            record.previous_version = previous_version or record.previous_version
            record.image_digest = image_digest or record.image_digest
            record.db_revision = db_revision or record.db_revision
            return record
        return OpsRollbackGuardRecord(
            org_id=org_id,
            guard_id=f"rollback-guard-{uuid4()}",
            environment=environment,
            service=service,
            current_version=current_version,
            previous_version=previous_version,
            restored_version=None,
            image_digest=image_digest,
            db_revision=db_revision,
            status="watch",
            failure_count=0,
            consistency_payload={},
        )

    def _latest(
        self,
        *,
        org_id: str,
        environment: str,
        service: str,
    ) -> OpsRollbackGuardRecord | None:
        if self.db is None:
            return None
        return self.db.scalar(
            select(OpsRollbackGuardRecord)
            .where(
                OpsRollbackGuardRecord.org_id == org_id,
                OpsRollbackGuardRecord.environment == environment,
                OpsRollbackGuardRecord.service == service,
            )
            .order_by(OpsRollbackGuardRecord.id.desc())
        )

    def _db_consistent(self, expected_db_revision: str | None) -> bool:
        try:
            report = build_migration_safety_report(
                default_engine,
                app_env=get_settings().app_env,
            )
        except Exception:
            return False
        if expected_db_revision:
            return expected_db_revision in report.current_revisions
        return report.clean
