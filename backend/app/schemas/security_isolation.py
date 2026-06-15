from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SecurityIsolationNode = Literal[
    "Module",
    "C15C Payload Standardization",
    "C15F Module Workflow Binding",
    "C15B Webhook Gateway",
    "C15A Workflow Registry",
    "internal hidden webhook resolver",
    "n8n",
    "C15D Callback Handler",
    "C15E Result Normalization",
]
SecurityFirewallLayer = Literal[
    "frontend_proxy",
    "backend_api",
    "edge_nginx_template",
    "gateway",
    "operation_log_sanitizer",
]
SecurityFirewallBehavior = Literal[
    "deny",
    "sanitize",
    "require_signed_gateway",
    "require_c15f_binding",
]


class SecurityIsolationArchitecture(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    architecture_id: Literal["c15g_security_isolation_architecture_v1"] = (
        "c15g_security_isolation_architecture_v1"
    )
    stage: Literal["C15G"] = "C15G"
    component: Literal["Security & Isolation Layer"] = (
        "Security & Isolation Layer"
    )
    allowed_execution_path: tuple[SecurityIsolationNode, ...] = (
        "Module",
        "C15C Payload Standardization",
        "C15F Module Workflow Binding",
        "C15B Webhook Gateway",
        "C15A Workflow Registry",
        "internal hidden webhook resolver",
        "n8n",
        "C15D Callback Handler",
        "C15E Result Normalization",
    )
    only_n8n_entrypoint: Literal["C15B Webhook Gateway"] = (
        "C15B Webhook Gateway"
    )
    frontend_can_access_n8n_url: Literal[False] = False
    module_can_access_n8n_url: Literal[False] = False
    direct_n8n_access_allowed: Literal[False] = False
    gateway_bypass_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False
    staging_change_allowed: Literal[False] = False


class SecurityFirewallRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str = Field(min_length=1, max_length=180)
    layer: SecurityFirewallLayer
    target: str = Field(min_length=1, max_length=180)
    behavior: SecurityFirewallBehavior
    reason: str = Field(min_length=1, max_length=500)


class SecurityFirewallRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rules_id: Literal["c15g_api_firewall_rules_v1"] = (
        "c15g_api_firewall_rules_v1"
    )
    rules: tuple[SecurityFirewallRule, ...]
    blocked_direct_paths: tuple[str, ...] = (
        "/webhook",
        "/webhook/*",
        "/n8n",
        "/n8n/*",
        "/api/backend/webhook",
        "/api/backend/webhook/*",
        "/api/backend/n8n",
        "/api/backend/n8n/*",
    )
    frontend_backend_proxy_allowlist_required: Literal[True] = True
    direct_webhook_access_blocked: Literal[True] = True
    external_bypass_calls_blocked: Literal[True] = True
    unauthorized_http_access_blocked: Literal[True] = True
    no_external_api_surface_expansion: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False


class WebhookHidingMechanism(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mechanism_id: Literal["c15g_webhook_hiding_v1"] = (
        "c15g_webhook_hiding_v1"
    )
    storage_rule: Literal[
        "real n8n URLs stay outside frontend and module contracts"
    ] = "real n8n URLs stay outside frontend and module contracts"
    registry_rule: Literal[
        "C15A registry stores opaque references only"
    ] = "C15A registry stores opaque references only"
    gateway_rule: Literal[
        "C15B may resolve hidden references internally only"
    ] = "C15B may resolve hidden references internally only"
    response_rule: Literal[
        "responses must not include n8n URLs or hidden webhook references"
    ] = "responses must not include n8n URLs or hidden webhook references"
    log_rule: Literal[
        "operation logs sanitize runtime URL and webhook reference data"
    ] = "operation logs sanitize runtime URL and webhook reference data"
    real_n8n_url_in_frontend_allowed: Literal[False] = False
    real_n8n_url_in_module_allowed: Literal[False] = False
    real_n8n_url_in_response_allowed: Literal[False] = False
    hidden_webhook_ref_in_gateway_response_allowed: Literal[False] = False
    webhook_url_in_logs_allowed: Literal[False] = False


class GatewayEnforcementModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c15g_gateway_enforcement_v1"] = (
        "c15g_gateway_enforcement_v1"
    )
    required_path: Literal["Module -> C15F -> C15B -> n8n"] = (
        "Module -> C15F -> C15B -> n8n"
    )
    c15b_only_entrypoint_to_n8n: Literal[True] = True
    c15f_binding_required_before_gateway_accept: Literal[True] = True
    c15a_registry_required_before_hidden_ref_resolution: Literal[True] = True
    signed_gateway_payload_required: Literal[True] = True
    direct_n8n_access_behavior: Literal["reject"] = "reject"
    direct_webhook_path_behavior: Literal["reject"] = "reject"
    unbound_workflow_behavior: Literal["reject"] = "reject"
    cross_module_workflow_behavior: Literal["reject"] = "reject"
    gateway_bypass_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class SecurityIsolationCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15G"] = "C15G"
    component: Literal["Security & Isolation Layer"] = (
        "Security & Isolation Layer"
    )
    completion_status: Literal["complete"] = "complete"
    isolation_architecture_defined: Literal[True] = True
    firewall_rules_defined: Literal[True] = True
    webhook_hiding_mechanism_defined: Literal[True] = True
    gateway_enforcement_model_defined: Literal[True] = True
    c15b_only_entrypoint_enforced: Literal[True] = True
    direct_webhook_access_blocked: Literal[True] = True
    response_url_sanitization_defined: Literal[True] = True
    operation_log_sanitization_defined: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_external_api_change: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True
    can_proceed_to_c15h: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=700)
