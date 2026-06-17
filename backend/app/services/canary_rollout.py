from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.ops import OpsCanaryRolloutRecord
from ..schemas.live_gate import CanaryRouteDecision, LiveExecutionMode

PLATFORM_ORG_ID = "platform"


@dataclass(frozen=True)
class CanaryRolloutRule:
    scope_type: str
    scope_key: str
    stage: LiveExecutionMode
    enabled: bool
    percentage: int = 0
    org_ids: tuple[str, ...] = ()
    module_ids: tuple[str, ...] = ()


def _bucket(*, org_id: str, module_id: str, execution_id: str | None) -> int:
    key = "|".join((org_id, module_id, execution_id or "no-execution-id"))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


class CanaryRolloutSystem:
    """Deterministic mock -> staging -> live rollout router."""

    def __init__(
        self,
        db: Session | None = None,
        *,
        rules: Iterable[CanaryRolloutRule] | None = None,
    ) -> None:
        self.db = db
        self._rules = tuple(rules or ())

    def route(
        self,
        *,
        org_id: str,
        module_id: str,
        requested_mode: LiveExecutionMode,
        execution_id: str | None = None,
    ) -> CanaryRouteDecision:
        bucket = _bucket(
            org_id=org_id,
            module_id=module_id,
            execution_id=execution_id,
        )
        if requested_mode == "mock":
            return self._decision(
                requested_mode=requested_mode,
                routed_mode="mock",
                percentage=100,
                org_allowed=True,
                module_allowed=True,
                org_rule_matched=False,
                module_rule_matched=False,
                bucket=bucket,
                reason="Mock mode remains on the safe mock stage.",
            )
        if requested_mode == "staging":
            return self._decision(
                requested_mode=requested_mode,
                routed_mode="staging",
                percentage=100,
                org_allowed=True,
                module_allowed=True,
                org_rule_matched=False,
                module_rule_matched=False,
                bucket=bucket,
                reason="Staging mode remains on the staging stage.",
            )

        rule = self._live_rule(org_id=org_id, module_id=module_id)
        if rule is None:
            return self._decision(
                requested_mode=requested_mode,
                routed_mode="staging",
                percentage=0,
                org_allowed=False,
                module_allowed=False,
                org_rule_matched=False,
                module_rule_matched=False,
                bucket=bucket,
                reason="No active live canary rollout matched; routing to staging.",
            )

        org_rule_matched = bool(rule.org_ids)
        module_rule_matched = bool(rule.module_ids)
        org_allowed = not rule.org_ids or org_id in rule.org_ids
        module_allowed = not rule.module_ids or module_id in rule.module_ids
        percentage = min(max(int(rule.percentage), 0), 100)
        live_selected = (
            rule.enabled
            and rule.stage == "live"
            and org_allowed
            and module_allowed
            and bucket < percentage
        )
        return self._decision(
            requested_mode=requested_mode,
            routed_mode="live" if live_selected else "staging",
            percentage=percentage,
            org_allowed=org_allowed,
            module_allowed=module_allowed,
            org_rule_matched=org_rule_matched,
            module_rule_matched=module_rule_matched,
            bucket=bucket,
            reason=(
                "Live canary matched; routing to live."
                if live_selected
                else "Live canary did not fully match; routing to staging."
            ),
        )

    def upsert_rule(
        self,
        *,
        org_id: str,
        scope_type: str,
        scope_key: str,
        stage: LiveExecutionMode,
        enabled: bool,
        percentage: int,
        org_ids: tuple[str, ...] = (),
        module_ids: tuple[str, ...] = (),
    ) -> OpsCanaryRolloutRecord:
        if self.db is None:
            raise ValueError("Canary rollout persistence requires a database session.")
        record = self.db.scalar(
            select(OpsCanaryRolloutRecord).where(
                OpsCanaryRolloutRecord.org_id == org_id,
                OpsCanaryRolloutRecord.scope_type == scope_type,
                OpsCanaryRolloutRecord.scope_key == scope_key,
            )
        )
        if record is None:
            record = OpsCanaryRolloutRecord(
                org_id=org_id,
                rollout_id=f"canary-{uuid4()}",
                scope_type=scope_type,
                scope_key=scope_key,
                stage=stage,
                enabled=enabled,
                percentage=percentage,
                org_ids=list(org_ids),
                module_ids=list(module_ids),
                status="active",
                payload={},
            )
        else:
            record.stage = stage
            record.enabled = enabled
            record.percentage = percentage
            record.org_ids = list(org_ids)
            record.module_ids = list(module_ids)
            record.status = "active"
        self.db.add(record)
        self.db.flush()
        return record

    def _live_rule(
        self,
        *,
        org_id: str,
        module_id: str,
    ) -> CanaryRolloutRule | None:
        candidates = [rule for rule in self._rules if rule.enabled and rule.stage == "live"]
        if self.db is not None:
            candidates.extend(self._db_rules(org_id=org_id, module_id=module_id))
        scoped = [
            rule
            for rule in candidates
            if rule.scope_type == "global"
            or (rule.scope_type == "org" and rule.scope_key == org_id)
            or (rule.scope_type == "module" and rule.scope_key == module_id)
        ]
        if not scoped:
            return None
        return sorted(
            scoped,
            key=lambda rule: (
                {"module": 0, "org": 1, "global": 2}.get(rule.scope_type, 3),
                -rule.percentage,
            ),
        )[0]

    def _db_rules(
        self,
        *,
        org_id: str,
        module_id: str,
    ) -> list[CanaryRolloutRule]:
        if self.db is None:
            return []
        rows = list(
            self.db.scalars(
                select(OpsCanaryRolloutRecord).where(
                    OpsCanaryRolloutRecord.org_id.in_((org_id, PLATFORM_ORG_ID)),
                    OpsCanaryRolloutRecord.status == "active",
                    OpsCanaryRolloutRecord.enabled.is_(True),
                    OpsCanaryRolloutRecord.stage == "live",
                    OpsCanaryRolloutRecord.scope_type.in_(
                        ("global", "org", "module")
                    ),
                )
            )
        )
        rules: list[CanaryRolloutRule] = []
        for row in rows:
            if row.scope_type == "org" and row.scope_key != org_id:
                continue
            if row.scope_type == "module" and row.scope_key != module_id:
                continue
            rules.append(
                CanaryRolloutRule(
                    scope_type=row.scope_type,
                    scope_key=row.scope_key,
                    stage=row.stage,  # type: ignore[arg-type]
                    enabled=row.enabled,
                    percentage=row.percentage,
                    org_ids=tuple(row.org_ids or ()),
                    module_ids=tuple(row.module_ids or ()),
                )
            )
        return rules

    def _decision(
        self,
        *,
        requested_mode: LiveExecutionMode,
        routed_mode: LiveExecutionMode,
        percentage: int,
        org_allowed: bool,
        module_allowed: bool,
        org_rule_matched: bool,
        module_rule_matched: bool,
        bucket: int,
        reason: str,
    ) -> CanaryRouteDecision:
        return CanaryRouteDecision(
            requested_mode=requested_mode,
            routed_mode=routed_mode,
            stage=routed_mode,
            percentage_rollout=percentage,
            org_allowed=org_allowed,
            module_allowed=module_allowed,
            org_rule_matched=org_rule_matched,
            module_rule_matched=module_rule_matched,
            deterministic_bucket=bucket,
            reason=reason,
        )
