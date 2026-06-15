from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from ..core.model_locks import MODEL_LOCKS_V1
from ..schemas.ai_execution_binding import AIExecutionBindingRecord
from ..schemas.model_lock import (
    ModelLockC14XAIntegration,
    ModelLockCompletionStatus,
    ModelLockEnforcementLogic,
    ModelLockRegistryRecord,
    ModelLockRegistryResponse,
    ModelLockRegistryValidationResult,
    ModelLockRequestValidationResult,
    ModelLockRuleModel,
    ModelLockValidationIssue,
)
from .ai_execution_binding_registry import (
    AI_BINDING_KEY_PATTERN,
    AI_MODEL_REF_PATTERN,
    SENSITIVE_AI_BINDING_MARKERS,
    validate_ai_execution_binding_registry,
)


MODEL_LOCK_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
)
INVALID_REQUEST_KEY = "[invalid_key_id]"
INVALID_REQUEST_MODEL = "[invalid_model_id]"


def _lock_from_raw(
    raw: ModelLockRegistryRecord | Mapping[str, Any],
) -> ModelLockRegistryRecord:
    if isinstance(raw, ModelLockRegistryRecord):
        return raw
    return ModelLockRegistryRecord.model_validate(raw)


def _iter_string_values(value: Any):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_string_values(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _iter_string_values(item)


def _contains_sensitive_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SENSITIVE_AI_BINDING_MARKERS)


def _validate_safe_values(lock: ModelLockRegistryRecord) -> None:
    for value in _iter_string_values(lock.model_dump(mode="json")):
        if _contains_sensitive_marker(value):
            raise ValueError(f"{lock.key_id} contains sensitive runtime data.")


def _validate_key_id(key_id: str) -> None:
    if not AI_BINDING_KEY_PATTERN.fullmatch(key_id):
        raise ValueError("Model lock key_id is invalid.")
    if _contains_sensitive_marker(key_id):
        raise ValueError("Model lock key_id contains a blocked marker.")


def _validate_model_id(model_id: str) -> None:
    if not AI_MODEL_REF_PATTERN.fullmatch(model_id):
        raise ValueError("Model lock model_id is invalid.")
    if _contains_sensitive_marker(model_id):
        raise ValueError("Model lock model_id contains a blocked marker.")


def _validate_lock_timestamp(lock_timestamp: str) -> None:
    if not MODEL_LOCK_TIMESTAMP_PATTERN.fullmatch(lock_timestamp):
        raise ValueError("Model lock timestamp must be UTC ISO-8601 seconds.")


