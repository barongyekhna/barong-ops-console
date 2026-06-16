from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class OrgDataIsolationLayerDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    layer_id: Literal["c18g_org_data_isolation_kernel_v1"] = (
        "c18g_org_data_isolation_kernel_v1"
    )
    partition_key: Literal["org_id"] = "org_id"
    all_data_requires_org_id: Literal[True] = True
    all_queries_org_scoped: Literal[True] = True
    cross_org_access_allowed: Literal[False] = False
    owner_read_scope_bypass_allowed: Literal[True] = True
    write_scope_bypass_allowed: Literal[False] = False
    migration_executed: Literal[False] = False
    schema_refactor_executed: Literal[False] = False
    ui_modified: Literal[False] = False


class OrgDataIsolationInjectionLogic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    if_query_missing_org_id: Literal["auto_inject_current_org_id"] = (
        "auto_inject_current_org_id"
    )
    if_query_contains_other_org_id: Literal["override_with_current_org_id"] = (
        "override_with_current_org_id"
    )
    if_context_missing_for_org_data: Literal["block"] = "block"
    if_role_owner_reads: Literal["return_query_without_org_restriction"] = (
        "return_query_without_org_restriction"
    )
    implemented_by: tuple[
        Literal["OrgDataIsolationLayer.apply_scope"],
        Literal["SQLAlchemy do_orm_execute hook"],
        Literal["OrgDataIsolationSession.execute guard"],
    ] = (
        "OrgDataIsolationLayer.apply_scope",
        "SQLAlchemy do_orm_execute hook",
        "OrgDataIsolationSession.execute guard",
    )


class OrgDataIsolationQueryInterceptionSystem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intercepts_select: Literal[True] = True
    intercepts_orm_get: Literal[True] = True
    intercepts_update: Literal[True] = True
    intercepts_delete: Literal[True] = True
    intercepts_raw_sql: Literal[True] = True
    raw_sql_without_org_filter_allowed: Literal[False] = False
    applies_to_future_org_scoped_models: Literal[True] = True


class OrgDataIsolationApiEnforcementStrategy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org_source_priority: tuple[
        Literal["C18F permission decision"],
        Literal["C18C active org path/context"],
        Literal["validated request context fallback"],
    ] = (
        "C18F permission decision",
        "C18C active org path/context",
        "validated request context fallback",
    )
    frontend_body_org_id_allowed: Literal[False] = False
    backend_overwrites_org_id: Literal[True] = True
    jwt_or_session_user_required: Literal[True] = True
    permission_gate_runs_before_data_access: Literal[True] = True


class OrgDataIsolationWriteProtectionRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    inserts_attach_org_id_automatically: Literal[True] = True
    inserts_missing_org_context_rejected: Literal[True] = True
    conflicting_insert_org_id_rejected: Literal[True] = True
    updates_cross_org_rejected: Literal[True] = True
    deletes_cross_org_rejected: Literal[True] = True
    organization_must_exist: Literal[True] = True


class OrgDataIsolationAttackPreventionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org_a_can_read_org_b: Literal[False] = False
    cross_org_api_query_bypass_allowed: Literal[False] = False
    manual_sql_without_org_filter_allowed: Literal[False] = False
    request_payload_org_id_trusted: Literal[False] = False
    owner_write_cross_org_without_context_allowed: Literal[False] = False


class OrgDataIsolationIntegrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    c18c_user_org_context_used: Literal[True] = True
    c18f_permission_pre_query_gate_used: Literal[True] = True
    c17_audit_hook_used: Literal[True] = True
    flow: tuple[
        Literal["Request"],
        Literal["C18F Permission Check"],
        Literal["C18G Org Data Isolation Layer"],
        Literal["Repository Query with org filter"],
        Literal["Database"],
    ] = (
        "Request",
        "C18F Permission Check",
        "C18G Org Data Isolation Layer",
        "Repository Query with org filter",
        "Database",
    )


class OrgDataIsolationUniversalCompatibility(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_name_hardcoding_allowed: Literal[False] = False
    supports_future_modules: Literal[True] = True
    dynamic_module_org_binding_via_c18d: Literal[True] = True
    detection_rule: Literal["any mapped model with an org_id column is protected"] = (
        "any mapped model with an org_id column is protected"
    )
    recommended_model_mixin: Literal["OrgScopedMixin"] = "OrgScopedMixin"


class OrgDataIsolationCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C18G"] = "C18G"
    component: Literal["Cross-Org Data Isolation"] = "Cross-Org Data Isolation"
    completion_status: Literal["complete"] = "complete"
    data_isolation_kernel_implemented: Literal[True] = True
    query_interception_implemented: Literal[True] = True
    write_protection_implemented: Literal[True] = True
    api_context_middleware_implemented: Literal[True] = True
    migration_executed: Literal[False] = False
    ui_implemented: Literal[False] = False


def get_org_data_isolation_layer_design() -> OrgDataIsolationLayerDesign:
    return OrgDataIsolationLayerDesign()


def get_org_data_isolation_injection_logic() -> OrgDataIsolationInjectionLogic:
    return OrgDataIsolationInjectionLogic()


def get_org_data_isolation_query_interception_system() -> (
    OrgDataIsolationQueryInterceptionSystem
):
    return OrgDataIsolationQueryInterceptionSystem()


def get_org_data_isolation_api_enforcement_strategy() -> (
    OrgDataIsolationApiEnforcementStrategy
):
    return OrgDataIsolationApiEnforcementStrategy()


def get_org_data_isolation_write_protection_rules() -> (
    OrgDataIsolationWriteProtectionRules
):
    return OrgDataIsolationWriteProtectionRules()


def get_org_data_isolation_attack_prevention_model() -> (
    OrgDataIsolationAttackPreventionModel
):
    return OrgDataIsolationAttackPreventionModel()


def get_org_data_isolation_integration_model() -> (
    OrgDataIsolationIntegrationModel
):
    return OrgDataIsolationIntegrationModel()


def get_org_data_isolation_universal_compatibility() -> (
    OrgDataIsolationUniversalCompatibility
):
    return OrgDataIsolationUniversalCompatibility()


def get_org_data_isolation_completion_status() -> (
    OrgDataIsolationCompletionStatus
):
    return OrgDataIsolationCompletionStatus()
