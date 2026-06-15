from __future__ import annotations

from typing import Any

from ..schemas.common import (
    contains_runtime_address_data,
    reject_runtime_address_data,
    sanitize_runtime_address_data,
)
from ..schemas.security_isolation import (
    GatewayEnforcementModel,
    SecurityFirewallRule,
    SecurityFirewallRules,
    SecurityIsolationArchitecture,
    SecurityIsolationCompletionStatus,
    WebhookHidingMechanism,
)


def get_security_isolation_architecture() -> SecurityIsolationArchitecture:
    return SecurityIsolationArchitecture()


def get_security_firewall_rules() -> SecurityFirewallRules:
    return SecurityFirewallRules(
        rules=(
            SecurityFirewallRule(
                rule_id="c15g_frontend_proxy_deny_direct_webhook",
                layer="frontend_proxy",
                target="/api/backend/webhook* and /api/backend/n8n*",
                behavior="deny",
                reason=(
                    "The frontend backend proxy must not relay direct webhook "
                    "or n8n paths."
                ),
            ),
            SecurityFirewallRule(
                rule_id="c15g_backend_deny_direct_webhook",
                layer="backend_api",
                target="/webhook* and /n8n*",
                behavior="deny",
                reason=(
                    "Direct backend webhook and n8n paths are explicit "
                    "firewall denials."
                ),
            ),
            SecurityFirewallRule(
                rule_id="c15g_edge_template_deny_public_webhook",
                layer="edge_nginx_template",
                target="/webhook*, /n8n*, /api/backend/webhook*",
                behavior="deny",
                reason=(
                    "The reviewed Nginx template blocks public bypass paths "
                    "before they reach application routing."
                ),
            ),
            SecurityFirewallRule(
                rule_id="c15g_gateway_requires_signed_c15f_request",
                layer="gateway",
                target="POST /webhook-gateway/ingress",
                behavior="require_signed_gateway",
                reason=(
                    "C15B accepts only signed payloads that also pass C15F "
                    "module workflow binding validation."
                ),
            ),
            SecurityFirewallRule(
                rule_id="c15g_operation_log_runtime_address_sanitizer",
                layer="operation_log_sanitizer",
                target="operation_logs.details",
                behavior="sanitize",
                reason=(
                    "Runtime URLs, n8n webhook references, endpoint fields, "
                    "and credential-like fields are removed or redacted."
                ),
            ),
        )
    )


def get_webhook_hiding_mechanism() -> WebhookHidingMechanism:
    return WebhookHidingMechanism()


def get_gateway_enforcement_model() -> GatewayEnforcementModel:
    return GatewayEnforcementModel()


def sanitize_security_isolation_payload(value: Any) -> Any:
    return sanitize_runtime_address_data(value)


def reject_security_isolation_payload(value: Any) -> Any:
    return reject_runtime_address_data(value)


def has_security_isolation_leak(value: Any) -> bool:
    return contains_runtime_address_data(value)


def get_security_isolation_completion_status() -> SecurityIsolationCompletionStatus:
    return SecurityIsolationCompletionStatus(
        proceed_reason=(
            "C15G defines the isolation architecture, API firewall rules, "
            "webhook hiding mechanism, gateway enforcement model, and log "
            "sanitization without runtime execution, external calls, "
            "production changes, or staging changes."
        )
    )
