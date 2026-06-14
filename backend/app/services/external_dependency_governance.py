from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, get_args

from ..core.external_dependencies import (
    EXTERNAL_DEPENDENCY_POLICIES_V1,
    EXTERNAL_SERVICE_REGISTRY_V1,
)
from ..schemas.external_dependency import (
    ExternalAccessRecommendation,
    ExternalDependencyBindingRead,
    ExternalDependencyBindingStatus,
    ExternalDependencyPolicy,
    ExternalService,
    ExternalServiceRegistrationProposal,
    ExternalServiceStatus,
    ExternalServiceType,
    ExternalTrustEvaluation,
    ExternalTrustLevel,
    PolicyDecision,
)
from .module_adapter_registry import get_adapter_contract, list_adapter_contracts


EXTERNAL_SERVICE_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:[._][a-z][a-z0-9_]*)*$"
)
EXTERNAL_POLICY_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:[._][a-z][a-z0-9_]*)*$"
)
ALLOWED_EXTERNAL_SERVICE_TYPES = frozenset(get_args(ExternalServiceType))
ALLOWED_EXTERNAL_SERVICE_STATUSES = frozenset(get_args(ExternalServiceStatus))
ALLOWED_EXTERNAL_TRUST_LEVELS = frozenset(get_args(ExternalTrustLevel))
TRUST_LEVEL_FLOORS: dict[ExternalTrustLevel, int] = {
    "untrusted": 0,
    "low": 35,
    "medium": 60,
    "high": 80,
}
TRUST_LEVEL_BASE_SCORE: dict[ExternalTrustLevel, int] = {
    "high": 85,
    "medium": 65,
    "low": 40,
    "untrusted": 10,
}
SERVICE_STATUS_SCORE_ADJUSTMENT: dict[ExternalServiceStatus, int] = {
    "active": 0,
    "pending": -15,
    "suspended": -45,
    "quarantined": -70,
}
RISK_SCORE_ADJUSTMENT = {
    "low": 0,
    "medium": -5,
    "high": -20,
    "critical": -35,
}
SENSITIVE_EXTERNAL_DEPENDENCY_MARKERS = (
    ".env",
    "authorization",
    "bearer ",
    "credential",
    "http://",
    "https://",
    "password",
    "provider_url",
    "secret",
    "token",
    "url",
    "webhook",
    "://",
    "=",
)


class ExternalDependencyGateBlockedError(ValueError):
    def __init__(
        self,
        decision: PolicyDecision,
        proposal: ExternalServiceRegistrationProposal | None = None,
    ) -> None:
        self.decision = decision
        self.proposal = proposal
        super().__init__(
            f"BLOCKED by C14D External Dependency Gate: {decision.reason}"
        )


def _service_from_raw(
    raw: ExternalService | Mapping[str, Any],
) -> ExternalService:
    if isinstance(raw, ExternalService):
        return raw
    return ExternalService.model_validate(raw)


def _policy_from_raw(
    raw: ExternalDependencyPolicy | Mapping[str, Any],
) -> ExternalDependencyPolicy:
    if isinstance(raw, ExternalDependencyPolicy):
        return raw
    return ExternalDependencyPolicy.model_validate(raw)


def _iter_string_values(value: Any):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _iter_string_values(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _iter_string_values(item)


def _contains_sensitive_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SENSITIVE_EXTERNAL_DEPENDENCY_MARKERS)


def _validate_service_id(service_id: str) -> None:
    if not EXTERNAL_SERVICE_ID_PATTERN.fullmatch(service_id):
        raise ValueError("External service id must use safe lowercase namespace.")
    if _contains_sensitive_marker(service_id):
        raise ValueError("External service id contains a blocked marker.")


def _validate_safe_values(model_key: str, payload: Mapping[str, Any]) -> None:
    for value in _iter_string_values(payload):
        if _contains_sensitive_marker(value):
            raise ValueError(f"{model_key} contains sensitive runtime data.")


