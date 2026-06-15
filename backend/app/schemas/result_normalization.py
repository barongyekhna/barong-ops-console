from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import reject_sensitive_data


ResultExecutionStatus = Literal[
    "pending",
    "running",
    "success",
    "failed",
    "unknown",
]
ResultModuleFamily = Literal["K", "P", "SEO", "generic"]
ResultSourceSchema = Literal[
    "workflow_specific",
    "standard_json",
    "fallback",
]
ResultSourceFormat = Literal[
    "c15d_storage",
    "c15d_notification",
    "n8n_items",
    "json_object",
    "json_string",
    "json_list",
    "fallback",
]
ResultStandardField = Literal[
    "context_id",
    "module",
    "workflow_id",
    "status",
    "result",
    "metadata",
]

RESULT_RUNTIME_KEY_MARKERS = (
    "n8n_webhook",
    "webhook_url",
    "webhook",
    "endpoint",
    "url",
    "authorization",
    "api_key",
    "token",
    "secret",
    "credential",
    "password",
)
RESULT_RUNTIME_VALUE_MARKERS = (
    "http://",
    "https://",
    "n8n-webhook-ref://",
    "authorization:",
    "bearer ",
)


def reject_result_runtime_data(value: Any) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(
                marker in normalized_key for marker in RESULT_RUNTIME_KEY_MARKERS
            ):
                raise ValueError(
                    "Runtime access or credential fields are not allowed in C15E result."
                )
            reject_result_runtime_data(item)
    elif isinstance(value, list):
        for item in value:
            reject_result_runtime_data(item)
    elif isinstance(value, str):
        lowered_value = value.lower()
        if any(marker in lowered_value for marker in RESULT_RUNTIME_VALUE_MARKERS):
            raise ValueError(
                "Runtime access or credential values are not allowed in C15E result."
            )
    return value


class ResultNormalizationMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15E"] = "C15E"
    component: Literal["Result Normalization Layer"] = (
        "Result Normalization Layer"
    )
    result_schema_version: Literal["c15e_standard_result_v1"] = (
        "c15e_standard_result_v1"
    )
    normalized_at: str = Field(min_length=1, max_length=40)
    module_family: ResultModuleFamily
    adapter_rule: str = Field(min_length=1, max_length=180)
    schema_mapping_id: str | None = Field(default=None, max_length=180)
    source_schema: ResultSourceSchema
    source_format: ResultSourceFormat
    fallback_used: bool
    extracted_fields: tuple[ResultStandardField, ...]
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    frontend_consumable: Literal[True] = True
    raw_n8n_structure_exposed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False

    @field_validator("normalized_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("source_metadata")
    @classmethod
    def validate_source_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        reject_sensitive_data(value)
        reject_result_runtime_data(value)
        return value


class NormalizedWorkflowResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    context_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    status: ResultExecutionStatus
    result: dict[str, Any] = Field(default_factory=dict)
    metadata: ResultNormalizationMetadata

    @field_validator("result")
    @classmethod
    def validate_result(cls, value: dict[str, Any]) -> dict[str, Any]:
        reject_sensitive_data(value)
        reject_result_runtime_data(value)
        return value


class ResultSchemaMappingRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mapping_id: str = Field(min_length=1, max_length=180)
    workflow_id: str = Field(min_length=1, max_length=180)
    module: str | None = Field(default=None, max_length=128)
    field_paths: dict[ResultStandardField, tuple[str, ...]]
    result_paths: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    metadata_paths: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    fallback_result_path: tuple[str, ...] | None = None

    @field_validator("field_paths")
    @classmethod
    def validate_field_paths(
        cls,
        value: dict[ResultStandardField, tuple[str, ...]],
    ) -> dict[ResultStandardField, tuple[str, ...]]:
        required = {"context_id", "module", "workflow_id"}
        missing = required.difference(value)
        if missing:
            raise ValueError(
                "C15E mapping field_paths must include context_id, module, and workflow_id."
            )
        return value


class ResultNormalizationEngineDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine_id: Literal["c15e_result_normalization_engine_v1"] = (
        "c15e_result_normalization_engine_v1"
    )
    standard_output_fields: tuple[ResultStandardField, ...] = (
        "context_id",
        "module",
        "workflow_id",
        "status",
        "result",
        "metadata",
    )
    flow: tuple[str, ...] = (
        "Parse direct JSON objects, JSON strings, n8n item arrays, or C15D result records.",
        "Apply workflow-specific schema mappings when a workflow_id rule matches.",
        "Fallback to common JSON extraction when no mapping exists.",
        "Apply K/P/SEO module adapter rules to the sanitized result object.",
        "Return only the C15E standard output shape for frontend consumption.",
    )
    flexible_json_parsing_supported: Literal[True] = True
    fallback_normalization_supported: Literal[True] = True
    raw_n8n_structure_exposed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    n8n_dispatch_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False


class ResultSchemaMappingModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c15e_schema_mapping_model_v1"] = (
        "c15e_schema_mapping_model_v1"
    )
    mapping_direction: Literal["workflow-specific -> standard result schema"] = (
        "workflow-specific -> standard result schema"
    )
    standard_fields: tuple[ResultStandardField, ...] = (
        "context_id",
        "module",
        "workflow_id",
        "status",
        "result",
        "metadata",
    )
    path_lookup_supported: Literal[True] = True
    list_index_path_segments_supported: Literal[True] = True
    common_json_aliases_supported: Literal[True] = True
    missing_mapping_behavior: Literal["fallback_normalization"] = (
        "fallback_normalization"
    )
    invalid_mapping_behavior: Literal["fallback_normalization"] = (
        "fallback_normalization"
    )
    raw_n8n_structure_exposed: Literal[False] = False


class ResultModuleAdapterRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rules_id: Literal["c15e_module_adapter_rules_v1"] = (
        "c15e_module_adapter_rules_v1"
    )
    supported_module_families: tuple[
        Literal["K"],
        Literal["P"],
        Literal["SEO"],
    ] = ("K", "P", "SEO")
    standard_result_shape: tuple[Literal["summary"], Literal["items"], Literal["data"]] = (
        "summary",
        "items",
        "data",
    )
    k_series_rule: Literal[
        "knowledge outputs map answer/insights/recommendations into summary/items/data"
    ] = "knowledge outputs map answer/insights/recommendations into summary/items/data"
    p_series_rule: Literal[
        "product outputs map product/products/items/draft/listing into summary/items/data"
    ] = "product outputs map product/products/items/draft/listing into summary/items/data"
    seo_rule: Literal[
        "SEO outputs map keywords/recommendations/title/meta_description into summary/items/data"
    ] = "SEO outputs map keywords/recommendations/title/meta_description into summary/items/data"
    generic_rule: Literal["sanitize and pass through as data"] = (
        "sanitize and pass through as data"
    )
    output_structure_unified: Literal[True] = True
    external_module_call_performed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False


class ResultUIOutputStructure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    structure_id: Literal["c15e_frontend_result_contract_v1"] = (
        "c15e_frontend_result_contract_v1"
    )
    top_level_fields: tuple[ResultStandardField, ...] = (
        "context_id",
        "module",
        "workflow_id",
        "status",
        "result",
        "metadata",
    )
    result_field_type: Literal["JSON object"] = "JSON object"
    metadata_field_type: Literal["C15E normalization metadata"] = (
        "C15E normalization metadata"
    )
    frontend_can_consume_directly: Literal[True] = True
    raw_n8n_structure_exposed: Literal[False] = False
    callback_storage_fields_exposed: Literal[False] = False
    workflow_output_field_exposed: Literal[False] = False
    execution_metadata_field_exposed: Literal[False] = False


class ResultNormalizationCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15E"] = "C15E"
    component: Literal["Result Normalization Layer"] = (
        "Result Normalization Layer"
    )
    completion_status: Literal["complete"] = "complete"
    output_normalization_engine_defined: Literal[True] = True
    schema_mapping_system_defined: Literal[True] = True
    module_adapter_layer_defined: Literal[True] = True
    ui_compatibility_layer_defined: Literal[True] = True
    no_raw_n8n_structure_exposed: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False
    can_proceed_to_c15f: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=700)
