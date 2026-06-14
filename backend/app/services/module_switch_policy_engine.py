from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from ..core.module_switches import (
    MODULE_SWITCH_DEPENDENCY_GRAPH_V1,
    MODULE_SWITCH_GROUP_POLICIES_V1,
    MODULE_SWITCH_INHERITANCE_POLICIES_V1,
    MODULE_SWITCH_REGISTRY_UPDATED_AT,
    MODULE_SWITCH_REGISTRY_V1,
)
from ..schemas.module_switch import (
    ModuleSwitchBatchSwitchRequest,
    ModuleSwitchDependencyRule,
    ModuleSwitchGroupPolicy,
    ModuleSwitchGroupSwitchRequest,
    ModuleSwitchInheritancePolicy,
    ModuleSwitchPolicyEvaluation,
    ModuleSwitchPolicySource,
    ModuleSwitchRegistryRecord,
)
from .emergency_kill_switch import EmergencyKillSwitchGate


class ModuleSwitchPolicyError(ValueError):
    pass


class ModuleSwitchPolicyEngine:
    """C13C read-only policy engine for effective module switch state."""

    def __init__(
        self,
        *,
        registry: Sequence[ModuleSwitchRegistryRecord | Mapping[str, Any]]
        | None = None,
        dependency_rules: Sequence[
            ModuleSwitchDependencyRule | Mapping[str, Any]
        ]
        | None = None,
        group_policies: Sequence[ModuleSwitchGroupPolicy | Mapping[str, Any]]
        | None = None,
        inheritance_policies: Sequence[
            ModuleSwitchInheritancePolicy | Mapping[str, Any]
        ]
        | None = None,
    ) -> None:
        self.updated_at = MODULE_SWITCH_REGISTRY_UPDATED_AT
        self._records: dict[str, ModuleSwitchRegistryRecord] = {}
        self._invalid_reasons: dict[str, str] = {}
        self._module_order: list[str] = []
        self._load_registry(
            registry if registry is not None else MODULE_SWITCH_REGISTRY_V1
        )
        self._dependency_rules = self._load_dependency_rules(
            dependency_rules
            if dependency_rules is not None
            else MODULE_SWITCH_DEPENDENCY_GRAPH_V1
        )
        self._groups = self._load_group_policies(
            group_policies
            if group_policies is not None
            else MODULE_SWITCH_GROUP_POLICIES_V1
        )
        self._inheritance = self._load_inheritance_policies(
            inheritance_policies
            if inheritance_policies is not None
            else MODULE_SWITCH_INHERITANCE_POLICIES_V1
        )
        self._include_policy_graph_modules()

    def evaluate(
        self,
        *,
        group_switches: Sequence[
            ModuleSwitchGroupSwitchRequest | Mapping[str, Any]
        ]
        | None = None,
        batch_switches: Sequence[
            ModuleSwitchBatchSwitchRequest | Mapping[str, Any]
        ]
        | None = None,
    ) -> tuple[ModuleSwitchPolicyEvaluation, ...]:
        EmergencyKillSwitchGate().enforce(
            integration_point="c13c_policy_engine",
        )
        states: dict[str, str] = {}
        reasons: dict[str, str] = {}
        sources: dict[str, ModuleSwitchPolicySource] = {}
        inherited_from: dict[str, str | None] = {}
        cascaded_from: dict[str, set[str]] = {}

        for module_key in self._module_order:
            group_keys = self._group_keys_for_module(module_key)
            inherited_from[module_key] = None
            cascaded_from[module_key] = set()
            if module_key in self._invalid_reasons:
                states[module_key] = "OFF"
                reasons[module_key] = self._invalid_reasons[module_key]
                sources[module_key] = "invalid"
                continue

            record = self._records.get(module_key)
            if record is None:
                states[module_key] = "OFF"
                reasons[module_key] = "module_switch_not_registered"
                sources[module_key] = "missing"
                continue

            states[module_key] = record.state
            reasons[module_key] = (
                "module_switch_on"
                if record.state == "ON"
                else record.disabled_reason or "module_switch_disabled"
            )
            sources[module_key] = "module"

            policy = self._inheritance.get(module_key)
            if (
                policy is not None
                and policy.policy_mode == "inherit"
                and states[module_key] == "ON"
            ):
                for group_key in group_keys:
                    group = self._groups.get(group_key)
                    if group is None or group.default_state == "ON":
                        continue
                    states[module_key] = group.default_state
                    reasons[module_key] = (
                        group.disabled_reason
                        or f"Module inherits disabled group {group_key}."
                    )
                    sources[module_key] = "group_default"
                    inherited_from[module_key] = group_key
                    break

        for request in self._parse_group_switches(group_switches):
            group = self._groups.get(request.group_key)
            if group is None:
                raise ModuleSwitchPolicyError(
                    f"Unknown module switch group: {request.group_key}"
                )
            for module_key in group.module_keys:
                states[module_key] = request.state
                reasons[module_key] = (
                    "module_switch_on"
                    if request.state == "ON"
                    else request.disabled_reason
                    or f"Group switch disabled {request.group_key}."
                )
                sources[module_key] = "group_switch"
                cascaded_from.setdefault(module_key, set())

        for request in self._parse_batch_switches(batch_switches):
            for module_key in request.module_keys:
                if module_key not in states:
                    raise ModuleSwitchPolicyError(
                        f"Unknown module switch target: {module_key}"
                    )
                states[module_key] = request.state
                reasons[module_key] = (
                    "module_switch_on"
                    if request.state == "ON"
                    else request.disabled_reason
                    or "Batch switch disabled module."
                )
                sources[module_key] = "batch_switch"

        for module_key, reason in self._invalid_reasons.items():
            states[module_key] = "OFF"
            reasons[module_key] = reason
            sources[module_key] = "invalid"

        for module_key in self._module_order:
            if module_key not in self._records:
                states[module_key] = "OFF"
                reasons[module_key] = "module_switch_not_registered"
                sources[module_key] = "missing"

        self._apply_dependency_cascade(
            states=states,
            reasons=reasons,
            sources=sources,
            cascaded_from=cascaded_from,
        )

        return tuple(
            ModuleSwitchPolicyEvaluation(
                module_key=module_key,
                state=states[module_key],
                enabled=states[module_key] == "ON",
                reason=reasons[module_key],
                policy_source=sources[module_key],
                group_keys=self._group_keys_for_module(module_key),
                inherited_from_group=inherited_from.get(module_key),
                cascaded_from=tuple(sorted(cascaded_from[module_key])),
                updated_at=self.updated_at,
            )
            for module_key in self._module_order
        )

    def effective_registry(
        self,
        *,
        group_switches: Sequence[
            ModuleSwitchGroupSwitchRequest | Mapping[str, Any]
        ]
        | None = None,
        batch_switches: Sequence[
            ModuleSwitchBatchSwitchRequest | Mapping[str, Any]
        ]
        | None = None,
    ) -> tuple[ModuleSwitchRegistryRecord, ...]:
        return tuple(
            ModuleSwitchRegistryRecord(
                module_key=evaluation.module_key,
                state=evaluation.state,
                enabled=evaluation.enabled,
                disabled_reason=(
                    None if evaluation.enabled else evaluation.reason
                ),
                updated_at=evaluation.updated_at,
            )
            for evaluation in self.evaluate(
                group_switches=group_switches,
                batch_switches=batch_switches,
            )
        )

    def _load_registry(
        self,
        raw_records: Sequence[ModuleSwitchRegistryRecord | Mapping[str, Any]],
    ) -> None:
        for raw_record in raw_records:
            module_key = self._raw_module_key(raw_record)
            if not module_key:
                continue
            if module_key not in self._module_order:
                self._module_order.append(module_key)
            if module_key in self._records or module_key in self._invalid_reasons:
                self._invalid_reasons[module_key] = "module_switch_duplicate"
                self._records.pop(module_key, None)
                continue
            try:
                self._records[module_key] = self._record_from_raw(raw_record)
            except (TypeError, ValueError, ValidationError):
                self._invalid_reasons[module_key] = "module_switch_invalid_state"

    def _load_dependency_rules(
        self,
        raw_rules: Sequence[ModuleSwitchDependencyRule | Mapping[str, Any]],
    ) -> tuple[ModuleSwitchDependencyRule, ...]:
        return tuple(
            raw_rule
            if isinstance(raw_rule, ModuleSwitchDependencyRule)
            else ModuleSwitchDependencyRule.model_validate(raw_rule)
            for raw_rule in raw_rules
        )

    def _load_group_policies(
        self,
        raw_groups: Sequence[ModuleSwitchGroupPolicy | Mapping[str, Any]],
    ) -> dict[str, ModuleSwitchGroupPolicy]:
        groups: dict[str, ModuleSwitchGroupPolicy] = {}
        for raw_group in raw_groups:
            group = (
                raw_group
                if isinstance(raw_group, ModuleSwitchGroupPolicy)
                else ModuleSwitchGroupPolicy.model_validate(raw_group)
            )
            if group.group_key in groups:
                raise ModuleSwitchPolicyError(
                    f"Duplicate module switch group: {group.group_key}"
                )
            groups[group.group_key] = group
        return groups

    def _load_inheritance_policies(
        self,
        raw_policies: Sequence[
            ModuleSwitchInheritancePolicy | Mapping[str, Any]
        ],
    ) -> dict[str, ModuleSwitchInheritancePolicy]:
        policies: dict[str, ModuleSwitchInheritancePolicy] = {}
        for raw_policy in raw_policies:
            policy = (
                raw_policy
                if isinstance(raw_policy, ModuleSwitchInheritancePolicy)
                else ModuleSwitchInheritancePolicy.model_validate(raw_policy)
            )
            if policy.module_key in policies:
                raise ModuleSwitchPolicyError(
                    "Duplicate module switch inheritance policy: "
                    f"{policy.module_key}"
                )
            policies[policy.module_key] = policy
        return policies

    def _include_policy_graph_modules(self) -> None:
        for rule in self._dependency_rules:
            self._append_module_key(rule.parent_module_key)
            self._append_module_key(rule.child_module_key)
        for group in self._groups.values():
            for module_key in group.module_keys:
                self._append_module_key(module_key)
        for policy in self._inheritance.values():
            self._append_module_key(policy.module_key)

    def _append_module_key(self, module_key: str) -> None:
        if module_key not in self._module_order:
            self._module_order.append(module_key)

    def _group_keys_for_module(self, module_key: str) -> tuple[str, ...]:
        policy = self._inheritance.get(module_key)
        if policy is not None:
            return policy.group_keys
        return tuple(
            group.group_key
            for group in self._groups.values()
            if module_key in group.module_keys
        )

    def _parse_group_switches(
        self,
        group_switches: Sequence[
            ModuleSwitchGroupSwitchRequest | Mapping[str, Any]
        ]
        | None,
    ) -> tuple[ModuleSwitchGroupSwitchRequest, ...]:
        if group_switches is None:
            return ()
        return tuple(
            request
            if isinstance(request, ModuleSwitchGroupSwitchRequest)
            else ModuleSwitchGroupSwitchRequest.model_validate(request)
            for request in group_switches
        )

    def _parse_batch_switches(
        self,
        batch_switches: Sequence[
            ModuleSwitchBatchSwitchRequest | Mapping[str, Any]
        ]
        | None,
    ) -> tuple[ModuleSwitchBatchSwitchRequest, ...]:
        if batch_switches is None:
            return ()
        return tuple(
            request
            if isinstance(request, ModuleSwitchBatchSwitchRequest)
            else ModuleSwitchBatchSwitchRequest.model_validate(request)
            for request in batch_switches
        )

    def _apply_dependency_cascade(
        self,
        *,
        states: dict[str, str],
        reasons: dict[str, str],
        sources: dict[str, ModuleSwitchPolicySource],
        cascaded_from: dict[str, set[str]],
    ) -> None:
        children_by_parent: dict[str, list[ModuleSwitchDependencyRule]] = {}
        for rule in self._dependency_rules:
            children_by_parent.setdefault(rule.parent_module_key, []).append(
                rule
            )

        queue: deque[str] = deque(
            module_key
            for module_key in self._module_order
            if states[module_key] != "ON"
        )
        visited_edges: set[tuple[str, str]] = set()
        while queue:
            parent_module_key = queue.popleft()
            for rule in children_by_parent.get(parent_module_key, ()):
                child_module_key = rule.child_module_key
                if child_module_key not in states:
                    continue
                edge = (parent_module_key, child_module_key)
                if edge in visited_edges:
                    continue
                visited_edges.add(edge)
                cascaded_from.setdefault(child_module_key, set()).add(
                    parent_module_key
                )
                if states[child_module_key] != "ON":
                    continue
                states[child_module_key] = "OFF"
                reasons[child_module_key] = (
                    "Disabled because dependency parent is off: "
                    f"{parent_module_key}."
                )
                sources[child_module_key] = "dependency_cascade"
                if rule.recursive:
                    queue.append(child_module_key)

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


def build_effective_module_switch_registry(
    *,
    group_switches: Sequence[ModuleSwitchGroupSwitchRequest | Mapping[str, Any]]
    | None = None,
    batch_switches: Sequence[ModuleSwitchBatchSwitchRequest | Mapping[str, Any]]
    | None = None,
) -> tuple[ModuleSwitchRegistryRecord, ...]:
    return ModuleSwitchPolicyEngine().effective_registry(
        group_switches=group_switches,
        batch_switches=batch_switches,
    )
