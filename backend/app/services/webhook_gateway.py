from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

from ..core.config import Settings
from ..schemas.webhook_gateway import (
    WebhookGatewayCompletionStatus,
    WebhookGatewayDecision,
    WebhookGatewayDesign,
    WebhookGatewayLookupFlow,
    WebhookGatewayPayloadFormat,
    WebhookGatewayRequest,
    WebhookGatewaySignatureModel,
)
from .module_workflow_binding_engine import evaluate_module_workflow_access
from .workflow_registry_system import evaluate_workflow_invocation

SIGNATURE_PREFIX = "sha256="


class WebhookGatewayConfigurationError(RuntimeError):
    pass


class WebhookGatewaySignatureError(RuntimeError):
    pass


def _secret_value(value: SecretStr | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)


def _parse_timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def canonical_webhook_gateway_payload(
    payload: WebhookGatewayRequest,
) -> str:
    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def sign_webhook_gateway_payload(
    payload: WebhookGatewayRequest,
    *,
    secret: SecretStr | str,
) -> str:
    secret_text = _secret_value(secret)
    digest = hmac.new(
        secret_text.encode("utf-8"),
        canonical_webhook_gateway_payload(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_webhook_gateway_signature(
    payload: WebhookGatewayRequest,
    *,
    provided_signature: str | None,
    settings: Settings,
) -> None:
    secret = _secret_value(settings.webhook_gateway_signing_secret)
    if not secret:
        raise WebhookGatewayConfigurationError(
            "C15B webhook gateway signing secret is not configured."
        )
    if not provided_signature:
        raise WebhookGatewaySignatureError(
            "C15B webhook gateway signature is required."
        )

    expected_signature = sign_webhook_gateway_payload(
        payload,
        secret=secret,
    )
    candidate = provided_signature.strip()
    if not candidate.startswith(SIGNATURE_PREFIX):
        candidate = f"{SIGNATURE_PREFIX}{candidate}"
    if not hmac.compare_digest(candidate, expected_signature):
        raise WebhookGatewaySignatureError(
            "C15B webhook gateway signature is invalid."
        )

    signed_at = _parse_timestamp(payload.timestamp)
    age_seconds = abs((datetime.now(UTC) - signed_at).total_seconds())
    if age_seconds > settings.webhook_gateway_signature_tolerance_seconds:
        raise WebhookGatewaySignatureError(
            "C15B webhook gateway timestamp is outside the accepted window."
        )


def build_webhook_gateway_decision(
    payload: WebhookGatewayRequest,
    *,
    provided_signature: str | None,
    settings: Settings,
) -> WebhookGatewayDecision:
    verify_webhook_gateway_signature(
        payload,
        provided_signature=provided_signature,
        settings=settings,
    )
    registry_decision = evaluate_workflow_invocation(
        module=payload.module,
        workflow_id=payload.workflow_id,
    )
    binding_decision = evaluate_module_workflow_access(
        module_id=payload.module,
        workflow_id=payload.workflow_id,
    )
    if not binding_decision.binding_validation_passed:
        return WebhookGatewayDecision(
            gateway_status="rejected",
            reason=(
                "C15G gateway enforcement rejected the request before the "
                f"n8n boundary: {binding_decision.reason}"
            ),
            module=payload.module,
            workflow_id=payload.workflow_id,
            context_id=payload.context_id,
            standardized_payload=payload,
            c15a_registered=registry_decision.registered,
            c15a_bound_to_module=registry_decision.bound_to_module,
            c15a_workflow_status=registry_decision.status,
            c15a_execution_allowed=False,
            hidden_webhook_reference_resolved=False,
        )

    hidden_ref_resolved = (
        registry_decision.execution_allowed
        and registry_decision.hidden_webhook_ref is not None
    )
    if not hidden_ref_resolved:
        return WebhookGatewayDecision(
            gateway_status="rejected",
            reason=registry_decision.reason,
            module=payload.module,
            workflow_id=payload.workflow_id,
            context_id=payload.context_id,
            standardized_payload=payload,
            c15a_registered=registry_decision.registered,
            c15a_bound_to_module=registry_decision.bound_to_module,
            c15a_workflow_status=registry_decision.status,
            c15a_execution_allowed=False,
            hidden_webhook_reference_resolved=False,
        )

    return WebhookGatewayDecision(
        gateway_status="accepted",
        reason=(
            "Signature validated and C15A returned an active module-bound "
            "workflow. C15B resolved only the hidden webhook reference."
        ),
        module=payload.module,
        workflow_id=payload.workflow_id,
        context_id=payload.context_id,
        standardized_payload=payload,
        c15a_registered=registry_decision.registered,
        c15a_bound_to_module=registry_decision.bound_to_module,
        c15a_workflow_status=registry_decision.status,
        c15a_execution_allowed=True,
        hidden_webhook_reference_resolved=True,
    )


def get_webhook_gateway_design() -> WebhookGatewayDesign:
    return WebhookGatewayDesign()


def get_webhook_gateway_signature_model(
    settings: Settings,
) -> WebhookGatewaySignatureModel:
    return WebhookGatewaySignatureModel(
        replay_window_seconds=(
            settings.webhook_gateway_signature_tolerance_seconds
        )
    )


def get_webhook_gateway_payload_format() -> WebhookGatewayPayloadFormat:
    return WebhookGatewayPayloadFormat()


def get_webhook_gateway_lookup_flow() -> WebhookGatewayLookupFlow:
    return WebhookGatewayLookupFlow()


def get_webhook_gateway_completion_status() -> WebhookGatewayCompletionStatus:
    return WebhookGatewayCompletionStatus(
        proceed_reason=(
            "C15B defines the signed gateway entry, standard payload contract, "
            "C15A workflow lookup integration, and no-bypass security rules "
            "without exposing n8n URLs or performing runtime execution."
        )
    )