def validate_external_service_registry(
    raw_services: Sequence[ExternalService | Mapping[str, Any]] | None = None,
) -> list[ExternalService]:
    source = (
        raw_services if raw_services is not None else EXTERNAL_SERVICE_REGISTRY_V1
    )
    services = [_service_from_raw(raw_service) for raw_service in source]
    seen_service_ids: set[str] = set()

    for service in services:
        _validate_service_id(service.service_id)
        if service.service_id in seen_service_ids:
            raise ValueError(f"Duplicate external service_id: {service.service_id}")
        seen_service_ids.add(service.service_id)
        if service.service_type not in ALLOWED_EXTERNAL_SERVICE_TYPES:
            raise ValueError(f"{service.service_id} has invalid service_type.")
        if service.status not in ALLOWED_EXTERNAL_SERVICE_STATUSES:
            raise ValueError(f"{service.service_id} has invalid status.")
        if service.trust_level not in ALLOWED_EXTERNAL_TRUST_LEVELS:
            raise ValueError(f"{service.service_id} has invalid trust_level.")
        _validate_safe_values(
            service.service_id,
            service.model_dump(mode="json"),
        )

    return services


def validate_external_dependency_policies(
    raw_policies: Sequence[ExternalDependencyPolicy | Mapping[str, Any]] | None = None,
) -> list[ExternalDependencyPolicy]:
    source = (
        raw_policies
        if raw_policies is not None
        else EXTERNAL_DEPENDENCY_POLICIES_V1
    )
    policies = [_policy_from_raw(raw_policy) for raw_policy in source]
    seen_policy_ids: set[str] = set()

    for policy in policies:
        if not EXTERNAL_POLICY_ID_PATTERN.fullmatch(policy.policy_id):
            raise ValueError("External dependency policy id is invalid.")
        if policy.policy_id in seen_policy_ids:
            raise ValueError(
                f"Duplicate external dependency policy_id: {policy.policy_id}"
            )
        seen_policy_ids.add(policy.policy_id)
        if policy.service_id is not None:
            _validate_service_id(policy.service_id)
        for value in (policy.module, policy.action):
            if _contains_sensitive_marker(value):
                raise ValueError(
                    f"{policy.policy_id} contains sensitive selector data."
                )
        _validate_safe_values(policy.policy_id, policy.model_dump(mode="json"))

    return policies


def list_external_services() -> list[ExternalService]:
    return validate_external_service_registry()


def list_external_dependency_policies() -> list[ExternalDependencyPolicy]:
    return validate_external_dependency_policies()


def get_external_service(service_id: str) -> ExternalService | None:
    for service in list_external_services():
        if service.service_id == service_id:
            return service
    return None


def _clamp_score(value: int) -> int:
    return max(0, min(100, value))


def _context_int(context: Mapping[str, Any], key: str) -> int:
    value = context.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return 0


def _context_ratio(
    context: Mapping[str, Any],
    numerator: str,
    denominator: str,
) -> float:
    num = _context_int(context, numerator)
    den = _context_int(context, denominator)
    if den <= 0:
        return 0.0
    return num / den


def _score_to_trust_level(score: int) -> ExternalTrustLevel:
    if score >= TRUST_LEVEL_FLOORS["high"]:
        return "high"
    if score >= TRUST_LEVEL_FLOORS["medium"]:
        return "medium"
    if score >= TRUST_LEVEL_FLOORS["low"]:
        return "low"
    return "untrusted"


def _recommendation_for_score(
    *,
    score: int,
    status: ExternalServiceStatus,
    trust_level: ExternalTrustLevel,
) -> ExternalAccessRecommendation:
    if status == "quarantined" or trust_level == "untrusted" or score < 35:
        return "quarantine"
    if status in {"pending", "suspended"} or score < 70:
        return "restrict"
    return "allow"


