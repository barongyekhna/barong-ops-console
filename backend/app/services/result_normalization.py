from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from ..schemas.common import reject_sensitive_data
from ..schemas.result_normalization import (
    NormalizedWorkflowResult,
    ResultExecutionStatus,
    ResultModuleAdapterRules,
    ResultModuleFamily,
    ResultNormalizationCompletionStatus,
    ResultNormalizationEngineDesign,
    ResultNormalizationMetadata,
    ResultSchemaMappingModel,
    ResultSchemaMappingRule,
    ResultSourceFormat,
    ResultSourceSchema,
    ResultUIOutputStructure,
    reject_result_runtime_data,
)


STANDARD_OUTPUT_FIELDS = (
    "context_id",
    "module",
    "workflow_id",
    "status",
    "result",
    "metadata",
)
WRAPPER_OUTPUT_KEYS = ("raw_output", "n8n_output")
COMMON_RESULT_KEYS = (
    "result",
    "output",
    "data",
    "payload",
    "workflow_output",
)
COMMON_METADATA_KEYS = (
    "metadata",
    "execution_metadata",
    "meta",
)
COMMON_CONTEXT_KEYS = (
    "context_id",
    "contextId",
    "correlation_id",
    "trace_id",
)
COMMON_MODULE_KEYS = ("module", "module_key")
COMMON_WORKFLOW_KEYS = ("workflow_id", "workflowId", "workflow")
COMMON_STATUS_KEYS = ("status", "state", "execution_status")
ENVELOPE_KEYS = frozenset(
    COMMON_RESULT_KEYS
    + COMMON_METADATA_KEYS
    + COMMON_CONTEXT_KEYS
    + COMMON_MODULE_KEYS
    + COMMON_WORKFLOW_KEYS
    + COMMON_STATUS_KEYS
    + ("schema_mappings",)
)
N8N_ITEM_STRUCTURE_KEYS = frozenset(("binary", "paireditem", "pairedItem"))
N8N_STRUCTURE_KEYS_TO_DROP = frozenset(
    (
        "binary",
        "paireditem",
        "executiondata",
        "rundata",
        "workflowdata",
        "itemindex",
    )
)
STATUS_ALIASES: dict[str, ResultExecutionStatus] = {
    "pending": "pending",
    "queued": "pending",
    "waiting": "pending",
    "running": "running",
    "in_progress": "running",
    "processing": "running",
    "success": "success",
    "succeeded": "success",
    "complete": "success",
    "completed": "success",
    "ok": "success",
    "failed": "failed",
    "failure": "failed",
    "error": "failed",
    "errored": "failed",
    "unknown": "unknown",
}


def _utc_now_timestamp() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate or None


def _parse_flexible_json(value: Any) -> tuple[Any, ResultSourceFormat]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value, "json_string"
        return parsed, "json_string"
    if isinstance(value, Mapping):
        return value, "json_object"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value, "json_list"
    return value, "fallback"


def _path_value(source: Any, path: Sequence[str] | None) -> Any:
    if not path:
        return None
    current = source
    for segment in path:
        if isinstance(current, Mapping):
            if segment not in current:
                return None
            current = current[segment]
            continue
        if (
            isinstance(current, Sequence)
            and not isinstance(current, (str, bytes, bytearray))
            and str(segment).isdigit()
        ):
            index = int(segment)
            if index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def _first_present(raw: Any, keys: Sequence[str]) -> Any:
    if not isinstance(raw, Mapping):
        return None
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return None


def _normalize_status(value: Any, raw: Any | None = None) -> ResultExecutionStatus:
    text = _string_value(value)
    if text is not None:
        normalized = text.lower().replace("-", "_").replace(" ", "_")
        return STATUS_ALIASES.get(normalized, "unknown")
    if isinstance(raw, Mapping) and any(key in raw for key in ("error", "errors")):
        return "failed"
    if raw is not None:
        return "success"
    return "unknown"


def _module_family(module: str) -> ResultModuleFamily:
    normalized = module.lower().replace("_", ".")
    if normalized.startswith(("k.", "business.k.")) or ".k." in normalized:
        return "K"
    if normalized.startswith(("seo.", "business.seo.")) or ".seo." in normalized:
        return "SEO"
    if (
        normalized.startswith(("p.", "business.p.", "products."))
        or normalized == "business.products"
        or ".products" in normalized
    ):
        return "P"
    return "generic"


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in N8N_STRUCTURE_KEYS_TO_DROP:
                continue
            candidate = {str(key): item}
            reject_sensitive_data(candidate)
            reject_result_runtime_data(candidate)
            sanitized[str(key)] = _sanitize_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value]
    reject_result_runtime_data(value)
    return value


