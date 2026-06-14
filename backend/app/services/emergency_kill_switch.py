from __future__ import annotations

from datetime import UTC, datetime

from ..core.roles import is_owner_role
from ..schemas.emergency_kill_switch import (
    EmergencyKillSwitchDecision,
    EmergencyKillSwitchIntegrationPoint,
    EmergencyKillSwitchState,
)


GLOBAL_KILL_SWITCH_INITIALIZED_AT = datetime(2026, 6, 14, tzinfo=UTC)
GLOBAL_KILL_SWITCH_BLOCK_REASON = "global_kill_switch_enabled"
SYSTEM_OWNER_REQUIRED_REASON = "system_owner_required"

_global_kill_switch_enabled = False
_global_kill_switch_updated_at = GLOBAL_KILL_SWITCH_INITIALIZED_AT
_global_kill_switch_updated_by_user_id: int | None = None
_global_kill_switch_updated_by_role: str | None = None


class EmergencyKillSwitchBlockedError(ValueError):
    def __init__(self, decision: EmergencyKillSwitchDecision) -> None:
        self.decision = decision
        super().__init__(f"BLOCKED by Emergency Kill Switch: {decision.reason}")


class EmergencyKillSwitchPermissionError(PermissionError):
    pass


class EmergencyKillSwitchGate:
    """C13D global kill switch. When enabled, it is a system-wide veto."""

    def __init__(self, global_kill_switch: bool | None = None) -> None:
        self.global_kill_switch = (
            global_kill_switch
            if global_kill_switch is not None
            else is_global_kill_switch_enabled()
        )

    def decision(
        self,
        *,
        integration_point: EmergencyKillSwitchIntegrationPoint | None = None,
    ) -> EmergencyKillSwitchDecision:
        evaluated_at = datetime.now(UTC)
        if self.global_kill_switch:
            return EmergencyKillSwitchDecision(
                global_kill_switch=True,
                enforcement_result="BLOCKED",
                reason=GLOBAL_KILL_SWITCH_BLOCK_REASON,
                integration_point=integration_point,
                evaluated_at=evaluated_at,
                execution_chain_stopped=True,
                c08_blocked=True,
                c09_blocked=True,
                c10_blocked=True,
                c12_blocked=True,
                c13b_blocked=True,
                c13c_blocked=True,
                module_switches_ignored=True,
            )

        return EmergencyKillSwitchDecision(
            global_kill_switch=False,
            enforcement_result="ALLOWED",
            reason="global_kill_switch_disabled",
            integration_point=integration_point,
            evaluated_at=evaluated_at,
            execution_chain_stopped=False,
            c08_blocked=False,
            c09_blocked=False,
            c10_blocked=False,
            c12_blocked=False,
            c13b_blocked=False,
            c13c_blocked=False,
            module_switches_ignored=False,
        )

    def enforce(
        self,
        *,
        integration_point: EmergencyKillSwitchIntegrationPoint | None = None,
    ) -> EmergencyKillSwitchDecision:
        decision = self.decision(integration_point=integration_point)
        if decision.enforcement_result == "BLOCKED":
            raise EmergencyKillSwitchBlockedError(decision)
        return decision


def get_global_kill_switch_state() -> EmergencyKillSwitchState:
    return EmergencyKillSwitchState(
        global_kill_switch=_global_kill_switch_enabled,
        updated_at=_global_kill_switch_updated_at,
        updated_by_user_id=_global_kill_switch_updated_by_user_id,
        updated_by_role=_global_kill_switch_updated_by_role,
    )


def is_global_kill_switch_enabled() -> bool:
    return _global_kill_switch_enabled


def set_global_kill_switch(
    *,
    global_kill_switch: bool,
    actor_role: str,
    actor_user_id: int | None = None,
) -> EmergencyKillSwitchState:
    if not is_owner_role(actor_role):
        raise EmergencyKillSwitchPermissionError(SYSTEM_OWNER_REQUIRED_REASON)

    global _global_kill_switch_enabled
    global _global_kill_switch_updated_at
    global _global_kill_switch_updated_by_user_id
    global _global_kill_switch_updated_by_role

    _global_kill_switch_enabled = global_kill_switch
    _global_kill_switch_updated_at = datetime.now(UTC)
    _global_kill_switch_updated_by_user_id = actor_user_id
    _global_kill_switch_updated_by_role = actor_role
    return get_global_kill_switch_state()