def evaluate_external_service_trust(
    service: ExternalService,
    *,
    context: Mapping[str, Any] | None = None,
) -> ExternalTrustEvaluation:
    safe_context = dict(context or {})
    risk_level = str(safe_context.get("risk_level", "medium"))
    module_sensitivity = str(safe_context.get("module_sensitivity", risk_level))
    usage_success_ratio = _context_ratio(
        safe_context,
        "successful_calls",
        "total_calls",
    )
    approval_success_ratio = _context_ratio(
        safe_context,
        "approved_requests",
        "approval_requests",
    )
    past_violations = _context_int(safe_context, "past_violations")
    approval_rejections = _context_int(safe_context, "approval_rejections")

    score = TRUST_LEVEL_BASE_SCORE[service.trust_level]
    score += SERVICE_STATUS_SCORE_ADJUSTMENT[service.status]
    score += RISK_SCORE_ADJUSTMENT.get(risk_level, -10)
    score += RISK_SCORE_ADJUSTMENT.get(module_sensitivity, -10)
    if usage_success_ratio:
        score += round((usage_success_ratio - 0.5) * 20)
    if approval_success_ratio:
        score += round((approval_success_ratio - 0.5) * 20)
    score -= min(40, past_violations * 12)
    score -= min(30, approval_rejections * 10)
    score = _clamp_score(score)
    dynamic_trust_level = _score_to_trust_level(score)

    return ExternalTrustEvaluation(
        service_id=service.service_id,
        service_type=service.service_type,
        status=service.status,
        configured_trust_level=service.trust_level,
        dynamic_trust_level=dynamic_trust_level,
        dynamic_trust_score=score,
        access_recommendation=_recommendation_for_score(
            score=score,
            status=service.status,
            trust_level=dynamic_trust_level,
        ),
        factors={
            "usage_history": {
                "total_calls": _context_int(safe_context, "total_calls"),
                "successful_calls": _context_int(safe_context, "successful_calls"),
            },
            "module_sensitivity": module_sensitivity,
            "risk_context": risk_level,
            "past_violations": past_violations,
            "approval_outcomes": {
                "approval_requests": _context_int(safe_context, "approval_requests"),
                "approved_requests": _context_int(safe_context, "approved_requests"),
                "approval_rejections": approval_rejections,
            },
        },
        reason="dynamic_trust_evaluated_from_policy_context",
    )


def _service_lookup(
    services: Sequence[ExternalService],
    service_id: str,
) -> ExternalService | None:
    return next(
        (service for service in services if service.service_id == service_id),
        None,
    )


def _policy_matches(
    policy: ExternalDependencyPolicy,
    *,
    service: ExternalService,
    module: str,
    action: str,
) -> bool:
    if not policy.enabled:
        return False
    if policy.module not in {module, "*"}:
        return False
    if policy.action not in {action, "*"}:
        return False
    if policy.service_id is not None and policy.service_id != service.service_id:
        return False
    if policy.service_type is not None and policy.service_type != service.service_type:
        return False
    return True


def _trust_satisfies_minimum(
    trust_level: ExternalTrustLevel,
    minimum: ExternalTrustLevel,
) -> bool:
    return TRUST_LEVEL_FLOORS[trust_level] >= TRUST_LEVEL_FLOORS[minimum]


def _unknown_service_decision(
    *,
    service_id: str,
    module: str,
    action: str,
    context: Mapping[str, Any],
) -> PolicyDecision:
    return PolicyDecision(
        service_id=service_id,
        module=module,
        action=action,
        context=dict(context),
        decision="quarantine",
        reason="c14d_unknown_service_quarantined",
        dynamic_trust_score=0,
        dynamic_trust_level="untrusted",
        access_recommendation="quarantine",
        default_deny_applied=True,
        explicit_policy_matched=False,
        c12_approval_required=False,
        registration_required=True,
        quarantine_required=True,
    )


