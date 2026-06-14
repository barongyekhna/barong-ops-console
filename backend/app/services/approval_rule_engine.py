from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from ..schemas.approval import (
    ApprovalDecision,
    ApprovalDecisionSource,
    ApprovalDecisionStatus,
    ApprovalExecutionType,
    ApprovalRequest,
    ApprovalRiskLevel,
)


RequesterRole = Literal["owner", "non_owner", "guest"]
ModuleApprovalProfile = Literal["admin", "system", "business", "unknown"]

APPROVAL_RULE_ENGINE_STAGE: Literal["c12b_approval_rule_engine"] = (
    "c12b_approval_rule_engine"
)
APPROVAL_RULE_ENGINE_SAFETY_GUARANTEES = (
    "ApprovalRuleEngine only evaluates ApprovalRequest data in memory.",
    "ApprovalRuleEngine returns ApprovalDecision and does not mutate requests.",
    "ApprovalRuleEngine does not call C09 execution provider APIs.",
    "ApprovalRuleEngine does not call C10 sandbox runtime or bridge.",
    "ApprovalRuleEngine does not write database rows or operation logs.",
    "ApprovalRuleEngine does not call external APIs or provider endpoints.",
)

REQUESTER_ROLE_FACT_KEYS = frozenset(
    {
        "actor_role",
        "requester_role",
        "role",
        "user_role",
    }
)
GUEST_ROLE_VALUES = frozenset(
    {
        "anonymous",
        "guest",
        "public",
        "unauthenticated",
    }
)
OWNER_ROLE_VALUES = frozenset({"owner"})
SAFE_EXECUTION_TYPES: frozenset[ApprovalExecutionType] = frozenset(
    {"mock", "no_op"}
)
STATUS_PRECEDENCE: Mapping[ApprovalDecisionStatus, int] = {
    "rejected": 40,
    "pending": 30,
    "approved": 20,
    "auto_approved": 10,
}
SOURCE_PRECEDENCE: Mapping[ApprovalDecisionSource, int] = {
    "user": 50,
    "module": 40,
    "execution": 30,
    "risk": 20,
    "global": 10,
}


def _approval_request_from_raw(
    request: ApprovalRequest | Mapping[str, Any],
) -> ApprovalRequest:
    if isinstance(request, ApprovalRequest):
        return request
    return ApprovalRequest.model_validate(request)


def _fact_value(request: ApprovalRequest, keys: frozenset[str]) -> str | None:
    for fact in request.context_snapshot.facts:
        if fact.key.strip().lower() in keys:
            return fact.value.strip().lower()
    return None


def _requester_role(request: ApprovalRequest) -> RequesterRole:
    role = _fact_value(request, REQUESTER_ROLE_FACT_KEYS)
    if role in OWNER_ROLE_VALUES:
        return "owner"
    if role in GUEST_ROLE_VALUES:
        return "guest"
    return "non_owner"


def _module_profile(module_key: str) -> ModuleApprovalProfile:
    if module_key.startswith("admin."):
        return "admin"
    if module_key.startswith("system."):
        return "system"
    if module_key.startswith("business."):
        return "business"
    return "unknown"


def _decision(
    status: ApprovalDecisionStatus,
    reason: str,
    source: ApprovalDecisionSource,
) -> ApprovalDecision:
    return ApprovalDecision(
        status=status,
        reason=reason,
        decision_source=source,
    )


def _safe_execution(execution_type: ApprovalExecutionType) -> bool:
    return execution_type in SAFE_EXECUTION_TYPES


def _risk_decision(
    risk_level: ApprovalRiskLevel,
    execution_type: ApprovalExecutionType,
    requester_role: RequesterRole,
    module_profile: ModuleApprovalProfile,
) -> ApprovalDecision:
    if risk_level == "high":
        return _decision(
            "pending",
            "High-risk approval requests require manual approval.",
            "risk",
        )

    if risk_level == "medium":
        can_auto_approve = (
            requester_role == "owner"
            and _safe_execution(execution_type)
            and module_profile not in {"admin", "system"}
        )
        if can_auto_approve:
            return _decision(
                "auto_approved",
                "Medium-risk owner request with safe execution can be auto-approved.",
                "risk",
            )
        return _decision(
            "pending",
            "Medium-risk approval requests require review unless owner and safe-execution rules apply.",
            "risk",
        )

    return _decision(
        "auto_approved",
        "Low-risk approval requests can be auto-approved.",
        "risk",
    )


def _execution_decision(
    execution_type: ApprovalExecutionType,
    risk_level: ApprovalRiskLevel,
    requester_role: RequesterRole,
    module_profile: ModuleApprovalProfile,
) -> ApprovalDecision:
    if execution_type in {"mock", "no_op"}:
        return _decision(
            "auto_approved",
            f"{execution_type} execution is safe for automatic approval.",
            "execution",
        )

    if execution_type == "real":
        return _decision(
            "pending",
            "Real execution requires manual approval.",
            "execution",
        )

    can_auto_approve_async = (
        requester_role == "owner"
        and risk_level == "low"
        and module_profile not in {"admin", "system"}
    )
    if can_auto_approve_async:
        return _decision(
            "auto_approved",
            "Async low-risk owner request can be auto-approved outside admin/system modules.",
            "execution",
        )
    return _decision(
        "pending",
        "Async execution is conditional and requires review unless low-risk owner rules apply.",
        "execution",
    )


