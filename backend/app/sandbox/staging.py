from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..schemas.execution_router import ExecutionRouterResponse


STAGING_SANDBOX_STAGE: Literal["c10_staging_runtime_layer"] = (
    "c10_staging_runtime_layer"
)


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


class StagingSandboxPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str = Field(min_length=1, max_length=180)
    isolated_execution_context: Literal[True] = True
    staging_secrets_namespace: str = Field(min_length=1, max_length=180)
    production_db_access_allowed: Literal[False] = False
    production_secret_access_allowed: Literal[False] = False
    controlled_external_calls: tuple[
        Literal["n8n_test_endpoint"],
        Literal["mock_endpoint"],
    ] = ("n8n_test_endpoint", "mock_endpoint")
    arbitrary_external_call_allowed: Literal[False] = False
    audit_logging_required: Literal[True] = True
    c17_integration_ready: Literal[True] = True


class StagingSandboxRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1, max_length=180)
    org_id: str = Field(min_length=1, max_length=68)
    module_id: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    action: str = Field(min_length=1, max_length=180)
    provider_key: str = Field(min_length=1, max_length=180)
    execution_mode: Literal["staging"] = "staging"
    payload_shape: dict[str, Any] = Field(default_factory=dict)
    context_ref: str = Field(min_length=1, max_length=180)
    policy: StagingSandboxPolicy


class StagingSandboxResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    response_id: str = Field(min_length=1, max_length=180)
    stage: Literal["c10_staging_runtime_layer"] = STAGING_SANDBOX_STAGE
    request: StagingSandboxRequest
    status: Literal["prepared", "blocked"] = "prepared"
    execution_dispatched: Literal[False] = False
    external_call_performed: Literal[False] = False
    production_db_access_performed: Literal[False] = False
    production_touched: Literal[False] = False
    staging_secret_namespace_bound: Literal[True] = True
    audit_log_prepared: Literal[True] = True
    c17_event_ready: Literal[True] = True
    prepared_at: datetime
    safety_notes: tuple[str, ...] = (
        "StagingSandbox prepares an isolated staging context only.",
        "Production database and production secret access are denied.",
        "Controlled external calls are limited to n8n test or mock endpoints.",
        "No external call is performed by this architecture layer.",
    )


class StagingSandbox:
    """C10 staging runtime layer.

    This layer is staging-ready architecture only. It prepares isolated
    context and policy records but never performs an external call.
    """

    def prepare(
        self,
        router_response: ExecutionRouterResponse,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> StagingSandboxResponse:
        if router_response.selected_provider is None:
            raise ValueError("StagingSandbox requires a selected provider.")
        if router_response.execution_plan.execution_mode != "staging":
            raise ValueError("StagingSandbox can only prepare staging mode.")
        payload_shape = self._shape(payload or {})
        context_ref = _stable_id(
            "staging_context",
            {
                "plan_id": router_response.execution_plan.plan_id,
                "provider_key": router_response.selected_provider.provider_key,
                "org_id": router_response.execution_plan.org_id,
            },
        )
        policy = StagingSandboxPolicy(
            policy_id=_stable_id(
                "staging_policy",
                {
                    "org_id": router_response.execution_plan.org_id,
                    "module_id": router_response.execution_plan.module_id,
                    "provider_key": router_response.selected_provider.provider_key,
                },
            ),
            staging_secrets_namespace=(
                "staging/"
                f"{router_response.execution_plan.org_id}/"
                f"{router_response.execution_plan.module_id}"
            ),
        )
        request = StagingSandboxRequest(
            request_id=_stable_id(
                "staging_request",
                {
                    "plan_id": router_response.execution_plan.plan_id,
                    "payload_shape": payload_shape,
                },
            ),
            org_id=router_response.execution_plan.org_id,
            module_id=router_response.execution_plan.module_id,
            adapter_key=router_response.execution_plan.adapter_key,
            action=router_response.execution_plan.action,
            provider_key=router_response.selected_provider.provider_key,
            payload_shape=payload_shape,
            context_ref=context_ref,
            policy=policy,
        )
        return StagingSandboxResponse(
            response_id=_stable_id(
                "staging_response",
                {
                    "request_id": request.request_id,
                    "policy_id": policy.policy_id,
                },
            ),
            request=request,
            prepared_at=datetime.now(UTC),
        )

    def _shape(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "key_count": len(value),
            "keys": sorted(str(key) for key in value.keys()),
            "values_redacted": True,
        }