def decide_external_dependency_policy(
    *,
    service_id: str,
    module: str,
    action: str,
    context: Mapping[str, Any] | None = None,
    raw_services: Sequence[ExternalService | Mapping[str, Any]] | None = None,
    raw_policies: Sequence[ExternalDependencyPolicy | Mapping[str, Any]] | None = None,
) -> PolicyDecision:
    safe_context = dict(context or {})
    services = validate_external_service_registry(raw_services)
    policies = validate_external_dependency_policies(raw_policies)
    service = _service_lookup(services, service_id)
    if service is None:
        return _unknown_service_decision(
            service_id=service_id,
            module=module,
            action=action,
            context=safe_context,
        )

    trust = evaluate_external_service_trust(service, context=safe_context)
    if service.status == "quarantined":
        return PolicyDecision(
            service_id=service_id,
            module=module,
            action=action,
            context=safe_context,
            decision="quarantine",
            reason="c14d_service_status_quarantined",
            dynamic_trust_score=trust.dynamic_trust_score,
            dynamic_trust_level=trust.dynamic_trust_level,
            access_recommendation=trust.access_recommendation,
            default_deny_applied=True,
            explicit_policy_matched=False,
            quarantine_required=True,
        )
    if service.status == "suspended":
        return PolicyDecision(
            service_id=service_id,
            module=module,
            action=action,
            context=safe_context,
            decision="deny",
            reason="c14d_service_status_suspended",
            dynamic_trust_score=trust.dynamic_trust_score,
            dynamic_trust_level=trust.dynamic_trust_level,
            access_recommendation=trust.access_recommendation,
            default_deny_applied=True,
            explicit_policy_matched=False,
        )

    matching_policies = [
        policy
        for policy in policies
        if _policy_matches(policy, service=service, module=module, action=action)
    ]
    if not matching_policies:
        return PolicyDecision(
            service_id=service_id,
            module=module,
            action=action,
            context=safe_context,
            decision="deny",
            reason="c14d_default_deny_no_explicit_policy",
            dynamic_trust_score=trust.dynamic_trust_score,
            dynamic_trust_level=trust.dynamic_trust_level,
            access_recommendation=trust.access_recommendation,
            default_deny_applied=True,
            explicit_policy_matched=False,
        )

    policy = matching_policies[0]
    if not _trust_satisfies_minimum(
        trust.dynamic_trust_level,
        policy.min_trust_level,
    ):
        return PolicyDecision(
            service_id=service_id,
            module=module,
            action=action,
            context=safe_context,
            decision="require_approval",
            reason="c14d_dynamic_trust_below_policy_minimum",
            dynamic_trust_score=trust.dynamic_trust_score,
            dynamic_trust_level=trust.dynamic_trust_level,
            access_recommendation=trust.access_recommendation,
            default_deny_applied=False,
            explicit_policy_matched=True,
            c12_approval_required=True,
        )

    risk_level = str(safe_context.get("risk_level", "medium"))
    high_risk = risk_level in {"high", "critical"}
    if trust.access_recommendation == "quarantine":
        return PolicyDecision(
            service_id=service_id,
            module=module,
            action=action,
            context=safe_context,
            decision="quarantine",
            reason="c14d_dynamic_trust_recommends_quarantine",
            dynamic_trust_score=trust.dynamic_trust_score,
            dynamic_trust_level=trust.dynamic_trust_level,
            access_recommendation=trust.access_recommendation,
            default_deny_applied=False,
            explicit_policy_matched=True,
            quarantine_required=True,
        )
    if (
        policy.decision == "require_approval"
        or policy.requires_c12_approval
        or high_risk
        or trust.access_recommendation == "restrict"
    ):
        return PolicyDecision(
            service_id=service_id,
            module=module,
            action=action,
            context=safe_context,
            decision="require_approval",
            reason="c14d_external_dependency_requires_c12_approval",
            dynamic_trust_score=trust.dynamic_trust_score,
            dynamic_trust_level=trust.dynamic_trust_level,
            access_recommendation=trust.access_recommendation,
            default_deny_applied=False,
            explicit_policy_matched=True,
            c12_approval_required=True,
        )
    if policy.decision == "deny":
        return PolicyDecision(
            service_id=service_id,
            module=module,
            action=action,
            context=safe_context,
            decision="deny",
            reason="c14d_policy_explicit_deny",
            dynamic_trust_score=trust.dynamic_trust_score,
            dynamic_trust_level=trust.dynamic_trust_level,
            access_recommendation=trust.access_recommendation,
            default_deny_applied=False,
            explicit_policy_matched=True,
        )

    return PolicyDecision(
        service_id=service_id,
        module=module,
        action=action,
        context=safe_context,
        decision="allow",
        reason="c14d_external_dependency_allowed_by_policy_trust_context",
        dynamic_trust_score=trust.dynamic_trust_score,
        dynamic_trust_level=trust.dynamic_trust_level,
        access_recommendation=trust.access_recommendation,
        default_deny_applied=False,
        explicit_policy_matched=True,
    )


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def build_registration_proposal(
    *,
    service_id: str,
    source_module: str,
    source_adapter: str,
    source_action: str | None = None,
    detection_context: Mapping[str, Any] | None = None,
) -> ExternalServiceRegistrationProposal:
    safe_context = dict(detection_context or {})
    return ExternalServiceRegistrationProposal(
        proposal_id=_stable_id(
            "c14d_registration",
            {
                "service_id": service_id,
                "source_module": source_module,
                "source_adapter": source_adapter,
                "source_action": source_action,
            },
        ),
        service_id=service_id,
        service_type="unknown",
        source_module=source_module,
        source_adapter=source_adapter,
        source_action=source_action,
        detection_context=safe_context,
        reason="c14d_unknown_service_requires_registration_review",
    )