def _module_decision(
    module_profile: ModuleApprovalProfile,
    risk_level: ApprovalRiskLevel,
    execution_type: ApprovalExecutionType,
    requester_role: RequesterRole,
) -> ApprovalDecision:
    if module_profile == "system":
        return _decision(
            "pending",
            "system.* modules are treated as high-risk and require manual approval.",
            "module",
        )

    if module_profile == "admin":
        return _decision(
            "pending",
            "admin.* modules use stricter approval and require manual approval.",
            "module",
        )

    if module_profile == "business":
        can_auto_approve = requester_role == "owner" and (
            (
                risk_level == "low"
                and (
                    _safe_execution(execution_type)
                    or execution_type == "async"
                )
            )
            or (
                risk_level == "medium"
                and _safe_execution(execution_type)
            )
        )
        if can_auto_approve:
            return _decision(
                "auto_approved",
                "business.* module request stays within automatic approval conditions.",
                "module",
            )
        return _decision(
            "pending",
            "business.* modules use medium-risk handling for non-trivial requests.",
            "module",
        )

    if requester_role == "owner" and risk_level == "low" and _safe_execution(
        execution_type
    ):
        return _decision(
            "auto_approved",
            "Unknown module namespace can be auto-approved only for low-risk owner safe execution.",
            "module",
        )
    return _decision(
        "pending",
        "Unknown module namespace requires manual review.",
        "module",
    )


def _user_decision(
    requester_role: RequesterRole,
    risk_level: ApprovalRiskLevel,
    execution_type: ApprovalExecutionType,
    module_profile: ModuleApprovalProfile,
) -> ApprovalDecision:
    if requester_role == "guest":
        if (
            risk_level == "high"
            or execution_type == "real"
            or module_profile in {"admin", "system"}
        ):
            return _decision(
                "rejected",
                "Guest requester cannot approve high-friction approval requests.",
                "user",
            )
        return _decision(
            "pending",
            "Guest requester requires manual review before any approval.",
            "user",
        )

    if requester_role == "owner":
        if (
            risk_level in {"low", "medium"}
            and execution_type != "real"
            and module_profile not in {"admin", "system"}
        ):
            return _decision(
                "auto_approved",
                "Owner requester receives relaxed approval for non-real non-admin/system requests.",
                "user",
            )
        return _decision(
            "pending",
            "Owner requester still requires manual approval for high-risk, real, admin, or system requests.",
            "user",
        )

    if (
        risk_level == "low"
        and _safe_execution(execution_type)
        and module_profile not in {"admin", "system"}
    ):
        return _decision(
            "auto_approved",
            "Non-owner requester can be auto-approved only for low-risk safe execution.",
            "user",
        )
    return _decision(
        "pending",
        "Non-owner requester uses strict approval for medium/high, async/real, admin, or system requests.",
        "user",
    )


def _identity_drift_decision(request: ApprovalRequest) -> ApprovalDecision | None:
    snapshot = request.context_snapshot
    if (
        snapshot.execution_id != request.execution_id
        or snapshot.module_key != request.module_key
        or snapshot.adapter_key != request.adapter_key
        or snapshot.action_key != request.action_key
        or snapshot.requester_id != request.requester_id
        or snapshot.risk_level != request.risk_level
        or snapshot.execution_type != request.execution_type
    ):
        return _decision(
            "rejected",
            "Approval request identity does not match immutable context snapshot.",
            "global",
        )
    return None


def _terminal_status_decision(request: ApprovalRequest) -> ApprovalDecision | None:
    if request.status == "approved":
        return _decision(
            "approved",
            "Approval request is already manually approved.",
            "global",
        )
    if request.status == "rejected":
        return _decision(
            "rejected",
            "Approval request is already rejected.",
            "global",
        )
    if request.status == "auto_approved":
        return _decision(
            "auto_approved",
            "Approval request is already auto-approved.",
            "global",
        )
    return None


def _select_decision(decisions: tuple[ApprovalDecision, ...]) -> ApprovalDecision:
    return max(
        decisions,
        key=lambda decision: (
            STATUS_PRECEDENCE[decision.status],
            SOURCE_PRECEDENCE[decision.decision_source],
        ),
    )


class ApprovalRuleEngine:
    def evaluate(
        self,
        request: ApprovalRequest | Mapping[str, Any],
    ) -> ApprovalDecision:
        approval_request = _approval_request_from_raw(request)

        identity_decision = _identity_drift_decision(approval_request)
        if identity_decision is not None:
            return identity_decision

        terminal_decision = _terminal_status_decision(approval_request)
        if terminal_decision is not None:
            return terminal_decision

        requester_role = _requester_role(approval_request)
        module_profile = _module_profile(approval_request.module_key)
        decisions = (
            _user_decision(
                requester_role,
                approval_request.risk_level,
                approval_request.execution_type,
                module_profile,
            ),
            _module_decision(
                module_profile,
                approval_request.risk_level,
                approval_request.execution_type,
                requester_role,
            ),
            _execution_decision(
                approval_request.execution_type,
                approval_request.risk_level,
                requester_role,
                module_profile,
            ),
            _risk_decision(
                approval_request.risk_level,
                approval_request.execution_type,
                requester_role,
                module_profile,
            ),
        )
        return _select_decision(decisions)


approval_rule_engine = ApprovalRuleEngine()
