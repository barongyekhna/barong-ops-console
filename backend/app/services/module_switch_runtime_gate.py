from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from ..schemas.module_switch import (
    ModuleSwitchIntegrationPoint,
    ModuleSwitchRegistryRecord,
    ModuleSwitchRuntimeDecision,
    ModuleSwitchRuntimeStatus,
)
from .emergency_kill_switch import (
    EmergencyKillSwitchGate,
    GLOBAL_KILL_SWITCH_BLOCK_REASON,
)
from .module_switch_policy_engine import build_effective_module_switch_registry


class ModuleSwitchRuntimeBlockedError(ValueError):
    def __init__(self, decision: ModuleSwitchRuntimeDecision) -> None:
        self.decision = decision
        super().__init__(
            f"BLOCKED by Module Switch: {decision.module_key} "
            f"{decision.switch_status} ({decision.reason})"
        )


class ModuleSwitchRuntimeGate:
    """C13B fail-closed runtime gate for module switch enforcement."""

    def __init__(
        self,
        registry: Sequence[ModuleSwitchRegistryRecord | Mapping[str, Any]]
        | None = None,
        global_kill_switch: bool | None = None,
    ) -> None:
        self._kill_switch_gate = EmergencyKillSwitchGate(
            global_kill_switch=global_kill_switch
        )
        self._records: dict[str, ModuleSwitchRegistryRecord] = {}
        self._invalid_reasons: dict[str, str] = {}
        if self._kill_switch_gate.global_kill_switch:
            return
        raw_records = (
            registry
            if registry is not None
            else build_effective_module_switch_registry()
        )
        for raw_record in raw_records:
            module_key = self._raw_module_key(raw_record)
            if not module_key:
                continue
            if module_key in self._records or module_key in self._invalid_reasons:
                self._invalid_reasons[module_key] = "module_switch_duplicate"
                self._records.pop(module_key, None)
                continue
            try:
                self._records[module_key] = self._record_from_raw(raw_record)
            except (TypeError, ValueError, ValidationError):
                self._invalid_reasons[module_key] = "module_switch_invalid_state"

    def check(self, module_key: str) -> ModuleSwitchRuntimeStatus:
        return self.decision(module_key).switch_status

    def decision(
        self,
        module_key: str,
        *,
        integration_point: ModuleSwitchIntegrationPoint | None = None,
    ) -> ModuleSwitchRuntimeDecision:
        evaluated_at = datetime.now(UTC)
        kill_switch_decision = self._kill_switch_gate.decision(
            integration_point=integration_point,
        )
        if kill_switch_decision.enforcement_result == "BLOCKED":
            return self._blocked(
                module_key=module_key or "global_kill_switch",
                state="GLOBAL_KILL_SWITCH",
                reason=GLOBAL_KILL_SWITCH_BLOCK_REASON,
                evaluated_at=evaluated_at,
                integration_point=integration_point,
            )

        if not module_key:
            return self._blocked(
                module_key="missing_module_key",
                state="MISSING",
                reason="module_switch_missing_module_key",
                evaluated_at=evaluated_at,
                integration_point=integration_point,
            )

        if module_key in self._invalid_reasons:
            return self._blocked(
                module_key=module_key,
                state="INVALID",
                reason=self._invalid_reasons[module_key],
                evaluated_at=evaluated_at,
                integration_point=integration_point,
            )

        record = self._records.get(module_key)
        if record is None:
            return self._blocked(
                module_key=module_key,
                state="MISSING",
                reason="module_switch_not_registered",
                evaluated_at=evaluated_at,
                integration_point=integration_point,
            )

        if record.state == "ON" and record.enabled is True:
            return ModuleSwitchRuntimeDecision(
                module_key=record.module_key,
                switch_status="ON",
                enforcement_result="ALLOWED",
                state=record.state,
                enabled=True,
                reason="module_switch_on",
                integration_point=integration_point,
                evaluated_at=evaluated_at,
                execution_chain_stopped=False,
                approval_request_allowed=True,
                execution_request_allowed=True,
                sandbox_entry_allowed=True,
            )

        reason_by_state = {
            "OFF": "module_switch_off",
            "DEPRECATED": "module_switch_deprecated",
            "MAINTENANCE": "module_switch_maintenance",
        }
        return self._blocked(
            module_key=record.module_key,
            state=record.state,
            reason=reason_by_state.get(record.state, "module_switch_invalid_state"),
            evaluated_at=evaluated_at,
            integration_point=integration_point,
        )

    def enforce(
        self,
        module_key: str,
        *,
        integration_point: ModuleSwitchIntegrationPoint | None = None,
    ) -> ModuleSwitchRuntimeDecision:
        decision = self.decision(
            module_key,
            integration_point=integration_point,
        )
        if decision.enforcement_result == "BLOCKED":
            raise ModuleSwitchRuntimeBlockedError(decision)
        return decision

    def enforce_before_c08_module_resolution(
        self,
        module_key: str,
    ) -> ModuleSwitchRuntimeDecision:
        return self.enforce(
            module_key,
            integration_point="c08_module_resolution",
        )

    def enforce_before_c12_approval_request(
        self,
        module_key: str,
    ) -> ModuleSwitchRuntimeDecision:
        return self.enforce(
            module_key,
            integration_point="c12_approval_request",
        )

    def enforce_before_c09_execution_request(
        self,
        module_key: str,
    ) -> ModuleSwitchRuntimeDecision:
        return self.enforce(
            module_key,
            integration_point="c09_execution_request",
        )

    def enforce_before_c10_sandbox_entry(
        self,
        module_key: str,
    ) -> ModuleSwitchRuntimeDecision:
        return self.enforce(
            module_key,
            integration_point="c10_sandbox_entry",
        )

    def _blocked(
        self,
        *,
        module_key: str,
        state: str,
        reason: str,
        evaluated_at: datetime,
        integration_point: ModuleSwitchIntegrationPoint | None,
    ) -> ModuleSwitchRuntimeDecision:
        return ModuleSwitchRuntimeDecision(
            module_key=module_key,
            switch_status="OFF",
            enforcement_result="BLOCKED",
            state=state,
            enabled=False,
            reason=reason,
            integration_point=integration_point,
            evaluated_at=evaluated_at,
            execution_chain_stopped=True,
            approval_request_allowed=False,
            execution_request_allowed=False,
            sandbox_entry_allowed=False,
        )

    @staticmethod
    def _record_from_raw(
        raw_record: ModuleSwitchRegistryRecord | Mapping[str, Any],
    ) -> ModuleSwitchRegistryRecord:
        if isinstance(raw_record, ModuleSwitchRegistryRecord):
            return raw_record
        return ModuleSwitchRegistryRecord.model_validate(raw_record)

    @staticmethod
    def _raw_module_key(
        raw_record: ModuleSwitchRegistryRecord | Mapping[str, Any],
    ) -> str:
        if isinstance(raw_record, ModuleSwitchRegistryRecord):
            return raw_record.module_key
        value = raw_record.get("module_key")
        return str(value) if value is not None else ""


def check_module_switch(module_key: str) -> ModuleSwitchRuntimeStatus:
    return ModuleSwitchRuntimeGate().check(module_key)


def enforce_module_switch_before_c08_module_resolution(
    module_key: str,
) -> ModuleSwitchRuntimeDecision:
    return ModuleSwitchRuntimeGate().enforce_before_c08_module_resolution(module_key)


def enforce_module_switch_before_c12_approval_request(
    module_key: str,
) -> ModuleSwitchRuntimeDecision:
    return ModuleSwitchRuntimeGate().enforce_before_c12_approval_request(module_key)


def enforce_module_switch_before_c09_execution_request(
    module_key: str,
) -> ModuleSwitchRuntimeDecision:
    return ModuleSwitchRuntimeGate().enforce_before_c09_execution_request(module_key)


def enforce_module_switch_before_c10_sandbox_entry(
    module_key: str,
) -> ModuleSwitchRuntimeDecision:
    return ModuleSwitchRuntimeGate().enforce_before_c10_sandbox_entry(module_key)