def _binding_status(decision: PolicyDecision) -> ExternalDependencyBindingStatus:
    if decision.reason == "c14d_no_external_dependency_declared":
        return "no_external_dependency"
    if decision.decision == "allow":
        return "allowed"
    if decision.decision == "quarantine":
        return "quarantined"
    if decision.decision == "require_approval":
        return "pending_approval"
    return "blocked"


def build_dependency_binding_decisions(
    *,
    raw_services: Sequence[ExternalService | Mapping[str, Any]] | None = None,
    raw_policies: Sequence[ExternalDependencyPolicy | Mapping[str, Any]] | None = None,
) -> list[ExternalDependencyBindingRead]:
    services = validate_external_service_registry(raw_services)
    bindings: list[ExternalDependencyBindingRead] = []

    for adapter in list_adapter_contracts():
        actions = adapter.action_contracts or []
        action_keys = [action.action_key for action in actions] or [None]
        for dependency in adapter.dependency_declarations:
            service = _service_lookup(services, dependency.dependency_key)
            for action_key in action_keys:
                action = action_key or f"{adapter.module_key}.metadata"
                context = {
                    "adapter_key": adapter.adapter_key,
                    "dependency_required": dependency.required,
                    "risk_level": next(
                        (
                            contract.risk_level
                            for contract in actions
                            if contract.action_key == action_key
                        ),
                        "medium",
                    ),
                }
                decision = decide_external_dependency_policy(
                    service_id=dependency.dependency_key,
                    module=adapter.module_key,
                    action=action,
                    context=context,
                    raw_services=services,
                    raw_policies=raw_policies,
                )
                bindings.append(
                    ExternalDependencyBindingRead(
                        binding_id=_stable_id(
                            "c14d_binding",
                            {
                                "adapter": adapter.adapter_key,
                                "action": action,
                                "service_id": dependency.dependency_key,
                            },
                        ),
                        module=adapter.module_key,
                        adapter=adapter.adapter_key,
                        action=action_key,
                        service_id=dependency.dependency_key,
                        dependency_intent_declared=True,
                        service_registered=service is not None,
                        service_status=service.status if service else "missing",
                        trust_level=service.trust_level if service else "untrusted",
                        binding_status=_binding_status(decision),
                        policy_decision=decision,
                        requires_c12_approval=decision.c12_approval_required,
                    )
                )

    return bindings


def list_registration_proposals() -> list[ExternalServiceRegistrationProposal]:
    proposals: dict[str, ExternalServiceRegistrationProposal] = {}
    services = {service.service_id for service in list_external_services()}
    for adapter in list_adapter_contracts():
        for dependency in adapter.dependency_declarations:
            if dependency.dependency_key in services:
                continue
            proposal = build_registration_proposal(
                service_id=dependency.dependency_key,
                source_module=adapter.module_key,
                source_adapter=adapter.adapter_key,
                source_action=(
                    adapter.action_contracts[0].action_key
                    if adapter.action_contracts
                    else None
                ),
                detection_context={
                    "dependency_required": dependency.required,
                    "provider_status": dependency.provider_status,
                },
            )
            proposals[proposal.proposal_id] = proposal
    return list(proposals.values())