def _validated_ai_bindings(
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> list[AIExecutionBindingRecord]:
    return validate_ai_execution_binding_registry(raw_bindings)


def validate_model_lock_registry(
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> list[ModelLockRegistryRecord]:
    source = raw_locks if raw_locks is not None else MODEL_LOCKS_V1
    locks = [_lock_from_raw(raw) for raw in source]
    bindings = _validated_ai_bindings(raw_bindings)
    binding_by_key = {binding.key: binding for binding in bindings}
    seen_key_to_model: dict[str, str] = {}
    seen_models: set[str] = set()

    for lock in locks:
        _validate_key_id(lock.key_id)
        _validate_model_id(lock.model_id)
        _validate_lock_timestamp(lock.lock_timestamp)
        _validate_safe_values(lock)

        existing_model = seen_key_to_model.get(lock.key_id)
        if existing_model is not None:
            if existing_model != lock.model_id:
                raise ValueError(
                    "Model lock immutability violation: "
                    f"{lock.key_id} cannot move from {existing_model} "
                    f"to {lock.model_id}."
                )
            raise ValueError(f"Duplicate model lock key_id: {lock.key_id}")

        if lock.model_id in seen_models:
            raise ValueError(
                f"1:1 model lock reuse violation: {lock.model_id}"
            )

        binding = binding_by_key.get(lock.key_id)
        if binding is None:
            raise ValueError(
                f"{lock.key_id} is not registered in C14X-A bindings."
            )
        if binding.model != lock.model_id:
            raise ValueError(
                "C14X-A/C14X-B model lock mismatch: "
                f"{lock.key_id} binds {binding.model} but locks "
                f"{lock.model_id}."
            )

        seen_key_to_model[lock.key_id] = lock.model_id
        seen_models.add(lock.model_id)

    missing_locks = [
        binding.key for binding in bindings if binding.key not in seen_key_to_model
    ]
    if missing_locks:
        raise ValueError(
            "C14X-A binding missing C14X-B model lock: "
            f"{', '.join(missing_locks)}"
        )

    return locks


def list_model_lock_registry(
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> ModelLockRegistryResponse:
    locks = validate_model_lock_registry(raw_locks, raw_bindings)
    return ModelLockRegistryResponse(
        items=locks,
        count=len(locks),
        locked_count=sum(1 for lock in locks if lock.locked),
    )


def get_model_lock_rule_model() -> ModelLockRuleModel:
    return ModelLockRuleModel()


def get_model_lock_enforcement_logic() -> ModelLockEnforcementLogic:
    return ModelLockEnforcementLogic()


def _validation_issue(
    *,
    code: str,
    message: str,
    key_id: str | None = None,
    model_id: str | None = None,
    severity: str = "error",
) -> ModelLockValidationIssue:
    return ModelLockValidationIssue(
        severity=severity,
        code=code,
        message=message,
        key_id=key_id,
        model_id=model_id,
    )


def build_model_lock_validation_result(
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> ModelLockRegistryValidationResult:
    binding_count = 0
    try:
        bindings = _validated_ai_bindings(raw_bindings)
        binding_count = len(bindings)
        locks = validate_model_lock_registry(raw_locks, raw_bindings)
    except (TypeError, ValueError, ValidationError) as exc:
        return ModelLockRegistryValidationResult(
            valid=False,
            issues=[
                _validation_issue(
                    code="c14x_b_model_lock_invalid",
                    message=str(exc),
                )
            ],
            lock_count=0,
            locked_count=0,
            c14x_a_binding_count=binding_count,
        )

    return ModelLockRegistryValidationResult(
        valid=True,
        issues=[],
        lock_count=len(locks),
        locked_count=sum(1 for lock in locks if lock.locked),
        c14x_a_binding_count=len(bindings),
    )


def get_model_lock_by_key(
    key_id: str,
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> ModelLockRegistryRecord | None:
    for lock in validate_model_lock_registry(raw_locks, raw_bindings):
        if lock.key_id == key_id:
            return lock
    return None


def _safe_request_key(key_id: str) -> str | None:
    if not AI_BINDING_KEY_PATTERN.fullmatch(key_id):
        return None
    if _contains_sensitive_marker(key_id):
        return None
    return key_id


def _safe_request_model(model_id: str) -> str | None:
    if not AI_MODEL_REF_PATTERN.fullmatch(model_id):
        return None
    if _contains_sensitive_marker(model_id):
        return None
    return model_id


def _request_rejection(
    *,
    key_id: str,
    requested_model_id: str,
    locked_model_id: str | None = None,
    rejection_code: str,
    rejection_reason: str,
) -> ModelLockRequestValidationResult:
    return ModelLockRequestValidationResult(
        key_id=key_id,
        requested_model_id=requested_model_id,
        locked_model_id=locked_model_id,
        valid=False,
        lock_validation_passed=False,
        execution_rejected=True,
        rejection_code=rejection_code,
        rejection_reason=rejection_reason,
    )


def validate_model_lock_request(
    *,
    key_id: str,
    requested_model_id: str,
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> ModelLockRequestValidationResult:
    safe_key_id = _safe_request_key(key_id)
    safe_requested_model_id = _safe_request_model(requested_model_id)
    if safe_key_id is None or safe_requested_model_id is None:
        return _request_rejection(
            key_id=safe_key_id or INVALID_REQUEST_KEY,
            requested_model_id=safe_requested_model_id or INVALID_REQUEST_MODEL,
            rejection_code="c14x_b_model_lock_request_invalid",
            rejection_reason=(
                "Execution rejected because the request key_id or model_id "
                "does not match the model lock identifier policy."
            ),
        )

    try:
        locks = validate_model_lock_registry(raw_locks, raw_bindings)
    except (TypeError, ValueError, ValidationError) as exc:
        return _request_rejection(
            key_id=safe_key_id,
            requested_model_id=safe_requested_model_id,
            rejection_code="c14x_b_model_lock_registry_invalid",
            rejection_reason=(
                "Execution rejected because the model lock registry is "
                f"invalid: {exc}"
            ),
        )

    lock_by_key = {lock.key_id: lock for lock in locks}
    lock = lock_by_key.get(safe_key_id)
    if lock is None:
        return _request_rejection(
            key_id=safe_key_id,
            requested_model_id=safe_requested_model_id,
            rejection_code="c14x_b_model_lock_missing",
            rejection_reason=(
                "Execution rejected because no model lock exists for the "
                "requested key_id; fallback model selection is forbidden."
            ),
        )

    if lock.model_id != safe_requested_model_id:
        return _request_rejection(
            key_id=safe_key_id,
            requested_model_id=safe_requested_model_id,
            locked_model_id=lock.model_id,
            rejection_code="c14x_b_model_lock_mismatch",
            rejection_reason=(
                "Execution rejected because requested model_id does not "
                "match the locked model_id; runtime model switching is "
                "forbidden."
            ),
        )

    return ModelLockRequestValidationResult(
        key_id=safe_key_id,
        requested_model_id=safe_requested_model_id,
        locked_model_id=lock.model_id,
        valid=True,
        lock_validation_passed=True,
        execution_rejected=False,
        rejection_code=None,
        rejection_reason=(
            "Model lock validation passed. This does not grant runtime "
            "execution, model invocation, fallback routing, or external API "
            "access."
        ),
    )


def get_model_lock_c14x_a_integration() -> ModelLockC14XAIntegration:
    return ModelLockC14XAIntegration()


def get_model_lock_completion_status() -> ModelLockCompletionStatus:
    return ModelLockCompletionStatus(
        proceed_reason=(
            "C14X-B defines immutable key_id -> model_id locks, exact "
            "request validation, and C14X-A integration without runtime "
            "execution."
        )
    )