def _as_result_object(value: Any) -> dict[str, Any]:
    sanitized = _sanitize_value(value)
    if isinstance(sanitized, Mapping):
        return dict(sanitized)
    if isinstance(sanitized, list):
        return {"items": sanitized}
    return {"value": sanitized}


def _looks_like_n8n_item(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if "json" not in value:
        return False
    normalized_keys = {str(key).lower() for key in value}
    return bool(normalized_keys.intersection(N8N_ITEM_STRUCTURE_KEYS)) or (
        len(normalized_keys) <= 3
    )


def _unwrap_n8n_items(value: Any) -> tuple[Any, bool]:
    if _looks_like_n8n_item(value):
        return value["json"], True
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        detected = False
        items: list[Any] = []
        for item in value:
            if _looks_like_n8n_item(item):
                detected = True
                items.append(item["json"])
            else:
                items.append(item)
        if detected:
            return {"items": items}, True
    if isinstance(value, Mapping):
        for key in ("data", "items", "result", "output"):
            if key in value:
                unwrapped, detected = _unwrap_n8n_items(value[key])
                if detected:
                    return unwrapped, True
    return value, False


def _extract_common_result(raw: Any) -> tuple[dict[str, Any], ResultSourceFormat]:
    unwrapped, n8n_detected = _unwrap_n8n_items(raw)
    if n8n_detected:
        return _as_result_object(unwrapped), "n8n_items"

    if isinstance(raw, Mapping):
        if "workflow_output" in raw:
            return _as_result_object(raw["workflow_output"]), "c15d_storage"
        notification = raw.get("standardized_result")
        if isinstance(notification, Mapping) and "output" in notification:
            return _as_result_object(notification["output"]), "c15d_notification"
        for key in ("result", "output", "data", "payload"):
            if key in raw:
                return _as_result_object(raw[key]), "json_object"
        fallback_payload = {
            str(key): value for key, value in raw.items() if key not in ENVELOPE_KEYS
        }
        return _as_result_object(fallback_payload), "fallback"

    return _as_result_object(raw), "json_list" if isinstance(raw, list) else "fallback"


def _extract_common_metadata(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    metadata_value = _first_present(raw, COMMON_METADATA_KEYS)
    if metadata_value is None:
        return {}
    return _as_result_object(metadata_value)


def _generate_context_id(raw: Any, module: str, workflow_id: str) -> str:
    digest_source = {
        "module": module,
        "workflow_id": workflow_id,
        "raw": raw,
    }
    digest = hashlib.sha256(
        _canonical_json(digest_source).encode("utf-8")
    ).hexdigest()[:16]
    return f"ctx.c15e.{digest}"


def _coerce_schema_mappings(
    schema_mappings: Sequence[ResultSchemaMappingRule | Mapping[str, Any]] | None,
) -> tuple[ResultSchemaMappingRule, ...]:
    if not schema_mappings:
        return ()
    mappings: list[ResultSchemaMappingRule] = []
    for mapping in schema_mappings:
        if isinstance(mapping, ResultSchemaMappingRule):
            mappings.append(mapping)
        else:
            mappings.append(ResultSchemaMappingRule.model_validate(mapping))
    return tuple(mappings)


def _candidate_workflow_id(raw: Any) -> str | None:
    return _string_value(_first_present(raw, COMMON_WORKFLOW_KEYS))


def _select_schema_mapping(
    *,
    raw: Any,
    workflow_id: str | None,
    module: str | None,
    schema_mappings: Sequence[ResultSchemaMappingRule],
) -> ResultSchemaMappingRule | None:
    for mapping in schema_mappings:
        mapped_workflow = _string_value(
            _path_value(raw, mapping.field_paths.get("workflow_id"))
        )
        candidate = workflow_id or _candidate_workflow_id(raw) or mapped_workflow
        if candidate != mapping.workflow_id:
            continue
        if mapping.module and module and mapping.module != module:
            continue
        return mapping
    return None


def _build_from_mapping(
    *,
    raw: Any,
    mapping: ResultSchemaMappingRule,
    context_id: str | None,
    module: str | None,
    workflow_id: str | None,
    status: str | None,
) -> tuple[str, str, str, ResultExecutionStatus, dict[str, Any], dict[str, Any]]:
    mapped_context_id = _string_value(
        _path_value(raw, mapping.field_paths.get("context_id"))
    )
    mapped_module = _string_value(_path_value(raw, mapping.field_paths.get("module")))
    mapped_workflow_id = _string_value(
        _path_value(raw, mapping.field_paths.get("workflow_id"))
    )
    mapped_status = _path_value(raw, mapping.field_paths.get("status"))

    result_source: Any = None
    if mapping.result_paths:
        result_source = {
            key: _path_value(raw, path)
            for key, path in mapping.result_paths.items()
            if _path_value(raw, path) is not None
        }
    if result_source is None:
        result_source = _path_value(raw, mapping.field_paths.get("result"))
    if result_source is None and mapping.fallback_result_path is not None:
        result_source = _path_value(raw, mapping.fallback_result_path)
    if result_source is None:
        raise ValueError("C15E mapping did not resolve a result payload.")

    metadata_source: Any = {}
    if mapping.metadata_paths:
        metadata_source = {
            key: _path_value(raw, path)
            for key, path in mapping.metadata_paths.items()
            if _path_value(raw, path) is not None
        }
    else:
        metadata_source = _path_value(raw, mapping.field_paths.get("metadata")) or {}

    resolved_module = module or mapped_module or mapping.module or "generic.unknown"
    resolved_workflow_id = workflow_id or mapped_workflow_id or mapping.workflow_id
    resolved_context_id = context_id or mapped_context_id
    if resolved_context_id is None:
        resolved_context_id = _generate_context_id(
            raw,
            resolved_module,
            resolved_workflow_id,
        )

    return (
        resolved_context_id,
        resolved_module,
        resolved_workflow_id,
        _normalize_status(status or mapped_status, result_source),
        _as_result_object(result_source),
        _as_result_object(metadata_source),
    )


def _first_string(result: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_items(result: Mapping[str, Any], keys: Sequence[str]) -> list[Any]:
    for key in keys:
        value = result.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, Mapping):
            return [dict(value)]
    return []


def _adapt_module_result(
    module: str,
    result: dict[str, Any],
) -> tuple[dict[str, Any], ResultModuleFamily, str]:
    family = _module_family(module)
    if family == "K":
        adapted = {
            "summary": _first_string(
                result,
                ("summary", "answer", "insight", "title"),
            ),
            "items": _first_items(
                result,
                ("recommendations", "insights", "items", "sources"),
            ),
            "data": result,
        }
        return adapted, family, "k_series_summary_items_data"
    if family == "P":
        adapted = {
            "summary": _first_string(
                result,
                ("summary", "title", "name", "description"),
            ),
            "items": _first_items(
                result,
                ("products", "product", "items", "draft", "listing"),
            ),
            "data": result,
        }
        return adapted, family, "p_series_summary_items_data"
    if family == "SEO":
        adapted = {
            "summary": _first_string(
                result,
                ("summary", "title", "meta_description", "description"),
            ),
            "items": _first_items(
                result,
                ("keywords", "recommendations", "issues", "items"),
            ),
            "data": result,
        }
        return adapted, family, "seo_summary_items_data"
    return result, family, "generic_sanitized_passthrough"


def _split_wrapper(
    raw_output: Any,
    *,
    context_id: str | None,
    module: str | None,
    workflow_id: str | None,
    status: str | None,
    schema_mappings: Sequence[ResultSchemaMappingRule | Mapping[str, Any]] | None,
) -> tuple[
    Any,
    str | None,
    str | None,
    str | None,
    str | None,
    Sequence[ResultSchemaMappingRule | Mapping[str, Any]] | None,
    ResultSourceFormat,
    bool,
]:
    parsed, detected_format = _parse_flexible_json(raw_output)
    if not isinstance(parsed, Mapping):
        return (
            parsed,
            context_id,
            module,
            workflow_id,
            status,
            schema_mappings,
            detected_format,
            False,
        )

    output_key = next((key for key in WRAPPER_OUTPUT_KEYS if key in parsed), None)
    if output_key is None and "schema_mappings" in parsed and "output" in parsed:
        output_key = "output"
    if output_key is None:
        return (
            parsed,
            context_id,
            module,
            workflow_id,
            status,
            schema_mappings,
            detected_format,
            False,
        )

    return (
        parsed[output_key],
        context_id or _string_value(_first_present(parsed, COMMON_CONTEXT_KEYS)),
        module or _string_value(_first_present(parsed, COMMON_MODULE_KEYS)),
        workflow_id or _string_value(_first_present(parsed, COMMON_WORKFLOW_KEYS)),
        status or _string_value(_first_present(parsed, COMMON_STATUS_KEYS)),
        schema_mappings or parsed.get("schema_mappings"),
        detected_format,
        True,
    )


def normalize_workflow_result(
    raw_output: Any,
    *,
    context_id: str | None = None,
    module: str | None = None,
    workflow_id: str | None = None,
    status: str | None = None,
    schema_mappings: Sequence[ResultSchemaMappingRule | Mapping[str, Any]]
    | None = None,
) -> NormalizedWorkflowResult:
    (
        unwrapped_request,
        context_id,
        module,
        workflow_id,
        status,
        schema_mappings,
        original_format,
        wrapper_used,
    ) = _split_wrapper(
        raw_output,
        context_id=context_id,
        module=module,
        workflow_id=workflow_id,
        status=status,
        schema_mappings=schema_mappings,
    )
    raw, detected_format = _parse_flexible_json(unwrapped_request)
    if not wrapper_used and original_format == "json_string":
        detected_format = "json_string"
    mappings = _coerce_schema_mappings(schema_mappings)

    if isinstance(raw, Mapping):
        context_id = context_id or _string_value(_first_present(raw, COMMON_CONTEXT_KEYS))
        module = module or _string_value(_first_present(raw, COMMON_MODULE_KEYS))
        workflow_id = workflow_id or _string_value(_first_present(raw, COMMON_WORKFLOW_KEYS))
        status = status or _string_value(_first_present(raw, COMMON_STATUS_KEYS))

    source_schema: ResultSourceSchema = "standard_json"
    source_format: ResultSourceFormat = detected_format
    schema_mapping_id: str | None = None
    fallback_used = False
    common_metadata: dict[str, Any] = {}

    mapping = _select_schema_mapping(
        raw=raw,
        workflow_id=workflow_id,
        module=module,
        schema_mappings=mappings,
    )
    if mapping is not None:
        try:
            (
                resolved_context_id,
                resolved_module,
                resolved_workflow_id,
                resolved_status,
                result,
                common_metadata,
            ) = _build_from_mapping(
                raw=raw,
                mapping=mapping,
                context_id=context_id,
                module=module,
                workflow_id=workflow_id,
                status=status,
            )
            source_schema = "workflow_specific"
            schema_mapping_id = mapping.mapping_id
            source_format = "json_object"
        except (TypeError, ValueError, ValidationError):
            fallback_used = True
            result, source_format = _extract_common_result(raw)
            common_metadata = _extract_common_metadata(raw)
            resolved_module = module or "generic.unknown"
            resolved_workflow_id = workflow_id or "unknown.workflow"
            resolved_context_id = context_id or _generate_context_id(
                raw,
                resolved_module,
                resolved_workflow_id,
            )
            resolved_status = _normalize_status(status, result)
            source_schema = "fallback"
    else:
        result, source_format = _extract_common_result(raw)
        common_metadata = _extract_common_metadata(raw)
        resolved_module = module or "generic.unknown"
        resolved_workflow_id = workflow_id or "unknown.workflow"
        resolved_context_id = context_id or _generate_context_id(
            raw,
            resolved_module,
            resolved_workflow_id,
        )
        resolved_status = _normalize_status(status, result)
        fallback_used = source_format == "fallback"
        if fallback_used:
            source_schema = "fallback"

    adapted_result, family, adapter_rule = _adapt_module_result(
        resolved_module,
        result,
    )
    extracted_fields = tuple(
        field
        for field, present in (
            ("context_id", bool(resolved_context_id)),
            ("module", bool(resolved_module)),
            ("workflow_id", bool(resolved_workflow_id)),
            ("status", True),
            ("result", True),
            ("metadata", bool(common_metadata)),
        )
        if present
    )
    metadata = ResultNormalizationMetadata(
        normalized_at=_utc_now_timestamp(),
        module_family=family,
        adapter_rule=adapter_rule,
        schema_mapping_id=schema_mapping_id,
        source_schema=source_schema,
        source_format=source_format,
        fallback_used=fallback_used,
        extracted_fields=extracted_fields,
        source_metadata=common_metadata,
    )
    return NormalizedWorkflowResult(
        context_id=resolved_context_id,
        module=resolved_module,
        workflow_id=resolved_workflow_id,
        status=resolved_status,
        result=adapted_result,
        metadata=metadata,
    )


def get_result_normalization_engine_design() -> ResultNormalizationEngineDesign:
    return ResultNormalizationEngineDesign()


def get_result_schema_mapping_model() -> ResultSchemaMappingModel:
    return ResultSchemaMappingModel()


def get_result_module_adapter_rules() -> ResultModuleAdapterRules:
    return ResultModuleAdapterRules()


def get_result_ui_output_structure() -> ResultUIOutputStructure:
    return ResultUIOutputStructure()


def get_result_normalization_completion_status() -> ResultNormalizationCompletionStatus:
    return ResultNormalizationCompletionStatus(
        proceed_reason=(
            "C15E defines a pure result normalization engine, workflow-specific "
            "schema mappings, K/P/SEO module adapters, and a frontend-ready "
            "standard output contract without runtime execution or external API calls."
        )
    )