def _field(value: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(field_name, default)
    return getattr(value, field_name, default)


def _no_external_dependency_decision(request: Any) -> PolicyDecision:
    return PolicyDecision(
        service_id="none",
        module=str(_field(request, "module_key", "unknown")),
        action=str(_field(request, "action_key", "unknown")),
        context={"provider_key": _field(request, "provider_key", "unknown")},
        decision="allow",
        reason="c14d_no_external_dependency_declared",
        dynamic_trust_score=100,
        dynamic_trust_level="high",
        access_recommendation="allow",
        default_deny_applied=False,
        explicit_policy_matched=False,
    )


class ExternalDependencyGate:
    """C14D fail-closed external dependency gate.

    The gate evaluates declared dependency intent only. It never calls external
    services, resolves secrets, mutates execution requests, or changes runtime.
    """

    def check(self, execution_request: Any) -> PolicyDecision:
        decision = self.decision(execution_request)
        if decision.decision != "allow":
            proposal = None
            if decision.registration_required:
                proposal = build_registration_proposal(
                    service_id=decision.service_id,
                    source_module=decision.module,
                    source_adapter=str(
                        _field(execution_request, "adapter_key", "unknown")
                    ),
                    source_action=decision.action,
                    detection_context=decision.context,
                )
            raise ExternalDependencyGateBlockedError(decision, proposal)
        return decision

    def decision(self, execution_request: Any) -> PolicyDecision:
        module_key = str(_field(execution_request, "module_key", ""))
        adapter_key = str(_field(execution_request, "adapter_key", ""))
        action_key = str(_field(execution_request, "action_key", ""))
        adapter = get_adapter_contract(adapter_key)
        if adapter is None or adapter.module_key != module_key:
            return PolicyDecision(
                service_id="unknown",
                module=module_key or "unknown",
                action=action_key or "unknown",
                context={"adapter_key": adapter_key},
                decision="deny",
                reason="c14d_adapter_dependency_context_invalid",
                dynamic_trust_score=0,
                dynamic_trust_level="untrusted",
                access_recommendation="quarantine",
                default_deny_applied=True,
                explicit_policy_matched=False,
            )

        dependencies = adapter.dependency_declarations
        if not dependencies:
            return _no_external_dependency_decision(execution_request)

        allowed_decisions: list[PolicyDecision] = []
        for dependency in dependencies:
            context = {
                "adapter_key": adapter_key,
                "provider_key": _field(execution_request, "provider_key", "unknown"),
                "provider_type": _field(
                    execution_request,
                    "provider_type",
                    "unknown",
                ),
                "required_permission": _field(
                    execution_request,
                    "required_permission",
                    "unknown",
                ),
                "risk_level": _field(execution_request, "risk_level", "medium"),
                "secret_binding_status": _field(
                    execution_request,
                    "secret_binding_status",
                    "not_required",
                ),
                "dependency_required": dependency.required,
            }
            decision = decide_external_dependency_policy(
                service_id=dependency.dependency_key,
                module=module_key,
                action=action_key,
                context=context,
            )
            if decision.decision != "allow":
                return decision
            allowed_decisions.append(decision)

        return PolicyDecision(
            service_id="all_declared_external_dependencies",
            module=module_key,
            action=action_key,
            context={
                "adapter_key": adapter_key,
                "allowed_service_ids": [
                    decision.service_id for decision in allowed_decisions
                ],
            },
            decision="allow",
            reason="c14d_all_declared_dependencies_allowed",
            dynamic_trust_score=min(
                decision.dynamic_trust_score for decision in allowed_decisions
            ),
            dynamic_trust_level=min(
                (
                    decision.dynamic_trust_level
                    for decision in allowed_decisions
                ),
                key=lambda value: TRUST_LEVEL_FLOORS[value],
            ),
            access_recommendation="allow",
            default_deny_applied=False,
            explicit_policy_matched=True,
        )


C14D_GATE = ExternalDependencyGate()


def check_external_dependency_gate(execution_request: Any) -> PolicyDecision:
    return C14D_GATE.check(execution_request)


__all__ = [
    "ALLOWED_EXTERNAL_SERVICE_STATUSES",
    "ALLOWED_EXTERNAL_SERVICE_TYPES",
    "ALLOWED_EXTERNAL_TRUST_LEVELS",
    "C14D_GATE",
    "EXTERNAL_POLICY_ID_PATTERN",
    "EXTERNAL_SERVICE_ID_PATTERN",
    "ExternalDependencyGate",
    "ExternalDependencyGateBlockedError",
    "SENSITIVE_EXTERNAL_DEPENDENCY_MARKERS",
    "build_dependency_binding_decisions",
    "build_registration_proposal",
    "check_external_dependency_gate",
    "decide_external_dependency_policy",
    "evaluate_external_service_trust",
    "list_external_dependency_policies",
    "list_external_services",
    "list_registration_proposals",
    "validate_external_dependency_policies",
    "validate_external_service_registry",
]
