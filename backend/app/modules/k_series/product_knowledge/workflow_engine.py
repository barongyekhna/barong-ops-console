from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....db.session import SessionLocal
from ....models.organization import OrganizationRecord
from ....models.user import User
from ....services.ai_provider_router import AIExecutionRouter, AIProviderExecutionError
from ....services.module_execution_gate import (
    ModuleExecutionContext,
    ModuleExecutionGateError,
    ModuleExecutionKey,
    require_module_execution_ready,
)
from .constants import MODULE_KEY, TARGET_ORGANIZATION_NAME
from .prompt_skills import (
    copy_skill_context_for_channel,
    image_art_direction_instruction,
    image_art_direction_skill_context,
    marketing_copy_instruction,
    plain_chinese_instruction,
)
from .category_resolver import category_is_bound
from .errors import KProductNotFoundError
from .models import (
    KProductKnowledgeAIEvent,
    KProductKnowledgeKeyword,
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeResearchRun,
    KProductKnowledgeRiskTerm,
    KProductKnowledgeVariant,
    KProductKnowledgeWorkflowExecution,
)
from .schemas import (
    ProductKnowledgeImageBindRequest,
    ProductKnowledgeRiskReviewRequest,
    ProductKnowledgeWorkflowExportRequest,
    ProductKnowledgeWorkflowReport,
    ProductKnowledgeWorkflowStartRequest,
)
from .prompt_skills import (
    chatgpt_keyword_filter_instruction,
    claude_keyword_review_instruction,
    keyword_research_skill_context,
)
from .scope_shim import KScopeContext, apply_scope_filters

logger = logging.getLogger(__name__)

IMAGE_SOURCE_MANUAL = "manual_upload_image"
IMAGE_SOURCE_I_SYSTEM = "i_system_asset"
BOUND_IMAGE_SOURCES = {IMAGE_SOURCE_MANUAL, IMAGE_SOURCE_I_SYSTEM}
K_WORKFLOW_PROVIDER_STEP_MAX_ATTEMPTS = 2

WORKFLOW_STEPS = (
    "product_ingestion",
    "serp_keyword_fetch",
    "ai_filter_chatgpt",
    "ai_filter_claude_opus",
    "risk_term_manual_review",
    "keyword_optimization_ai",
    "unit_conversion_normalization",
    "image_handling",
    "export_p_gmc_seo",
)

DUAL_AI_KEY_REQUIREMENTS = {
    "serp_keyword_fetch": "serp",
    "ai_filter_chatgpt": "chatgpt",
    "ai_filter_claude_opus": "claude_opus",
}

CLOSED_LOOP_WORKFLOW_STEPS_V2 = (
    "product_ingestion",
    "deepseek_enrichment",
    "serp_keyword_fetch",
    "ai_filter_chatgpt",
    "ai_filter_claude_opus",
    "risk_term_manual_review",
    "keyword_optimization_ai",
    "selling_points_generation",
    "unit_conversion_normalization",
    "image_binding",
    "export_p_series",
    "export_gmc",
    "export_seo",
)

CLOSED_LOOP_AI_KEY_REQUIREMENTS = {
    "deepseek_enrichment": "deepseek",
    "serp_keyword_fetch": "serp",
    "ai_filter_chatgpt": "chatgpt",
    "ai_filter_claude_opus": "claude_opus",
}

DEEPSEEK_ENRICHMENT_FIELDS = (
    "product_name_en",
    "brand_name",
    "manufacturer",
    "product_type",
    "short_description_en",
    "long_description_en",
    "primary_use_case_en",
    "target_customer_en",
    "category_hint",
    "google_product_category",
    "merchant_product_type",
)

IMPERIAL_TARGET_MARKETS = {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}
UNIT_CONVERSIONS = {
    "cm": ("inch", Decimal("0.3937007874")),
    "kg": ("lb", Decimal("2.2046226218")),
    "g": ("oz", Decimal("0.03527396195")),
}


class KWorkflowStateMachineV2:
    STATES = (
        "PRODUCT_CREATED",
        "AI_DEEPSEEK_ENRICHED",
        "SERP_ANALYZED",
        "CHATGPT_FILTERED",
        "CLAUDE_FILTERED",
        "RISK_PENDING_REVIEW",
        "RISK_APPROVED",
        "KEYWORD_OPTIMIZED",
        "SELLING_POINTS_GENERATED",
        "UNIT_NORMALIZED",
        "IMAGE_BOUND",
        "EXPORT_READY",
        "EXPORTED",
    )
    STATE_INDEX = {state: index for index, state in enumerate(STATES)}
    STEP_TO_STATE = {
        "product_ingestion": "PRODUCT_CREATED",
        "deepseek_enrichment": "AI_DEEPSEEK_ENRICHED",
        "serp_keyword_fetch": "SERP_ANALYZED",
        "ai_filter_chatgpt": "CHATGPT_FILTERED",
        "ai_filter_claude_opus": "CLAUDE_FILTERED",
        "risk_term_manual_review": "RISK_PENDING_REVIEW",
        "risk_term_review_manual": "RISK_PENDING_REVIEW",
        "keyword_optimization_ai": "KEYWORD_OPTIMIZED",
        "selling_points_generation": "SELLING_POINTS_GENERATED",
        "unit_conversion_normalization": "UNIT_NORMALIZED",
        "image_binding": "IMAGE_BOUND",
        "image_handling": "IMAGE_BOUND",
        "export_p_series": "EXPORT_READY",
        "export_gmc": "EXPORT_READY",
        "export_seo": "EXPORTED",
        "export_p_gmc_seo": "EXPORTED",
    }

    @classmethod
    def assert_state(cls, state: str) -> None:
        if state not in cls.STATE_INDEX:
            raise KWorkflowExecutionError(
                "K_WORKFLOW_STATE_UNKNOWN",
                f"K workflow state '{state}' is not registered.",
                status_code=500,
            )

    @classmethod
    def can_transition(cls, current: str | None, target: str) -> bool:
        cls.assert_state(target)
        if current is None:
            return target == cls.STATES[0]
        cls.assert_state(current)
        return cls.STATE_INDEX[target] >= cls.STATE_INDEX[current]

    @classmethod
    def current_state(
        cls,
        execution: KProductKnowledgeWorkflowExecution,
        product: KProductKnowledgeProduct | None = None,
    ) -> str:
        for entry in reversed(execution.execution_gate_logs_json or []):
            if entry.get("gate") == "workflow_state_machine_v2":
                state = str(entry.get("details", {}).get("state") or "").strip()
                if state in cls.STATE_INDEX:
                    return state
        if execution.status == "exported" or execution.export_payloads_json:
            return "EXPORTED"
        if execution.status == "ready_for_export":
            return "EXPORT_READY"
        if execution.image_binding_json and execution.image_binding_json.get("status") == "bound":
            return "IMAGE_BOUND"
        if execution.unit_conversion_json:
            return "UNIT_NORMALIZED"
        if execution.final_keyword_set_json:
            return "KEYWORD_OPTIMIZED"
        if (execution.risk_approval_log_json or {}).get("approved") is True:
            return "RISK_APPROVED"
        if execution.current_step in {"risk_term_review_manual", "risk_term_manual_review"}:
            return "RISK_PENDING_REVIEW"
        if execution.claude_filter_result_json:
            return "CLAUDE_FILTERED"
        if execution.chatgpt_filter_result_json:
            return "CHATGPT_FILTERED"
        if _trace_has_step(execution, "serp_keyword_fetch"):
            return "SERP_ANALYZED"
        if (product is not None and product.deepseek_structured_output_json) or _trace_has_step(
            execution,
            "deepseek_enrichment",
        ):
            return "AI_DEEPSEEK_ENRICHED"
        return "PRODUCT_CREATED"


class KWorkflowExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        error_report: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        reason = _workflow_error_reason(code)
        self.error_report = error_report or {
            "status": "failed",
            "reason": reason,
            "code": code,
            "message": message,
            "must_stop": True,
            "timestamp": _now_iso(),
        }
        super().__init__(message)


class KWorkflowProviderError(KWorkflowExecutionError):
    pass


def _workflow_error_reason(code: str | None) -> str:
    if code in {"API_KEY_BINDING_MISSING", "API_KEY_INJECTION_FAILED"}:
        return "missing_key"
    if code in {"ORG_CONTEXT_REQUIRED", "PRODUCT_CONTEXT_INCOMPLETE"}:
        return "missing_context"
    if code in {"MODULE_DISABLED", "MODULE_NOT_REGISTERED"}:
        return "module_unavailable"
    if code and code.startswith("SERP_"):
        return "provider_error"
    return "execution_error"


ProviderClient = Callable[[ModuleExecutionKey, dict[str, Any]], dict[str, Any]]
GateResolver = Callable[..., ModuleExecutionContext]


class KProductKnowledgeWorkflowEngine:
    def __init__(
        self,
        db: Session,
        *,
        provider_client: ProviderClient | None = None,
        gate_resolver: GateResolver | None = None,
    ) -> None:
        self.db = db
        self.provider_client = provider_client
        self.gate_resolver = gate_resolver or require_module_execution_ready

    def start_pipeline(
        self,
        *,
        product_id: UUID,
        payload: ProductKnowledgeWorkflowStartRequest,
        scope_context: KScopeContext,
        request: Request,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        product = self._require_product(product_id, scope_context)
        execution = self._create_execution(
            product=product,
            payload=payload,
            scope_context=scope_context,
            user=user,
        )
        try:
            self._validate_organization(product, scope_context, execution)
            self._append_trace(
                execution,
                "product_ingestion",
                "completed",
                output_summary={
                    "product_id": str(product.id),
                    "product_key": product.product_key,
                    "organization": product.organization_name,
                },
            )
            gate_context = self._require_execution_gate(
                execution=execution,
                request=request,
                user=user,
                key_requirements=DUAL_AI_KEY_REQUIREMENTS,
            )
            serp_result = self._fetch_serp_keywords(
                product=product,
                execution=execution,
                payload=payload,
                gate_context=gate_context,
                user=user,
            )
            chatgpt_result = self._run_chatgpt_filter(
                product=product,
                execution=execution,
                serp_result=serp_result,
                gate_context=gate_context,
                user=user,
            )
            claude_result = self._run_claude_filter(
                product=product,
                execution=execution,
                chatgpt_result=chatgpt_result,
                gate_context=gate_context,
                user=user,
            )
            self._create_manual_risk_review_block(
                product=product,
                execution=execution,
                claude_result=claude_result,
            )
            return execution
        except KWorkflowExecutionError as exc:
            if execution.error_report_json is None:
                self._fail_execution(
                    execution,
                    code=exc.code,
                    message=str(exc),
                    step=execution.current_step,
                    status_code=exc.status_code,
                    raw_error=exc,
                )
            raise
        except Exception as exc:
            self._fail_execution(
                execution,
                code="K_WORKFLOW_UNEXPECTED_FAILURE",
                message="K workflow execution failed unexpectedly.",
                step=execution.current_step,
                status_code=500,
                raw_error=exc,
            )
            raise

    def review_risk_terms(
        self,
        *,
        product_id: UUID,
        payload: ProductKnowledgeRiskReviewRequest,
        scope_context: KScopeContext,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        product = self._require_product(product_id, scope_context)
        execution = self._require_execution(product, payload.execution_id)
        risk_review_already_approved = (
            (execution.risk_approval_log_json or {}).get("approved") is True
        )
        if (
            execution.current_step
            not in {"risk_term_manual_review", "risk_term_review_manual"}
            and not risk_review_already_approved
        ):
            error_report = self._error_report(
                execution,
                code="RISK_REVIEW_NOT_CURRENT_STEP",
                message="Risk review can only be submitted at the manual review step.",
                step=execution.current_step,
            )
            execution.error_report_json = error_report
            self.db.add(execution)
            self.db.commit()
            raise KWorkflowExecutionError(
                "RISK_REVIEW_NOT_CURRENT_STEP",
                "Risk review can only be submitted at the manual review step.",
                error_report=error_report,
            )

        expected_terms = [
            item["term"]
            for item in _normalize_risk_keywords(
                (execution.claude_filter_result_json or {}).get("risk_keywords")
            )
        ]
        normalized_expected = {_normalize_key(term): term for term in expected_terms}
        decision_lookup = {
            _normalize_key(decision.term): decision for decision in payload.decisions
        }
        if normalized_expected:
            missing = [
                term
                for key, term in normalized_expected.items()
                if key not in decision_lookup
            ]
            if missing:
                error_report = self._error_report(
                    execution,
                    code="RISK_REVIEW_INCOMPLETE",
                    message="Every risk keyword must be manually approved or rejected.",
                    step="risk_term_manual_review",
                    details={"missing_terms": missing},
                )
                execution.error_report_json = error_report
                self.db.add(execution)
                self.db.commit()
                raise KWorkflowExecutionError(
                    "RISK_REVIEW_INCOMPLETE",
                    "Every risk keyword must be manually approved or rejected.",
                    error_report=error_report,
                )
        elif not payload.confirm_no_risk_terms:
            error_report = self._error_report(
                execution,
                code="RISK_REVIEW_CONFIRMATION_REQUIRED",
                message=(
                    "Manual confirmation is required even when Claude "
                    "returns no risk keywords."
                ),
                step="risk_term_manual_review",
            )
            execution.error_report_json = error_report
            self.db.add(execution)
            self.db.commit()
            raise KWorkflowExecutionError(
                "RISK_REVIEW_CONFIRMATION_REQUIRED",
                "Manual confirmation is required even when Claude returns no risk keywords.",
                error_report=error_report,
            )

        reviewed_at = _now_iso()
        decisions = []
        rejected_terms: list[str] = []
        for key, term in normalized_expected.items():
            decision = decision_lookup[key]
            if decision.decision == "reject":
                rejected_terms.append(term)
            self._persist_risk_decision(product, decision, user)
            decisions.append(
                {
                    "term": term,
                    "decision": decision.decision,
                    "reason": decision.reason,
                    "risk_term_id": str(decision.risk_term_id)
                    if decision.risk_term_id
                    else None,
                }
            )

        if rejected_terms:
            self._remove_rejected_terms_from_keyword_flow(
                product=product,
                execution=execution,
                rejected_terms=rejected_terms,
            )
        execution.risk_approval_log_json = {
            "approved": True,
            "reviewed_at": reviewed_at,
            "reviewed_by_user_id": str(user.id),
            "decisions": decisions,
            "rejected_terms": rejected_terms,
            "removed_terms": rejected_terms,
            "confirm_no_risk_terms": payload.confirm_no_risk_terms,
        }

        self._append_trace(
            execution,
            "risk_term_manual_review",
            "completed",
            output_summary=execution.risk_approval_log_json,
        )
        execution.error_report_json = None
        return self._continue_after_risk_review(product, execution, user)

    def bind_image_asset(
        self,
        *,
        product_id: UUID,
        payload: ProductKnowledgeImageBindRequest,
        scope_context: KScopeContext,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        product = self._require_product(product_id, scope_context)
        asset = self._resolve_image_asset(product, payload, user)
        if asset is None:
            raise KWorkflowExecutionError(
                "IMAGE_ASSET_NOT_FOUND",
                "Image asset was not found for this product.",
                status_code=404,
            )
        execution = self._latest_execution(product)
        if execution is None:
            raise KWorkflowExecutionError(
                "WORKFLOW_EXECUTION_NOT_FOUND",
                "Image binding requires an existing K workflow execution.",
                status_code=404,
            )
        self._bind_image(product, execution, asset)
        if self._risk_review_is_approved(execution) and execution.final_keyword_set_json:
            execution.status = "ready_for_export"
            execution.current_step = "export_p_gmc_seo"
            execution.error_report_json = None
        execution.updated_by_user_id = _user_uuid(user)
        self.db.add_all([product, execution])
        self.db.flush()
        return execution

    def export_payloads(
        self,
        *,
        product_id: UUID,
        payload: ProductKnowledgeWorkflowExportRequest,
        scope_context: KScopeContext,
        user: User,
    ) -> tuple[KProductKnowledgeWorkflowExecution, ProductKnowledgeWorkflowReport]:
        product = self._require_product(product_id, scope_context)
        execution = self._require_execution(product, payload.execution_id)
        blockers = self._export_blockers(product, execution)
        if blockers:
            execution.status = "blocked"
            execution.current_step = "export_p_gmc_seo"
            execution.error_report_json = self._error_report(
                execution,
                code="EXPORT_GATE_BLOCKED",
                message="K export is blocked until the complete workflow is satisfied.",
                step="export_p_gmc_seo",
                details={"blockers": blockers},
            )
            self._append_trace(
                execution,
                "export_p_gmc_seo",
                "blocked",
                error=execution.error_report_json,
            )
            self.db.add(execution)
            self.db.commit()
            raise KWorkflowExecutionError(
                "EXPORT_GATE_BLOCKED",
                "K export is blocked until the complete workflow is satisfied.",
                error_report=execution.error_report_json,
            )

        export_payloads = self._build_export_payloads(product, execution)
        execution.export_payloads_json = export_payloads
        execution.status = "exported"
        execution.current_step = "export_p_gmc_seo"
        execution.finished_at = _now()
        execution.updated_by_user_id = _user_uuid(user)
        execution.error_report_json = None
        self._append_trace(
            execution,
            "export_p_gmc_seo",
            "completed",
            output_summary={
                "payloads": ["p_series_payload", "gmc_feed", "seo_keyword_pack"],
            },
        )
        self.db.add(execution)
        self.db.flush()
        return execution, self.build_report(execution)

    def build_report(
        self,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> ProductKnowledgeWorkflowReport:
        return ProductKnowledgeWorkflowReport(
            workflow_id=execution.id,
            product_id=execution.product_id,
            organization=execution.organization_name,
            status=execution.status,
            current_step=execution.current_step,
            full_pipeline_trace=execution.trace_json or [],
            chatgpt_filter_result=execution.chatgpt_filter_result_json,
            claude_filter_result=execution.claude_filter_result_json,
            risk_approval_log=execution.risk_approval_log_json,
            final_keyword_set=execution.final_keyword_set_json,
            export_payloads=execution.export_payloads_json,
            execution_gate_logs=execution.execution_gate_logs_json or [],
            error_report=execution.error_report_json,
        )

    def latest_execution_for_product(
        self,
        *,
        product_id: UUID,
        scope_context: KScopeContext,
    ) -> KProductKnowledgeWorkflowExecution | None:
        product = self._require_product(product_id, scope_context)
        return self._latest_execution(product)

    def _create_execution(
        self,
        *,
        product: KProductKnowledgeProduct,
        payload: ProductKnowledgeWorkflowStartRequest,
        scope_context: KScopeContext,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        execution = KProductKnowledgeWorkflowExecution(
            id=uuid4(),
            product_id=product.id,
            organization_name=product.organization_name or TARGET_ORGANIZATION_NAME,
            workspace_key=scope_context.workspace_key,
            business_context=scope_context.business_context,
            scope_mode=scope_context.scope_mode,
            target_market=payload.target_market,
            target_region=payload.target_region,
            status="running",
            current_step="product_ingestion",
            trace_json=[],
            execution_gate_logs_json=[],
            started_at=_now(),
            created_by_user_id=_user_uuid(user),
            updated_by_user_id=_user_uuid(user),
        )
        self.db.add(execution)
        self.db.flush()
        return execution

    def _validate_organization(
        self,
        product: KProductKnowledgeProduct,
        scope_context: KScopeContext,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> None:
        if not product.organization_name:
            product.organization_name = TARGET_ORGANIZATION_NAME
        if product.organization_name != TARGET_ORGANIZATION_NAME:
            self._fail_execution(
                execution,
                code="ORGANIZATION_MISMATCH",
                message="K workflow organization does not match the required owner.",
                step="product_ingestion",
                status_code=403,
                details={
                    "required": TARGET_ORGANIZATION_NAME,
                    "actual": product.organization_name,
                },
            )
        organization = self.db.get(OrganizationRecord, scope_context.workspace_key)
        if organization is not None and organization.org_name != TARGET_ORGANIZATION_NAME:
            self._fail_execution(
                execution,
                code="ORGANIZATION_MISMATCH",
                message="Execution organization context does not match the required owner.",
                step="product_ingestion",
                status_code=403,
                details={
                    "required": TARGET_ORGANIZATION_NAME,
                    "actual": organization.org_name,
                    "org_id": organization.org_id,
                },
            )
        self._append_gate_log(
            execution,
            "organization_validation",
            "allowed",
            {
                "organization": TARGET_ORGANIZATION_NAME,
                "workspace_key": scope_context.workspace_key,
            },
        )

    def _require_execution_gate(
        self,
        *,
        execution: KProductKnowledgeWorkflowExecution,
        request: Request,
        user: User,
        key_requirements: Mapping[str, str],
    ) -> ModuleExecutionContext:
        try:
            context = self.gate_resolver(
                self.db,
                module_id=MODULE_KEY,
                user=user,
                request=request,
                key_requirements=key_requirements,
            )
        except ModuleExecutionGateError as exc:
            self._fail_execution(
                execution,
                code=exc.code,
                message=str(exc),
                step=execution.current_step,
                status_code=exc.status_code,
                details={"module_id": exc.module_id, "org_id": exc.org_id},
            )
        self._append_gate_log(
            execution,
            "module_execution_gate",
            "allowed",
            {
                "module_id": context.control_module_id,
                "org_id": context.org_id,
                "resolved_keys": context.redacted_key_map(),
                "required_order": list(key_requirements),
            },
        )
        return context

    def _execute_provider(
        self,
        *,
        provider: str,
        task_type: str,
        key: ModuleExecutionKey,
        gate_context: ModuleExecutionContext,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self.provider_client is not None:
            return self.provider_client(key, payload)
        step = str(payload.get("task") or provider)
        provider_db = SessionLocal()
        provider_error: Exception | None = None
        try:
            return AIExecutionRouter(provider_db).execute(
                provider=provider,
                task_type=task_type,  # type: ignore[arg-type]
                payload=payload,
                org=TARGET_ORGANIZATION_NAME,
                module_id=MODULE_KEY,
                execution_context=gate_context,
            )
        except AIProviderExecutionError as exc:
            provider_error = exc
            provider_report = {
                "status": "failed",
                "reason": "provider_error",
                **exc.structured_error(),
                "must_stop": True,
                "timestamp": _now_iso(),
            }
            raise KWorkflowProviderError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                error_report=provider_report,
            ) from exc
        except Exception as exc:
            provider_error = exc
            raise KWorkflowProviderError(
                "PROVIDER_EXECUTION_FAILED",
                "Provider execution failed.",
                status_code=502,
                error_report={
                    "status": "failed",
                    "reason": "provider_error",
                    "code": "PROVIDER_EXECUTION_FAILED",
                    "message": "Provider execution failed.",
                    "provider": provider,
                    "org_id": gate_context.org_id,
                    "must_stop": True,
                    "timestamp": _now_iso(),
                },
            ) from exc
        finally:
            self._dispose_provider_session(
                provider_db,
                step=step,
                reason="provider_call_finished",
                raw_error=provider_error,
            )

    def _run_deepseek_enrichment(
        self,
        *,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        gate_context: ModuleExecutionContext,
        user: User,
    ) -> dict[str, Any]:
        self._append_trace(
            execution,
            "deepseek_enrichment",
            "running",
            input_summary={
                "product_id": str(product.id),
                "product_key": product.product_key,
            },
        )
        self._commit_workflow_progress(
            product=product,
            execution=execution,
            step="deepseek_enrichment",
            reason="provider_call_started",
        )
        key = gate_context.key_for_step("deepseek_enrichment")
        ai_input = {
            "module_id": MODULE_KEY,
            "task": "deepseek_enrichment",
            "product": _product_snapshot(product),
            "raw_input_text": product.raw_input_text,
            "raw_input_language": product.raw_input_language,
            "required_output": list(DEEPSEEK_ENRICHMENT_FIELDS),
        }
        provider_output = self._execute_provider(
            provider="deepseek",
            task_type="generate",
            key=key,
            gate_context=gate_context,
            payload=ai_input,
        )
        diff: dict[str, dict[str, Any]] = {}
        for field in DEEPSEEK_ENRICHMENT_FIELDS:
            value = provider_output.get(field)
            if isinstance(value, str):
                value = value.strip()
            if value in (None, ""):
                continue
            before = getattr(product, field, None)
            if before == value:
                continue
            diff[field] = {"before": before, "after": value}
            setattr(product, field, value)

        product.deepseek_structured_output_json = provider_output
        product.review_status = "ai_structured"
        product.ai_confidence_scores_json = {
            **(product.ai_confidence_scores_json or {}),
            "deepseek_enrichment": provider_output.get("confidence_score"),
        }
        product.field_diff_json = {
            **(product.field_diff_json or {}),
            "deepseek_enrichment": diff,
        }
        self._add_ai_event(
            product=product,
            execution=execution,
            event_type="deepseek_enrichment",
            provider_key=key,
            ai_input=ai_input,
            result=provider_output,
            user=user,
        )
        self._append_trace(
            execution,
            "deepseek_enrichment",
            "completed",
            output_summary={
                "updated_fields": sorted(diff),
                "provider": key.name,
            },
        )
        return provider_output

    def _fetch_serp_keywords(
        self,
        *,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        payload: ProductKnowledgeWorkflowStartRequest,
        gate_context: ModuleExecutionContext,
        user: User,
    ) -> dict[str, Any]:
        self._append_trace(
            execution,
            "serp_keyword_fetch",
            "running",
            input_summary={
                "target_market": payload.target_market,
                "main_keyword": payload.main_keyword or product.primary_keyword,
                "seed_keywords": payload.seed_keywords,
            },
        )
        self._commit_workflow_progress(
            product=product,
            execution=execution,
            step="serp_keyword_fetch",
            reason="provider_call_started",
        )
        key = gate_context.key_for_step("serp_keyword_fetch")
        explicit_query = (payload.main_keyword or product.primary_keyword or "").strip()
        query = (
            explicit_query
            or product.product_name_en
            or product.sku
            or product.parent_sku
            or product.product_key
            or ""
        ).strip()
        if not query:
            self._fail_execution(
                execution,
                code="MAIN_KEYWORD_REQUIRED",
                message="SERP keyword fetch requires product main_keyword.",
                step="serp_keyword_fetch",
                status_code=400,
                details={"product_id": str(product.id), "product_key": product.product_key},
            )
        if payload.main_keyword and product.primary_keyword != query:
            product.primary_keyword = query
        product_context = {
            "product_id": str(product.id),
            "product_key": product.product_key,
            "target_market": payload.target_market,
            "org_id": gate_context.org_id,
            "main_keyword": query,
        }
        missing_context = [
            field
            for field, value in product_context.items()
            if not str(value or "").strip()
        ]
        if missing_context:
            self._fail_execution(
                execution,
                code="PRODUCT_CONTEXT_INCOMPLETE",
                message="SERP execution requires product_id, product_key, target_market, main_keyword, and org_id.",
                step="serp_keyword_fetch",
                status_code=400,
                details={"missing": missing_context, "product_context": product_context},
            )
        provider_output = self._execute_provider(
            provider="serp",
            task_type="search",
            key=key,
            gate_context=gate_context,
            payload={
                "module_id": MODULE_KEY,
                "task": "serp_keyword_fetch",
                "product_context": product_context,
                "product_id": product_context["product_id"],
                "product_key": product_context["product_key"],
                "org_id": product_context["org_id"],
                "main_keyword": query,
                "query": query,
                "requested_query": payload.serp_query,
                "target_market": product_context["target_market"],
                "target_region": payload.target_region,
                "seed_keywords": payload.seed_keywords,
                "competitors": payload.competitors,
                "keyword_research_skill": keyword_research_skill_context(),
            },
        )
        keywords = _safe_string_list(
            provider_output.get("keywords")
            or provider_output.get("related_keywords")
            or provider_output.get("keyword_candidates")
        )
        organic_results = _organic_results(
            provider_output.get("organic_results")
            or provider_output.get("organic")
            or provider_output.get("results")
            or provider_output.get("items")
        )
        if not keywords:
            keywords = _keywords_from_organic_results(organic_results, query)
        if not keywords:
            self._fail_execution(
                execution,
                code="SERP_KEYWORDS_MISSING",
                message="SERP keyword fetch did not return usable keywords.",
                step="serp_keyword_fetch",
                status_code=502,
            )
        competitors = _safe_string_list(
            provider_output.get("competitor_links") or provider_output.get("competitors")
        )
        competitors = _dedupe_strings([*payload.competitors, *competitors])
        run = KProductKnowledgeResearchRun(
            id=uuid4(),
            product_id=product.id,
            run_type="serp_keyword_fetch",
            status="succeeded",
            requested_by_user_id=_user_uuid(user),
            target_market=payload.target_market,
            target_language=product.canonical_language,
            seed_keywords_json=payload.seed_keywords,
            serp_provider=key.name,
            serp_result_summary_json={
                "query": query,
                "keywords": keywords,
                "organic_results": organic_results,
                "competitors": competitors,
            },
            selected_keyword_ids_json=keywords,
            started_at=_now(),
            finished_at=_now(),
            created_by_user_id=_user_uuid(user),
            updated_by_user_id=_user_uuid(user),
        )
        self.db.add(run)
        self._upsert_keywords(
            product,
            keywords,
            keyword_type="secondary",
            source="SERP",
            status="candidate",
            market=payload.target_market,
        )
        result = {
            "query": query,
            "keywords": keywords,
            "organic_results": organic_results,
            "competitors": competitors,
            "research_run_id": str(run.id),
            "provider": key.name,
        }
        self._append_trace(
            execution,
            "serp_keyword_fetch",
            "completed",
            output_summary={
                "keyword_count": len(keywords),
                "competitor_count": len(competitors),
                "provider": key.name,
            },
        )
        return result

    def _run_chatgpt_filter(
        self,
        *,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        serp_result: dict[str, Any],
        gate_context: ModuleExecutionContext,
        user: User,
    ) -> dict[str, Any]:
        self._append_trace(
            execution,
            "ai_filter_chatgpt",
            "running",
            input_summary={"keyword_count": len(serp_result["keywords"])},
        )
        self._commit_workflow_progress(
            product=product,
            execution=execution,
            step="ai_filter_chatgpt",
            reason="provider_call_started",
        )
        key = gate_context.key_for_step("ai_filter_chatgpt")
        ai_input = {
            "module_id": MODULE_KEY,
            "task": "ai_filter_chatgpt",
            "product": _product_snapshot(product),
            "serp_keywords": serp_result["keywords"],
            "competitors": serp_result["competitors"],
            "keyword_research_skill": keyword_research_skill_context(),
            "required_output": [
                "cleaned_keywords",
                "filtered_keywords",
                "rejected_keywords",
                "rationale",
            ],
        }
        ai_input["messages"] = _strict_json_messages(
            instruction=chatgpt_keyword_filter_instruction(),
            payload=ai_input,
        )
        provider_output = self._execute_provider(
            provider="chatgpt",
            task_type="chat",
            key=key,
            gate_context=gate_context,
            payload=ai_input,
        )
        result = _normalize_chatgpt_result(provider_output)
        if not result["cleaned_keywords"]:
            self._fail_execution(
                execution,
                code="CHATGPT_FILTER_FAILED",
                message="ChatGPT filter completed without cleaned keywords.",
                step="ai_filter_chatgpt",
                status_code=502,
            )
        execution.chatgpt_filter_result_json = result
        self._add_ai_event(
            product=product,
            execution=execution,
            event_type="ai_filter_chatgpt",
            provider_key=key,
            ai_input=ai_input,
            result=result,
            user=user,
        )
        self._append_trace(
            execution,
            "ai_filter_chatgpt",
            "completed",
            output_summary={
                "cleaned_keywords": len(result["cleaned_keywords"]),
                "filtered_keywords": len(result["filtered_keywords"]),
                "rejected_keywords": len(result["rejected_keywords"]),
                "provider": key.name,
            },
        )
        return result

    def _run_claude_filter(
        self,
        *,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        chatgpt_result: dict[str, Any],
        gate_context: ModuleExecutionContext,
        user: User,
    ) -> dict[str, Any]:
        self._append_trace(
            execution,
            "ai_filter_claude_opus",
            "running",
            input_summary={
                "chatgpt_cleaned_keywords": len(chatgpt_result["cleaned_keywords"])
            },
        )
        self._commit_workflow_progress(
            product=product,
            execution=execution,
            step="ai_filter_claude_opus",
            reason="provider_call_started",
        )
        key = gate_context.key_for_step("ai_filter_claude_opus")
        ai_input = {
            "module_id": MODULE_KEY,
            "task": "ai_filter_claude_opus",
            "product": _product_snapshot(product),
            "chatgpt_filter_result": chatgpt_result,
            "keyword_research_skill": keyword_research_skill_context(),
            "max_tokens": 1024,
            "required_output": [
                "final_keywords",
                "high_value_keywords",
                "low_value_keywords",
                "risk_keywords",
            ],
        }
        ai_input["messages"] = _strict_json_messages(
            instruction=claude_keyword_review_instruction(),
            payload=ai_input,
        )
        provider_output = self._execute_provider(
            provider="claude",
            task_type="chat",
            key=key,
            gate_context=gate_context,
            payload=ai_input,
        )
        result = _normalize_claude_result(provider_output)
        if not result["final_keywords"]:
            self._fail_execution(
                execution,
                code="CLAUDE_FILTER_FAILED",
                message="Claude Opus filter completed without final keywords.",
                step="ai_filter_claude_opus",
                status_code=502,
            )
        execution.claude_filter_result_json = result
        product.risk_keywords_json = result["risk_keywords"]
        self._persist_risk_keywords(product, result["risk_keywords"])
        self._add_ai_event(
            product=product,
            execution=execution,
            event_type="ai_filter_claude_opus",
            provider_key=key,
            ai_input=ai_input,
            result=result,
            user=user,
        )
        self._append_trace(
            execution,
            "ai_filter_claude_opus",
            "completed",
            output_summary={
                "final_keywords": len(result["final_keywords"]),
                "high_value_keywords": len(result["high_value_keywords"]),
                "low_value_keywords": len(result["low_value_keywords"]),
                "risk_keywords": len(result["risk_keywords"]),
                "provider": key.name,
            },
        )
        return result

    def _create_manual_risk_review_block(
        self,
        *,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        claude_result: dict[str, Any],
    ) -> None:
        execution.status = "blocked"
        execution.current_step = "risk_term_review_manual"
        execution.error_report_json = self._error_report(
            execution,
            code="RISK_REVIEW_REQUIRED",
            message="Manual risk keyword review is required before continuing.",
            step="risk_term_manual_review",
            details={
                "risk_keywords": claude_result["risk_keywords"],
                "auto_approval_allowed": False,
            },
        )
        self._append_trace(
            execution,
            "risk_term_manual_review",
            "blocked",
            output_summary={
                "manual_review_required": True,
                "risk_keyword_count": len(claude_result["risk_keywords"]),
            },
            error=execution.error_report_json,
        )
        execution.current_step = "risk_term_review_manual"
        self.db.add_all([product, execution])
        self.db.flush()

    def _continue_after_risk_review(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        user: User,
        ) -> KProductKnowledgeWorkflowExecution:
        self._optimize_keywords(product, execution, user)
        self._normalize_units(product, execution)
        if not self._image_is_bound(product, execution):
            execution.status = "blocked"
            execution.current_step = "image_handling"
            execution.error_report_json = self._error_report(
                execution,
                code="IMAGE_BINDING_REQUIRED",
                message="A manual upload or I-system image asset must be bound before export.",
                step="image_handling",
            )
            self._append_trace(
                execution,
                "image_handling",
                "blocked",
                error=execution.error_report_json,
            )
            self.db.add_all([product, execution])
            self.db.flush()
            return execution
        execution.status = "ready_for_export"
        execution.current_step = "export_p_gmc_seo"
        execution.error_report_json = None
        self.db.add_all([product, execution])
        self.db.flush()
        return execution

    def _optimize_keywords(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        user: User,
    ) -> None:
        self._append_trace(execution, "keyword_optimization_ai", "running")
        claude = execution.claude_filter_result_json or {}
        final_keywords = _dedupe_strings(_safe_string_list(claude.get("final_keywords")))
        high_value = _dedupe_strings(_safe_string_list(claude.get("high_value_keywords")))
        ordered = _dedupe_strings([*high_value, *final_keywords])
        primary = ordered[:1]
        secondary = [item for item in ordered[1:12] if len(item.split()) <= 4]
        longtail = _dedupe_strings(
            [
                item
                for item in [*ordered[1:], *_safe_string_list(claude.get("low_value_keywords"))]
                if len(item.split()) > 3
            ]
        )[:20]
        if not primary and ordered:
            primary = [ordered[0]]
        keyword_set = {
            "ranking": [
                {"keyword": keyword, "rank": index + 1}
                for index, keyword in enumerate(ordered)
            ],
            "clusters": _cluster_keywords(ordered),
            "intent_classification": {
                keyword: _classify_intent(keyword) for keyword in ordered
            },
            "primary_keywords": primary,
            "secondary_keywords": secondary,
            "longtail_keywords": longtail,
            "deduplication_removed": max(
                0,
                len(_safe_string_list(claude.get("final_keywords"))) - len(final_keywords),
            ),
            "source": "claude_opus_filtered_keywords",
        }
        execution.final_keyword_set_json = keyword_set
        product.secondary_keywords_json = secondary
        product.long_tail_keywords_json = longtail
        self._upsert_keywords(
            product,
            primary,
            keyword_type="primary",
            source="AI_KEYWORD_OPTIMIZATION",
            status="approved",
            market=execution.target_market,
        )
        self._upsert_keywords(
            product,
            secondary,
            keyword_type="secondary",
            source="AI_KEYWORD_OPTIMIZATION",
            status="approved",
            market=execution.target_market,
        )
        self._upsert_keywords(
            product,
            longtail,
            keyword_type="long_tail",
            source="AI_KEYWORD_OPTIMIZATION",
            status="approved",
            market=execution.target_market,
        )
        self.db.add(
            KProductKnowledgeAIEvent(
                id=uuid4(),
                product_id=product.id,
                research_run_id=None,
                event_type="keyword_optimization_ai",
                provider="workflow_engine:claude_output_optimizer",
                provider_model="deterministic_v1",
                prompt_version="k-workflow-v1",
                input_hash=_hash_json(claude),
                output_summary_json={
                    "primary": len(primary),
                    "secondary": len(secondary),
                    "longtail": len(longtail),
                },
                output_payload_json=keyword_set,
                status="succeeded",
                created_by_user_id=_user_uuid(user),
                updated_by_user_id=_user_uuid(user),
            )
        )
        self._append_trace(
            execution,
            "keyword_optimization_ai",
            "completed",
            output_summary={
                "primary": len(primary),
                "secondary": len(secondary),
                "longtail": len(longtail),
            },
        )

    def _normalize_units(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> None:
        self._append_trace(
            execution,
            "unit_conversion_normalization",
            "running",
            input_summary={"target_market": execution.target_market},
        )
        market = execution.target_market.strip().upper()
        fields = {
            "dimensions_json": product.dimensions_json,
            "package_dimensions_json": product.package_dimensions_json,
            "weight_json": product.weight_json,
            "package_weight_json": product.package_weight_json,
        }
        normalized = {
            field: _normalize_units_for_market(value, market)
            for field, value in fields.items()
            if value is not None
        }
        execution.unit_conversion_json = {
            "target_market": execution.target_market,
            "system": "imperial" if market in IMPERIAL_TARGET_MARKETS else "metric",
            "normalized_fields": normalized,
            "supported_conversions": ["cm->inch", "kg->lb", "g->oz"],
        }
        product.field_diff_json = {
            **(product.field_diff_json or {}),
            "unit_conversion_normalization": execution.unit_conversion_json,
        }
        self._append_trace(
            execution,
            "unit_conversion_normalization",
            "completed",
            output_summary={
                "converted_fields": sorted(normalized),
                "target_market": execution.target_market,
            },
        )

    def _bind_image(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        asset: KProductKnowledgeMediaAsset,
    ) -> None:
        product.selected_image_path = (
            asset.object_key or asset.file_url_placeholder or str(asset.id)
        )
        source_type = _image_source_type(asset)
        metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
        product.image_asset_status = "bound"
        product.media_notes_json = {
            **(product.media_notes_json or {}),
            "bound_asset_id": str(asset.id),
            "image_source_type": source_type,
            "i_system_image_asset_id": _i_system_asset_id(asset),
            "variant_sku": asset.variant_sku,
            "bound_at": _now_iso(),
            "k_image_ai_generation_allowed": False,
            "k_image_review_allowed": False,
            "object_key": asset.object_key,
            "original_url": (
                f"/k/media/{asset.id}/file"
                if asset.object_key
                else asset.file_url_placeholder
            ),
            "preview_url": (
                f"/k/media/{asset.id}/preview"
                if asset.object_key
                else asset.file_url_placeholder
            ),
            "thumbnail_url": (
                f"/k/media/{asset.id}/thumbnail"
                if asset.object_key
                else asset.file_url_placeholder
            ),
        }
        execution.image_binding_json = {
            "status": "bound",
            "source_type": source_type,
            "asset_id": str(asset.id),
            "i_system_image_asset_id": _i_system_asset_id(asset),
            "variant_sku": asset.variant_sku,
            "object_key": asset.object_key,
            "file_url_placeholder": asset.file_url_placeholder,
            "original_url": (
                f"/k/media/{asset.id}/file"
                if asset.object_key
                else asset.file_url_placeholder
            ),
            "preview_url": (
                f"/k/media/{asset.id}/preview"
                if asset.object_key
                else asset.file_url_placeholder
            ),
            "thumbnail_url": (
                f"/k/media/{asset.id}/thumbnail"
                if asset.object_key
                else asset.file_url_placeholder
            ),
            "content_sha256": metadata.get("content_sha256"),
            "file_size": asset.file_size,
            "mime_type": asset.mime_type,
            "width": asset.width,
            "height": asset.height,
            "bound_at": _now_iso(),
        }
        self._append_trace(
            execution,
            "image_handling",
            "completed",
            output_summary=execution.image_binding_json,
        )

    def _resolve_image_asset(
        self,
        product: KProductKnowledgeProduct,
        payload: ProductKnowledgeImageBindRequest,
        user: User,
    ) -> KProductKnowledgeMediaAsset | None:
        variant = self._resolve_variant_for_image(product, payload.variant_sku)
        if payload.source_type == IMAGE_SOURCE_MANUAL:
            asset_id = payload.asset_id or payload.manual_asset_id
            if asset_id is None:
                raise KWorkflowExecutionError(
                    "MANUAL_IMAGE_ASSET_REQUIRED",
                    "Manual image binding requires a manual asset id.",
                    status_code=422,
                )
            asset = self.db.get(KProductKnowledgeMediaAsset, asset_id)
            if asset is None or asset.product_id != product.id:
                return None
            if asset.variant_sku != variant.variant_sku:
                raise KWorkflowExecutionError(
                    "IMAGE_VARIANT_MISMATCH",
                    "Manual image asset must be stored under the requested variant_sku.",
                    status_code=409,
                )
            if _image_source_type(asset) != IMAGE_SOURCE_MANUAL:
                raise KWorkflowExecutionError(
                    "IMAGE_SOURCE_MISMATCH",
                    "Manual image binding can only bind manually uploaded K images.",
                    status_code=409,
                )
            return asset

        i_system_asset_id = (
            payload.i_system_image_asset_id
            or (str(payload.asset_id) if payload.asset_id is not None else None)
        )
        if not i_system_asset_id:
            raise KWorkflowExecutionError(
                "I_SYSTEM_IMAGE_ASSET_REQUIRED",
                "I-system image binding requires an I-system image_asset_id.",
                status_code=422,
            )
        asset = self._i_system_asset_reference(
            product,
            i_system_asset_id,
            variant.variant_sku,
        )
        if asset is not None:
            return asset
        asset = KProductKnowledgeMediaAsset(
            id=uuid4(),
            product_id=product.id,
            variant_id=variant.id,
            variant_sku=variant.variant_sku,
            asset_type="image",
            asset_role="main",
            status="available",
            review_status="i_system_managed",
            storage_provider="i_series",
            object_key=(
                f"images/{product.product_key}/{variant.variant_sku}/"
                f"i-series/{i_system_asset_id}"
            ),
            source=IMAGE_SOURCE_I_SYSTEM,
            metadata_json={
                "source_type": IMAGE_SOURCE_I_SYSTEM,
                "i_system_image_asset_id": i_system_asset_id,
                "product_key": product.product_key,
                "variant_folder": f"images/{product.product_key}/{variant.variant_sku}",
                "variant_sku": variant.variant_sku,
                "k_image_ai_generation_allowed": False,
                "k_image_review_allowed": False,
            },
            created_by_user_id=_user_uuid(user),
            updated_by_user_id=_user_uuid(user),
        )
        self.db.add(asset)
        self.db.flush()
        return asset

    def _build_export_payloads(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> dict[str, Any]:
        keyword_set = execution.final_keyword_set_json or {}
        image = execution.image_binding_json or self._product_image_binding_fallback(product)
        normalized_units = execution.unit_conversion_json or {}
        title = product.product_name_en or product.product_key
        description = product.short_description_en or product.long_description_en or ""
        return {
            "p_series_payload": {
                "organization": TARGET_ORGANIZATION_NAME,
                "product_id": str(product.id),
                "product_key": product.product_key,
                "sku": product.sku,
                "title": title,
                "brand": product.brand_name,
                "product_type": product.product_type,
                "primary_keywords": keyword_set.get("primary_keywords", []),
                "secondary_keywords": keyword_set.get("secondary_keywords", []),
                "longtail_keywords": keyword_set.get("longtail_keywords", []),
                "image": image,
                "normalized_units": normalized_units,
                "workflow_trace_id": str(execution.id),
            },
            "gmc_feed_structure": {
                "id": product.sku or product.product_key,
                "title": title,
                "description": description,
                "link": product.slug,
                "image_link": product.selected_image_path or product.main_image_url,
                "availability": product.stock_status or "in_stock",
                "price": _price(product.regular_price, product.price_currency),
                "sale_price": _price(product.sale_price, product.price_currency),
                "brand": product.brand_name,
                "gtin": product.gtin,
                "mpn": product.mpn,
                "google_product_category": product.google_product_category,
                "product_type": product.merchant_product_type or product.product_type,
            },
            "seo_keyword_pack": {
                "primary_keywords": keyword_set.get("primary_keywords", []),
                "secondary_keywords": keyword_set.get("secondary_keywords", []),
                "longtail_keywords": keyword_set.get("longtail_keywords", []),
                "clusters": keyword_set.get("clusters", {}),
                "intent_classification": keyword_set.get("intent_classification", {}),
                "seo_title": product.seo_title_en or title,
                "seo_description": product.seo_description_en or description,
            },
        }

    def _export_blockers(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> list[str]:
        blockers: list[str] = []
        if product.organization_name != TARGET_ORGANIZATION_NAME:
            blockers.append("organization mismatch")
        if not execution.chatgpt_filter_result_json:
            blockers.append("ChatGPT filter missing")
        if not execution.claude_filter_result_json:
            blockers.append("Claude Opus filter missing")
        if not self._risk_review_is_approved(execution):
            blockers.append("risk review not approved")
        if not execution.final_keyword_set_json:
            blockers.append("keywords not finalized")
        if not self._selling_points_generated(product):
            blockers.append("DeepSeek selling points not generated")
        if not self._image_is_bound(product, execution):
            blockers.append("manual or I-system image not bound")
        if execution.status not in {"ready_for_export", "exported"}:
            blockers.append(f"workflow status is {execution.status}")
        if not category_is_bound(product):
            channel = (product.channel or "dtc").strip().lower()
            blockers.append(f"category not bound for {channel} channel")
        return blockers

    def _risk_review_is_approved(
        self,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> bool:
        return bool((execution.risk_approval_log_json or {}).get("approved") is True)

    def _selling_points_generated(self, product: KProductKnowledgeProduct) -> bool:
        ai_warnings = product.ai_warnings_json or {}
        deepseek_output = product.deepseek_structured_output_json or {}
        return bool(
            ai_warnings.get("selling_points")
            or deepseek_output.get("selling_points_generation")
        )

    def _i_system_asset_reference(
        self,
        product: KProductKnowledgeProduct,
        i_system_asset_id: str,
        variant_sku: str,
    ) -> KProductKnowledgeMediaAsset | None:
        return self.db.scalar(
            select(KProductKnowledgeMediaAsset)
            .where(
                KProductKnowledgeMediaAsset.product_id == product.id,
                KProductKnowledgeMediaAsset.variant_sku == variant_sku,
                KProductKnowledgeMediaAsset.source == IMAGE_SOURCE_I_SYSTEM,
                KProductKnowledgeMediaAsset.object_key
                == (
                    f"images/{product.product_key}/{variant_sku}/"
                    f"i-series/{i_system_asset_id}"
                ),
            )
            .order_by(KProductKnowledgeMediaAsset.updated_at.desc())
            .limit(1)
        )

    def _resolve_variant_for_image(
        self,
        product: KProductKnowledgeProduct,
        variant_sku: str | None,
    ) -> KProductKnowledgeVariant:
        variants = list(
            self.db.scalars(
                select(KProductKnowledgeVariant)
                .where(KProductKnowledgeVariant.product_id == product.id)
                .order_by(KProductKnowledgeVariant.created_at.asc())
            )
        )
        if not variants:
            raise KWorkflowExecutionError(
                "VARIANT_REQUIRED",
                "Image binding requires an existing product variant.",
                status_code=422,
            )
        if variant_sku:
            normalized = variant_sku.strip()
            for variant in variants:
                if variant.variant_sku == normalized:
                    return variant
            raise KWorkflowExecutionError(
                "VARIANT_NOT_FOUND",
                "variant_sku was not found for this product.",
                status_code=404,
            )
        if product.product_type == "simple_product" and len(variants) == 1:
            return variants[0]
        raise KWorkflowExecutionError(
            "VARIANT_SKU_REQUIRED",
            "variant_sku is required for variable product image binding.",
            status_code=422,
        )

    def _image_is_bound(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> bool:
        image = execution.image_binding_json or self._product_image_binding_fallback(product)
        return (
            product.image_asset_status == "bound"
            and image.get("status") == "bound"
            and image.get("source_type") in BOUND_IMAGE_SOURCES
        )

    def _product_image_binding_fallback(
        self,
        product: KProductKnowledgeProduct,
    ) -> dict[str, Any]:
        notes = product.media_notes_json if isinstance(product.media_notes_json, dict) else {}
        source_type = str(notes.get("image_source_type") or "").strip()
        if product.image_asset_status != "bound" or source_type not in BOUND_IMAGE_SOURCES:
            return {}
        return {
            "status": "bound",
            "source_type": source_type,
            "asset_id": notes.get("bound_asset_id"),
            "i_system_image_asset_id": notes.get("i_system_image_asset_id"),
            "variant_sku": notes.get("variant_sku"),
            "object_key": notes.get("object_key") or product.selected_image_path,
            "original_url": notes.get("original_url"),
            "preview_url": notes.get("preview_url"),
            "thumbnail_url": notes.get("thumbnail_url"),
            "bound_at": notes.get("bound_at"),
        }

    def _persist_risk_keywords(
        self,
        product: KProductKnowledgeProduct,
        risk_keywords: list[dict[str, Any]],
    ) -> None:
        existing = {
            (_normalize_key(row.term_en), row.risk_type): row
            for row in self.db.scalars(
                select(KProductKnowledgeRiskTerm).where(
                    KProductKnowledgeRiskTerm.product_id == product.id
                )
            )
        }
        for item in risk_keywords:
            term = str(item.get("term") or "").strip()
            if not term:
                continue
            key = (_normalize_key(term), "ai_keyword_risk")
            if key in existing:
                row = existing[key]
                row.risk_reason = item.get("reason") or item.get("risk_reason")
                row.suggested_action = item.get("suggested_action")
                row.source = "claude_opus"
                row.status = "candidate"
                continue
            self.db.add(
                KProductKnowledgeRiskTerm(
                    id=uuid4(),
                    product_id=product.id,
                    term_en=term,
                    risk_type="ai_keyword_risk",
                    risk_reason=item.get("reason") or item.get("risk_reason"),
                    suggested_action=item.get("suggested_action"),
                    source="claude_opus",
                    status="candidate",
                )
            )

    def _persist_risk_decision(
        self,
        product: KProductKnowledgeProduct,
        decision: Any,
        user: User,
    ) -> None:
        row = None
        if decision.risk_term_id is not None:
            row = self.db.get(KProductKnowledgeRiskTerm, decision.risk_term_id)
        if row is None:
            row = self.db.scalar(
                select(KProductKnowledgeRiskTerm).where(
                    KProductKnowledgeRiskTerm.product_id == product.id,
                    KProductKnowledgeRiskTerm.term_en == decision.term,
                )
            )
        if row is None:
            row = KProductKnowledgeRiskTerm(
                id=uuid4(),
                product_id=product.id,
                term_en=decision.term,
                risk_type="manual_review",
                source="manual",
            )
            self.db.add(row)
        row.status = "confirmed" if decision.decision == "approve" else "removed"
        row.confirmed_by_user_id = _user_uuid(user)
        row.confirmed_at = _now()
        row.updated_by_user_id = _user_uuid(user)

    def _remove_rejected_terms_from_keyword_flow(
        self,
        *,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        rejected_terms: list[str],
    ) -> None:
        rejected_keys = {_normalize_key(term) for term in rejected_terms if term.strip()}
        if not rejected_keys:
            return
        claude = dict(execution.claude_filter_result_json or {})
        for key in ("final_keywords", "high_value_keywords", "low_value_keywords"):
            claude[key] = [
                keyword
                for keyword in _safe_string_list(claude.get(key))
                if _normalize_key(keyword) not in rejected_keys
            ]
        risk_keywords = [
            item
            for item in _normalize_risk_keywords(claude.get("risk_keywords"))
            if _normalize_key(item["term"]) not in rejected_keys
        ]
        claude["risk_keywords"] = risk_keywords
        execution.claude_filter_result_json = claude
        product.risk_keywords_json = risk_keywords

    def _upsert_keywords(
        self,
        product: KProductKnowledgeProduct,
        keywords: list[str],
        *,
        keyword_type: str,
        source: str,
        status: str,
        market: str | None,
    ) -> None:
        if not keywords:
            return
        existing = {
            (
                _normalize_key(row.keyword_text),
                row.keyword_type,
                row.language_code,
                row.market or "",
            ): row
            for row in self.db.scalars(
                select(KProductKnowledgeKeyword).where(
                    KProductKnowledgeKeyword.product_id == product.id
                )
            )
        }
        for keyword in _dedupe_strings(keywords):
            key = (
                _normalize_key(keyword),
                keyword_type,
                product.canonical_language,
                market or "",
            )
            row = existing.get(key)
            if row is None:
                self.db.add(
                    KProductKnowledgeKeyword(
                        id=uuid4(),
                        product_id=product.id,
                        keyword_text=keyword,
                        keyword_type=keyword_type,
                        language_code=product.canonical_language,
                        market=market,
                        source=source,
                        status=status,
                    )
                )
                continue
            row.source = source
            row.status = status

    def _add_ai_event(
        self,
        *,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        event_type: str,
        provider_key: ModuleExecutionKey,
        ai_input: dict[str, Any],
        result: dict[str, Any],
        user: User,
    ) -> None:
        self.db.add(
            KProductKnowledgeAIEvent(
                id=uuid4(),
                product_id=product.id,
                research_run_id=None,
                event_type=event_type,
                provider=provider_key.name,
                provider_model=provider_key.key_alias,
                prompt_version=str(
                    (ai_input.get("keyword_research_skill") or {}).get(
                        "version",
                        "k-workflow-v1",
                    )
                ),
                input_hash=_hash_json(ai_input),
                output_summary_json={key: _summary_count(value) for key, value in result.items()},
                output_payload_json=result,
                status="succeeded",
                created_by_user_id=_user_uuid(user),
                updated_by_user_id=_user_uuid(user),
            )
        )

    def _require_product(
        self,
        product_id: UUID,
        scope_context: KScopeContext,
    ) -> KProductKnowledgeProduct:
        product = self.db.scalar(
            apply_scope_filters(
                select(KProductKnowledgeProduct).where(
                    KProductKnowledgeProduct.id == product_id
                ),
                KProductKnowledgeProduct,
                scope_context,
            )
        )
        if product is None:
            raise KProductNotFoundError(f"K product '{product_id}' was not found.")
        if not product.organization_name:
            product.organization_name = TARGET_ORGANIZATION_NAME
        return product

    def _latest_execution(
        self,
        product: KProductKnowledgeProduct,
    ) -> KProductKnowledgeWorkflowExecution | None:
        return self.db.scalar(
            select(KProductKnowledgeWorkflowExecution)
            .where(KProductKnowledgeWorkflowExecution.product_id == product.id)
            .order_by(KProductKnowledgeWorkflowExecution.created_at.desc())
            .limit(1)
        )

    def _require_execution(
        self,
        product: KProductKnowledgeProduct,
        execution_id: UUID | None,
    ) -> KProductKnowledgeWorkflowExecution:
        if execution_id is None:
            execution = self._latest_execution(product)
        else:
            execution = self.db.get(KProductKnowledgeWorkflowExecution, execution_id)
            if execution is not None and execution.product_id != product.id:
                execution = None
        if execution is None:
            raise KWorkflowExecutionError(
                "WORKFLOW_EXECUTION_NOT_FOUND",
                "K workflow execution was not found.",
                status_code=404,
            )
        return execution

    def _append_trace(
        self,
        execution: KProductKnowledgeWorkflowExecution,
        step: str,
        status: str,
        *,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        trace = list(execution.trace_json or [])
        trace.append(
            {
                "step": step,
                "status": status,
                "timestamp": _now_iso(),
                "input_summary": input_summary or {},
                "output_summary": output_summary or {},
                "error": error,
            }
        )
        execution.trace_json = trace
        execution.current_step = step

    def _append_gate_log(
        self,
        execution: KProductKnowledgeWorkflowExecution,
        gate: str,
        status: str,
        details: dict[str, Any],
    ) -> None:
        logs = list(execution.execution_gate_logs_json or [])
        logs.append(
            {
                "gate": gate,
                "status": status,
                "timestamp": _now_iso(),
                "details": details,
            }
        )
        execution.execution_gate_logs_json = logs

    def _rollback_session_for_workflow(
        self,
        *,
        step: str,
        reason: str,
        raw_error: Exception | None = None,
    ) -> bool:
        try:
            needs_rollback = self.db.in_transaction() or self.db.in_nested_transaction()
        except Exception:
            needs_rollback = True
        if not needs_rollback:
            return False
        try:
            self.db.rollback()
        except Exception as rollback_error:
            logger.exception(
                "K workflow DB rollback failed: step=%s reason=%s raw_error=%s",
                step,
                reason,
                raw_error.__class__.__name__ if raw_error else None,
            )
            raise
        logger.warning(
            "K workflow DB session rolled back: step=%s reason=%s error_class=%s",
            step,
            reason,
            raw_error.__class__.__name__ if raw_error else None,
        )
        return True

    def _dispose_provider_session(
        self,
        provider_db: Session,
        *,
        step: str,
        reason: str,
        raw_error: Exception | None = None,
    ) -> None:
        try:
            provider_db.invalidate()
        except Exception as invalidate_error:
            logger.warning(
                "K workflow provider DB session invalidation failed: "
                "step=%s reason=%s raw_error=%s invalidate_error=%s",
                step,
                reason,
                raw_error.__class__.__name__ if raw_error else None,
                invalidate_error.__class__.__name__,
            )

    def _commit_workflow_progress(
        self,
        *,
        product: KProductKnowledgeProduct | None,
        execution: KProductKnowledgeWorkflowExecution,
        step: str,
        reason: str,
    ) -> None:
        try:
            if product is not None:
                self.db.add(product)
            self.db.add(execution)
            self.db.commit()
        except Exception as exc:
            self._rollback_session_for_workflow(
                step=step,
                reason=f"{reason}_commit_failed",
                raw_error=exc,
            )
            logger.exception(
                "K workflow state commit failed: step=%s reason=%s status=%s",
                step,
                reason,
                execution.status,
            )
            raise KWorkflowExecutionError(
                "K_WORKFLOW_STATE_PERSIST_FAILED",
                "K workflow state could not be persisted safely.",
                status_code=503,
                error_report={
                    "code": "K_WORKFLOW_STATE_PERSIST_FAILED",
                    "message": "K workflow state could not be persisted safely.",
                    "blocking_step": step,
                    "workflow_id": str(execution.id),
                    "product_id": str(execution.product_id),
                    "organization": execution.organization_name,
                    "rollback_reason": f"{reason}_commit_failed",
                    "raw_error_class": exc.__class__.__name__,
                    "must_stop": True,
                    "timestamp": _now_iso(),
                },
            ) from exc

    def _reload_workflow_objects(
        self,
        *,
        product_id: UUID,
        execution_id: UUID,
        step: str,
    ) -> tuple[KProductKnowledgeProduct, KProductKnowledgeWorkflowExecution]:
        product = self.db.get(KProductKnowledgeProduct, product_id)
        execution = self.db.get(KProductKnowledgeWorkflowExecution, execution_id)
        if product is None or execution is None:
            raise KWorkflowExecutionError(
                "K_WORKFLOW_PARTIAL_STATE_NOT_FOUND",
                "K workflow partial state could not be reloaded after rollback.",
                status_code=503,
                error_report={
                    "code": "K_WORKFLOW_PARTIAL_STATE_NOT_FOUND",
                    "message": "K workflow partial state could not be reloaded after rollback.",
                    "blocking_step": step,
                    "product_id": str(product_id),
                    "workflow_id": str(execution_id),
                    "must_stop": True,
                    "timestamp": _now_iso(),
                },
            )
        return product, execution

    def _persist_step_failure_after_rollback(
        self,
        *,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        step: str,
        raw_error: Exception,
        attempts: int,
    ) -> KProductKnowledgeWorkflowExecution:
        self._rollback_session_for_workflow(
            step=step,
            reason="provider_step_failure",
            raw_error=raw_error,
        )
        product, execution = self._reload_workflow_objects(
            product_id=product.id,
            execution_id=execution.id,
            step=step,
        )
        if isinstance(raw_error, KWorkflowExecutionError):
            code = raw_error.code
            status_code = raw_error.status_code
            provider_failure_reason = str(raw_error)
        else:
            code = "K_WORKFLOW_PROVIDER_STEP_FAILED"
            status_code = 502
            provider_failure_reason = "K workflow provider step failed."
        error_report = self._error_report(
            execution,
            code=code,
            message=provider_failure_reason,
            step=step,
            details={
                "failed_step": step,
                "db_rollback_reason": "provider_step_failure",
                "provider_failure_reason": provider_failure_reason,
                "raw_error_class": raw_error.__class__.__name__,
                "attempts": attempts,
                "retry_available": True,
                "status_code": status_code,
                "partial_state": "blocked",
            },
            raw_error=raw_error,
        )
        execution.status = "blocked"
        execution.current_step = step
        execution.error_report_json = error_report
        execution.finished_at = None
        self._append_trace(execution, step, "failed", error=error_report)
        self._append_gate_log(
            execution,
            "workflow_resilience",
            "blocked",
            {
                "failed_step": step,
                "code": code,
                "db_rollback_reason": "provider_step_failure",
                "provider_failure_reason": provider_failure_reason,
                "raw_error_class": raw_error.__class__.__name__,
                "attempts": attempts,
                "retry_available": True,
                "partial_state": "blocked",
            },
        )
        self._commit_workflow_progress(
            product=product,
            execution=execution,
            step=step,
            reason="provider_step_failure_persisted",
        )
        logger.warning(
            "K workflow provider step isolated: workflow_id=%s product_id=%s step=%s attempts=%s error=%s",
            execution.id,
            product.id,
            step,
            attempts,
            raw_error.__class__.__name__,
        )
        return execution

    def _run_resilient_provider_step(
        self,
        *,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        step: str,
        runner: Callable[
            [KProductKnowledgeProduct, KProductKnowledgeWorkflowExecution],
            Any,
        ],
    ) -> tuple[bool, Any, KProductKnowledgeProduct, KProductKnowledgeWorkflowExecution]:
        product_id = product.id
        execution_id = execution.id
        last_error: Exception | None = None
        for attempt in range(1, K_WORKFLOW_PROVIDER_STEP_MAX_ATTEMPTS + 1):
            try:
                self._append_gate_log(
                    execution,
                    "workflow_resilience",
                    "attempt",
                    {
                        "step": step,
                        "attempt": attempt,
                        "max_attempts": K_WORKFLOW_PROVIDER_STEP_MAX_ATTEMPTS,
                    },
                )
                self._commit_workflow_progress(
                    product=product,
                    execution=execution,
                    step=step,
                    reason="provider_step_attempt_started",
                )
                result = runner(product, execution)
                return True, result, product, execution
            except Exception as exc:
                last_error = exc
                self._rollback_session_for_workflow(
                    step=step,
                    reason="provider_step_attempt_failed",
                    raw_error=exc,
                )
                product, execution = self._reload_workflow_objects(
                    product_id=product_id,
                    execution_id=execution_id,
                    step=step,
                )
                if attempt < K_WORKFLOW_PROVIDER_STEP_MAX_ATTEMPTS:
                    execution.status = "running"
                    execution.current_step = step
                    execution.error_report_json = None
                    execution.finished_at = None
                    self._append_gate_log(
                        execution,
                        "workflow_resilience",
                        "retry",
                        {
                            "step": step,
                            "attempt": attempt,
                            "next_attempt": attempt + 1,
                            "db_rollback_reason": "provider_step_attempt_failed",
                            "provider_failure_reason": str(exc),
                            "raw_error_class": exc.__class__.__name__,
                        },
                    )
                    self._commit_workflow_progress(
                        product=product,
                        execution=execution,
                        step=step,
                        reason="provider_step_retry_scheduled",
                    )
                    continue
                blocked = self._persist_step_failure_after_rollback(
                    product=product,
                    execution=execution,
                    step=step,
                    raw_error=exc,
                    attempts=attempt,
                )
                return False, None, product, blocked
        raise last_error or KWorkflowExecutionError(
            "K_WORKFLOW_PROVIDER_STEP_FAILED",
            "K workflow provider step failed.",
            status_code=502,
        )

    def _fail_execution(
        self,
        execution: KProductKnowledgeWorkflowExecution,
        *,
        code: str,
        message: str,
        step: str,
        status_code: int,
        details: dict[str, Any] | None = None,
        raw_error: Exception | None = None,
    ) -> None:
        error_report = self._error_report(
            execution,
            code=code,
            message=message,
            step=step,
            details=details,
            raw_error=raw_error,
        )
        execution.status = "failed"
        execution.current_step = step
        execution.error_report_json = error_report
        execution.finished_at = _now()
        self._append_trace(execution, step, "failed", error=error_report)
        self._append_gate_log(
            execution,
            "failure_block",
            "blocked",
            {"code": code, "message": message},
        )
        self._commit_workflow_progress(
            product=None,
            execution=execution,
            step=step,
            reason="workflow_failed",
        )
        raise KWorkflowExecutionError(
            code,
            message,
            status_code=status_code,
            error_report=error_report,
        )

    def _error_report(
        self,
        execution: KProductKnowledgeWorkflowExecution,
        *,
        code: str,
        message: str,
        step: str,
        details: dict[str, Any] | None = None,
        raw_error: Exception | None = None,
    ) -> dict[str, Any]:
        report: dict[str, Any] = {
            "status": "failed",
            "reason": _workflow_error_reason(code),
            "code": code,
            "message": message,
            "blocking_step": step,
            "workflow_id": str(execution.id),
            "product_id": str(execution.product_id),
            "organization": execution.organization_name,
            "must_stop": True,
            "timestamp": _now_iso(),
        }
        if details:
            report["details"] = details
        if raw_error is not None:
            report["raw_error_class"] = raw_error.__class__.__name__
        return report


CLOSED_LOOP_STEP_ALIASES = {
    "risk_term_review_manual": "risk_term_manual_review",
    "image_handling": "image_binding",
    "export_p_gmc_seo": "export_p_series",
}
CLOSED_LOOP_STEP_ORDER = {
    step: index for index, step in enumerate(CLOSED_LOOP_WORKFLOW_STEPS_V2)
}
CLOSED_LOOP_PREVIOUS_STATE = {
    "product_ingestion": "PRODUCT_CREATED",
    "deepseek_enrichment": "PRODUCT_CREATED",
    "serp_keyword_fetch": "AI_DEEPSEEK_ENRICHED",
    "ai_filter_chatgpt": "SERP_ANALYZED",
    "ai_filter_claude_opus": "CHATGPT_FILTERED",
    "risk_term_manual_review": "CLAUDE_FILTERED",
    "keyword_optimization_ai": "RISK_APPROVED",
    "unit_conversion_normalization": "KEYWORD_OPTIMIZED",
    "image_binding": "UNIT_NORMALIZED",
    "export_p_series": "IMAGE_BOUND",
    "export_gmc": "EXPORT_READY",
    "export_seo": "EXPORT_READY",
}


def _canonical_closed_loop_step(step: str) -> str:
    normalized = step.strip()
    normalized = CLOSED_LOOP_STEP_ALIASES.get(normalized, normalized)
    if normalized not in CLOSED_LOOP_STEP_ORDER:
        raise KWorkflowExecutionError(
            "K_WORKFLOW_STEP_UNKNOWN",
            f"K workflow step '{step}' is not part of the closed loop.",
            status_code=422,
        )
    return normalized


def _closed_loop_step_order(step: str) -> int:
    return CLOSED_LOOP_STEP_ORDER[_canonical_closed_loop_step(step)]


def _state_before_closed_loop_step(step: str) -> str:
    return CLOSED_LOOP_PREVIOUS_STATE[_canonical_closed_loop_step(step)]


def _trace_has_step(
    execution: KProductKnowledgeWorkflowExecution,
    step: str,
) -> bool:
    return any(item.get("step") == step for item in execution.trace_json or [])


def _rollback_deepseek_product_fields(product: KProductKnowledgeProduct) -> None:
    diff = (product.field_diff_json or {}).get("deepseek_enrichment")
    if isinstance(diff, dict):
        for field, change in diff.items():
            if field not in DEEPSEEK_ENRICHMENT_FIELDS or not isinstance(change, dict):
                continue
            setattr(product, field, change.get("before"))
    product.deepseek_structured_output_json = None
    product.review_status = "draft"
    product.field_diff_json = {
        key: value
        for key, value in (product.field_diff_json or {}).items()
        if key != "deepseek_enrichment"
    }


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat()


def _user_uuid(user: User) -> UUID:
    return uuid5(NAMESPACE_URL, f"barong-ops-console-user:{user.id}")


def _product_snapshot(product: KProductKnowledgeProduct) -> dict[str, Any]:
    return {
        "id": str(product.id),
        "product_key": product.product_key,
        "sku": product.sku,
        "product_name_en": product.product_name_en,
        "brand_name": product.brand_name,
        "manufacturer": product.manufacturer,
        "product_type": product.product_type,
        "short_description_en": product.short_description_en,
        "long_description_en": product.long_description_en,
        "primary_use_case_en": product.primary_use_case_en,
        "target_customer_en": product.target_customer_en,
        "organization_name": product.organization_name,
    }


def _json_object_from_text(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _merge_provider_output(provider_output: dict[str, Any]) -> dict[str, Any]:
    merged = dict(provider_output)
    for key in ("result", "output", "data", "response"):
        nested = merged.get(key)
        if isinstance(nested, dict):
            merged = {**merged, **nested}
    parsed_content = _json_object_from_text(merged.get("content"))
    if parsed_content:
        merged = {**merged, **parsed_content}
    return merged


def _safe_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return _dedupe_strings(
            [
                item.strip(" -:;,.\"'")
                for item in re.split(r"[\n,，;；|]+", value)
                if item.strip(" -:;,.\"'")
            ]
        )
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if isinstance(item, str):
            keyword = item.strip()
        elif isinstance(item, dict):
            keyword = str(
                item.get("keyword")
                or item.get("term")
                or item.get("text")
                or item.get("query")
                or item.get("phrase")
                or item.get("value")
                or item.get("name")
                or ""
            ).strip()
        else:
            keyword = str(item).strip()
        if keyword:
            output.append(keyword)
    return _dedupe_strings(output)


def _string_list_from_aliases(
    provider_output: dict[str, Any],
    aliases: tuple[str, ...],
) -> list[str]:
    for alias in aliases:
        values = _safe_string_list(provider_output.get(alias))
        if values:
            return values
    return []


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = _normalize_key(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(value.strip())
    return output


def _normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _organic_results(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("name") or "").strip()
        url = str(raw.get("url") or raw.get("link") or "").strip()
        if not title or not url:
            continue
        items.append(
            {
                "title": title,
                "url": url,
                "snippet": str(raw.get("snippet") or raw.get("description") or ""),
                "rank": int(raw.get("rank") or raw.get("position") or index),
            }
        )
    return items


def _keywords_from_organic_results(
    organic_results: list[dict[str, Any]],
    query: str,
) -> list[str]:
    candidates = [query]
    for item in organic_results[:10]:
        candidates.extend(_keyword_phrases(str(item.get("title") or "")))
    return _dedupe_strings(candidates)[:25]


def _keyword_phrases(value: str) -> list[str]:
    cleaned = re.sub(r"[^A-Za-z0-9\s-]", " ", value)
    words = [word for word in cleaned.split() if len(word) > 2]
    phrases: list[str] = []
    for size in (2, 3, 4):
        for index in range(0, max(0, len(words) - size + 1)):
            phrases.append(" ".join(words[index : index + size]))
    return phrases


def _strict_json_messages(
    *,
    instruction: str,
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True),
        },
    ]


def _keywords_from_provider_content(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    quoted = re.findall(r'"([^"]{2,100})"', value)
    if quoted:
        return _dedupe_strings(
            [item.strip(" -:;,.") for item in quoted if 1 <= len(item.split()) <= 8]
        )[:20]
    candidates: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*\d.)\s]+", "", line).strip()
        if ":" in line:
            label, rest = line.split(":", 1)
            if any(token in label.lower() for token in ("keyword", "final", "high", "low")):
                line = rest.strip()
        for part in re.split(r"[,;|]", line):
            candidate = part.strip(" -:;,.\"'")
            if not candidate or len(candidate) > 100:
                continue
            if not re.search(r"[A-Za-z]", candidate):
                continue
            if len(candidate.split()) > 8:
                continue
            candidates.append(candidate)
    return _dedupe_strings(candidates)[:20]


def _normalize_chatgpt_result(provider_output: dict[str, Any]) -> dict[str, Any]:
    provider_output = _merge_provider_output(provider_output)
    content_keywords = _keywords_from_provider_content(provider_output.get("content"))
    filtered = (
        _string_list_from_aliases(
            provider_output,
            (
                "filtered_keywords",
                "approved_keywords",
                "selected_keywords",
                "recommended_keywords",
                "buyer_intent_keywords",
            ),
        )
        or content_keywords
    )
    cleaned = (
        _string_list_from_aliases(
            provider_output,
            ("cleaned_keywords", "keywords", "keyword_candidates"),
        )
        or filtered
    )
    rejected = (
        _string_list_from_aliases(
            provider_output,
            ("rejected_keywords", "removed_keywords", "negative_keywords"),
        )
    )
    rationale = provider_output.get("rationale") or provider_output.get("reasoning") or ""
    return {
        "cleaned_keywords": cleaned,
        "filtered_keywords": filtered or cleaned,
        "rejected_keywords": rejected,
        "rationale": rationale,
    }


def _normalize_claude_result(provider_output: dict[str, Any]) -> dict[str, Any]:
    provider_output = _merge_provider_output(provider_output)
    content_keywords = _keywords_from_provider_content(provider_output.get("content"))
    high_value = (
        _string_list_from_aliases(
            provider_output,
            (
                "high_value_keywords",
                "high_intent_keywords",
                "priority_keywords",
                "approved_keywords",
                "safe_keywords",
                "recommended_keywords",
                "buyer_intent_keywords",
                "commercial_keywords",
                "conversion_keywords",
            ),
        )
    )
    low_value = (
        _string_list_from_aliases(
            provider_output,
            (
                "low_value_keywords",
                "secondary_keywords",
                "supporting_keywords",
                "longtail_keywords",
                "long_tail_keywords",
                "informational_keywords",
            ),
        )
    )
    final = (
        _string_list_from_aliases(
            provider_output,
            (
                "final_keywords",
                "keywords",
                "selected_keywords",
                "approved_keywords",
                "recommended_keywords",
                "safe_keywords",
                "non_risk_keywords",
                "nonrisk_keywords",
                "viable_keywords",
                "optimized_keywords",
                "target_keywords",
                "buyer_intent_keywords",
                "high_conversion_keywords",
            ),
        )
        or _dedupe_strings([*high_value, *low_value])
        or content_keywords
    )
    risk_keywords = _normalize_risk_keywords(
        provider_output.get("risk_keywords")
        or provider_output.get("risky_keywords")
        or provider_output.get("restricted_keywords")
        or provider_output.get("unsafe_keywords")
        or provider_output.get("trademark_keywords")
    )
    risk_keys = {_normalize_key(item["term"]) for item in risk_keywords}
    final = [keyword for keyword in final if _normalize_key(keyword) not in risk_keys]
    if not high_value and final:
        high_value = final[: min(5, len(final))]
    return {
        "final_keywords": final,
        "high_value_keywords": high_value,
        "low_value_keywords": low_value,
        "risk_keywords": risk_keywords,
    }


def _normalize_risk_keywords(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            term = item.strip()
            reason = None
        elif isinstance(item, dict):
            term = str(item.get("term") or item.get("keyword") or "").strip()
            reason = item.get("reason") or item.get("risk_reason")
        else:
            continue
        if not term:
            continue
        output.append({"term": term, "reason": reason})
    return output


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _summary_count(value: Any) -> int | str:
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return "present" if value else "empty"


def _cluster_keywords(keywords: list[str]) -> dict[str, list[str]]:
    clusters: dict[str, list[str]] = {}
    for keyword in keywords:
        intent = _classify_intent(keyword)
        first_word = keyword.split()[0].lower() if keyword.split() else "general"
        cluster_key = f"{intent}:{first_word}"
        clusters.setdefault(cluster_key, []).append(keyword)
    return clusters


def _classify_intent(keyword: str) -> str:
    lowered = keyword.lower()
    if any(token in lowered for token in ("buy", "price", "wholesale", "supplier")):
        return "transactional"
    if any(token in lowered for token in ("best", "review", "compare", "vs")):
        return "commercial"
    if any(token in lowered for token in ("how", "what", "guide", "use")):
        return "informational"
    return "category"


def _normalize_units_for_market(value: Any, market: str) -> Any:
    if market not in IMPERIAL_TARGET_MARKETS:
        return {"original": value, "normalized": value, "converted": False}
    return {"original": value, "normalized": _convert_unit_payload(value), "converted": True}


def _convert_unit_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [_convert_unit_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    converted = {key: _convert_unit_payload(item) for key, item in value.items()}
    unit = str(value.get("unit") or value.get("units") or "").strip().lower()
    if unit in UNIT_CONVERSIONS:
        target_unit, factor = UNIT_CONVERSIONS[unit]
        converted["normalized_unit"] = target_unit
        for key, item in value.items():
            if key in {"unit", "units"}:
                continue
            number = _decimal_or_none(item)
            if number is not None:
                converted[f"{key}_{target_unit}"] = float(round(number * factor, 4))
    for key, item in value.items():
        lowered = key.lower()
        number = _decimal_or_none(item)
        if number is None:
            continue
        for source_unit, (target_unit, factor) in UNIT_CONVERSIONS.items():
            suffix = f"_{source_unit}"
            if lowered.endswith(suffix):
                converted[f"{key[: -len(suffix)]}_{target_unit}"] = float(
                    round(number * factor, 4)
                )
    return converted


def _decimal_or_none(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _price(value: Decimal | None, currency: str | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f} {currency or 'USD'}"


def _image_source_type(asset: KProductKnowledgeMediaAsset) -> str:
    if isinstance(asset.metadata_json, dict):
        source_type = str(asset.metadata_json.get("source_type") or "").strip()
        if source_type:
            return source_type
    if asset.source == IMAGE_SOURCE_I_SYSTEM:
        return IMAGE_SOURCE_I_SYSTEM
    return IMAGE_SOURCE_MANUAL


def _i_system_asset_id(asset: KProductKnowledgeMediaAsset) -> str | None:
    if isinstance(asset.metadata_json, dict):
        value = asset.metadata_json.get("i_system_image_asset_id")
        if value is not None and str(value).strip():
            return str(value).strip()
    if asset.source == IMAGE_SOURCE_I_SYSTEM and asset.object_key:
        return asset.object_key.rsplit("/", 1)[-1]
    return None


class KWorkflowOrchestratorV1(KProductKnowledgeWorkflowEngine):
    """K-series product knowledge orchestrator with image-system separation."""


class KWorkflowOrchestratorV2(KWorkflowOrchestratorV1):
    """Closed-loop K-series workflow state machine and orchestration layer."""

    state_machine = KWorkflowStateMachineV2

    def run(
        self,
        *,
        product_id: UUID,
        payload: ProductKnowledgeWorkflowStartRequest,
        scope_context: KScopeContext,
        request: Request,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        product = self._require_product(product_id, scope_context)
        execution = self._create_execution(
            product=product,
            payload=payload,
            scope_context=scope_context,
            user=user,
        )
        try:
            self._validate_organization(product, scope_context, execution)
            self._append_trace(
                execution,
                "product_ingestion",
                "completed",
                output_summary={
                    "product_id": str(product.id),
                    "product_key": product.product_key,
                    "organization": product.organization_name,
                },
            )
            self._transition_state(
                product,
                execution,
                "PRODUCT_CREATED",
                step="product_ingestion",
            )
            self._commit_workflow_progress(
                product=product,
                execution=execution,
                step="product_ingestion",
                reason="product_ingestion_completed",
            )
            try:
                gate_context = self._require_execution_gate(
                    execution=execution,
                    request=request,
                    user=user,
                    key_requirements=CLOSED_LOOP_AI_KEY_REQUIREMENTS,
                )
            except Exception as exc:
                return self._persist_step_failure_after_rollback(
                    product=product,
                    execution=execution,
                    step=execution.current_step,
                    raw_error=exc,
                    attempts=1,
                )
            self._commit_workflow_progress(
                product=product,
                execution=execution,
                step="execution_gate",
                reason="execution_gate_allowed",
            )
            ok, _deepseek_result, product, execution = self._run_resilient_provider_step(
                product=product,
                execution=execution,
                step="deepseek_enrichment",
                runner=lambda current_product, current_execution: (
                    self._run_deepseek_enrichment(
                        product=current_product,
                        execution=current_execution,
                        gate_context=gate_context,
                        user=user,
                    )
                ),
            )
            if not ok:
                return execution
            self._transition_state(
                product,
                execution,
                "AI_DEEPSEEK_ENRICHED",
                step="deepseek_enrichment",
            )
            self._commit_workflow_progress(
                product=product,
                execution=execution,
                step="deepseek_enrichment",
                reason="provider_step_completed",
            )
            ok, serp_result, product, execution = self._run_resilient_provider_step(
                product=product,
                execution=execution,
                step="serp_keyword_fetch",
                runner=lambda current_product, current_execution: (
                    self._fetch_serp_keywords(
                        product=current_product,
                        execution=current_execution,
                        payload=payload,
                        gate_context=gate_context,
                        user=user,
                    )
                ),
            )
            if not ok:
                return execution
            self._transition_state(
                product,
                execution,
                "SERP_ANALYZED",
                step="serp_keyword_fetch",
            )
            self._commit_workflow_progress(
                product=product,
                execution=execution,
                step="serp_keyword_fetch",
                reason="provider_step_completed",
            )
            ok, chatgpt_result, product, execution = self._run_resilient_provider_step(
                product=product,
                execution=execution,
                step="ai_filter_chatgpt",
                runner=lambda current_product, current_execution: (
                    self._run_chatgpt_filter(
                        product=current_product,
                        execution=current_execution,
                        serp_result=serp_result,
                        gate_context=gate_context,
                        user=user,
                    )
                ),
            )
            if not ok:
                return execution
            self._transition_state(
                product,
                execution,
                "CHATGPT_FILTERED",
                step="ai_filter_chatgpt",
            )
            self._commit_workflow_progress(
                product=product,
                execution=execution,
                step="ai_filter_chatgpt",
                reason="provider_step_completed",
            )
            ok, claude_result, product, execution = self._run_resilient_provider_step(
                product=product,
                execution=execution,
                step="ai_filter_claude_opus",
                runner=lambda current_product, current_execution: (
                    self._run_claude_filter(
                        product=current_product,
                        execution=current_execution,
                        chatgpt_result=chatgpt_result,
                        gate_context=gate_context,
                        user=user,
                    )
                ),
            )
            if not ok:
                return execution
            self._transition_state(
                product,
                execution,
                "CLAUDE_FILTERED",
                step="ai_filter_claude_opus",
            )
            self._commit_workflow_progress(
                product=product,
                execution=execution,
                step="ai_filter_claude_opus",
                reason="provider_step_completed",
            )
            self._create_manual_risk_review_block(
                product=product,
                execution=execution,
                claude_result=claude_result,
            )
            self._transition_state(
                product,
                execution,
                "RISK_PENDING_REVIEW",
                step="risk_term_manual_review",
                event="hard_gate_blocked",
                details={"manual_approval_required": True},
            )
            self._commit_workflow_progress(
                product=product,
                execution=execution,
                step="risk_term_manual_review",
                reason="manual_risk_review_required",
            )
            return execution
        except KWorkflowExecutionError as exc:
            return self._persist_step_failure_after_rollback(
                product=product,
                execution=execution,
                step=execution.current_step,
                raw_error=exc,
                attempts=1,
            )
        except Exception as exc:
            return self._persist_step_failure_after_rollback(
                product=product,
                execution=execution,
                step=execution.current_step,
                raw_error=exc,
                attempts=1,
            )

    def start_pipeline(
        self,
        *,
        product_id: UUID,
        payload: ProductKnowledgeWorkflowStartRequest,
        scope_context: KScopeContext,
        request: Request,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        return self.run(
            product_id=product_id,
            payload=payload,
            scope_context=scope_context,
            request=request,
            user=user,
        )

    def review_risk_terms(
        self,
        *,
        product_id: UUID,
        payload: ProductKnowledgeRiskReviewRequest,
        scope_context: KScopeContext,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        return super().review_risk_terms(
            product_id=product_id,
            payload=payload,
            scope_context=scope_context,
            user=user,
        )

    def bind_image_asset(
        self,
        *,
        product_id: UUID,
        payload: ProductKnowledgeImageBindRequest,
        scope_context: KScopeContext,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        execution = super().bind_image_asset(
            product_id=product_id,
            payload=payload,
            scope_context=scope_context,
            user=user,
        )
        product = self._require_product(product_id, scope_context)
        self._transition_state(product, execution, "IMAGE_BOUND", step="image_binding")
        if self._risk_review_is_approved(execution) and execution.final_keyword_set_json:
            self._mark_export_ready(product, execution)
        return execution

    def export_payloads(
        self,
        *,
        product_id: UUID,
        payload: ProductKnowledgeWorkflowExportRequest,
        scope_context: KScopeContext,
        user: User,
    ) -> tuple[KProductKnowledgeWorkflowExecution, ProductKnowledgeWorkflowReport]:
        product = self._require_product(product_id, scope_context)
        execution = self._require_execution(product, payload.execution_id)
        blockers = self._export_blockers(product, execution)
        if blockers:
            execution.status = "blocked"
            execution.current_step = "export_p_series"
            execution.error_report_json = self._error_report(
                execution,
                code="EXPORT_GATE_BLOCKED",
                message="K export is blocked until the complete workflow is satisfied.",
                step="export_p_series",
                details={"blockers": blockers},
            )
            self._append_trace(
                execution,
                "export_p_series",
                "blocked",
                error=execution.error_report_json,
            )
            self.db.add(execution)
            self.db.commit()
            raise KWorkflowExecutionError(
                "EXPORT_GATE_BLOCKED",
                "K export is blocked until the complete workflow is satisfied.",
                error_report=execution.error_report_json,
            )

        export_payloads = self._build_export_payloads(product, execution)
        execution.export_payloads_json = export_payloads
        for step, key in (
            ("export_p_series", "p_series_payload"),
            ("export_gmc", "gmc_feed_structure"),
            ("export_seo", "seo_keyword_pack"),
        ):
            self._append_trace(
                execution,
                step,
                "completed",
                output_summary={"payload": key, "generated": key in export_payloads},
            )
        execution.status = "exported"
        execution.current_step = "export_seo"
        execution.finished_at = _now()
        execution.updated_by_user_id = _user_uuid(user)
        execution.error_report_json = None
        self._transition_state(
            product,
            execution,
            "EXPORTED",
            step="export_seo",
            event="closed_loop_completed",
            details={"payloads": ["p_series_payload", "gmc_feed_structure", "seo_keyword_pack"]},
        )
        self.db.add(execution)
        self.db.flush()
        return execution, self.build_report(execution)

    def pause(
        self,
        *,
        workflow_id: UUID,
        scope_context: KScopeContext,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        product, execution = self._require_workflow_execution(
            workflow_id=workflow_id,
            scope_context=scope_context,
        )
        del product
        if execution.status in {"exported", "failed"}:
            raise KWorkflowExecutionError(
                "WORKFLOW_PAUSE_NOT_ALLOWED",
                "Only active or blocked workflows can be paused.",
                status_code=409,
            )
        execution.status = "blocked"
        execution.error_report_json = self._error_report(
            execution,
            code="WORKFLOW_PAUSED",
            message="K workflow was paused by the operator.",
            step=execution.current_step,
            details={"paused_by_user_id": str(user.id)},
        )
        self._append_trace(execution, execution.current_step, "paused")
        self._append_gate_log(
            execution,
            "workflow_control",
            "paused",
            {"workflow_id": str(workflow_id), "paused_by_user_id": str(user.id)},
        )
        self.db.add(execution)
        self.db.flush()
        return execution

    def resume(
        self,
        *,
        workflow_id: UUID,
        scope_context: KScopeContext,
        request: Request,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        product, execution = self._require_workflow_execution(
            workflow_id=workflow_id,
            scope_context=scope_context,
        )
        error_code = (execution.error_report_json or {}).get("code")
        if execution.status == "failed":
            raise KWorkflowExecutionError(
                "WORKFLOW_RETRY_OR_ROLLBACK_REQUIRED",
                "Failed K workflows can only continue through retry or rollback.",
                status_code=409,
            )
        if error_code == "WORKFLOW_PAUSED":
            execution.error_report_json = None
        state = self.state_machine.current_state(execution, product)
        if state == "RISK_PENDING_REVIEW":
            self._block_risk_review(execution)
            return execution
        if not self._risk_review_is_approved(execution):
            self._block_risk_review(execution)
            return execution
        if state in {"RISK_APPROVED", "KEYWORD_OPTIMIZED", "UNIT_NORMALIZED"}:
            return self._continue_after_risk_review(product, execution, user)
        if self._image_is_bound(product, execution):
            self._mark_export_ready(product, execution)
            exported, _report = self.export_payloads(
                product_id=product.id,
                payload=ProductKnowledgeWorkflowExportRequest(execution_id=execution.id),
                scope_context=scope_context,
                user=user,
            )
            return exported
        execution.status = "blocked"
        execution.current_step = "image_binding"
        execution.error_report_json = self._error_report(
            execution,
            code="IMAGE_BINDING_REQUIRED",
            message="A manual upload or I-system image asset must be bound before export.",
            step="image_binding",
        )
        self._append_trace(execution, "image_binding", "blocked", error=execution.error_report_json)
        self.db.add(execution)
        self.db.flush()
        return execution

    def retry(
        self,
        *,
        workflow_id: UUID,
        step: str,
        payload: ProductKnowledgeWorkflowStartRequest | None,
        scope_context: KScopeContext,
        request: Request,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        product, execution = self._require_workflow_execution(
            workflow_id=workflow_id,
            scope_context=scope_context,
        )
        canonical_step = _canonical_closed_loop_step(step)
        retry_payload = payload or ProductKnowledgeWorkflowStartRequest(
            target_market=execution.target_market,
            target_region=execution.target_region,
        )
        self._clear_outputs_from_step(product, execution, canonical_step, user=user)
        execution.status = "running"
        execution.error_report_json = None
        execution.finished_at = None
        self._append_gate_log(
            execution,
            "workflow_control",
            "retry",
            {"workflow_id": str(workflow_id), "step": canonical_step},
        )
        return self._rerun_from_step(
            product=product,
            execution=execution,
            step=canonical_step,
            payload=retry_payload,
            scope_context=scope_context,
            request=request,
            user=user,
        )

    def rollback(
        self,
        *,
        workflow_id: UUID,
        step: str,
        scope_context: KScopeContext,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        product, execution = self._require_workflow_execution(
            workflow_id=workflow_id,
            scope_context=scope_context,
        )
        canonical_step = _canonical_closed_loop_step(step)
        self._clear_outputs_from_step(product, execution, canonical_step, user=user)
        self._transition_state(
            product,
            execution,
            _state_before_closed_loop_step(canonical_step),
            step=canonical_step,
            event="rolled_back",
            allow_backward=True,
        )
        execution.status = "blocked"
        execution.current_step = canonical_step
        execution.error_report_json = self._error_report(
            execution,
            code="WORKFLOW_ROLLED_BACK",
            message="K workflow was rolled back. Use retry to continue from this step.",
            step=canonical_step,
            details={"rollback_by_user_id": str(user.id)},
        )
        self._append_trace(execution, canonical_step, "rolled_back", error=execution.error_report_json)
        self._append_gate_log(
            execution,
            "workflow_control",
            "rolled_back",
            {"workflow_id": str(workflow_id), "step": canonical_step},
        )
        self.db.add_all([product, execution])
        self.db.flush()
        return execution

    def _continue_after_risk_review(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        self._transition_state(
            product,
            execution,
            "RISK_APPROVED",
            step="risk_term_manual_review",
            event="manual_gate_approved",
        )
        self._optimize_keywords(product, execution, user)
        self._transition_state(
            product,
            execution,
            "KEYWORD_OPTIMIZED",
            step="keyword_optimization_ai",
        )
        self._normalize_units(product, execution)
        self._transition_state(
            product,
            execution,
            "UNIT_NORMALIZED",
            step="unit_conversion_normalization",
        )
        if not product.marketing_copy_json:
            execution.status = "blocked"
            execution.current_step = "marketing_copy_generation"
            execution.error_report_json = self._error_report(
                execution,
                code="MARKETING_COPY_REQUIRED",
                message="Generate the product marketing copy before export.",
                step="marketing_copy_generation",
            )
            self._append_trace(
                execution,
                "marketing_copy_generation",
                "blocked",
                error=execution.error_report_json,
            )
            self.db.add_all([product, execution])
            self.db.flush()
            return execution
        if not self._image_is_bound(product, execution):
            execution.status = "blocked"
            execution.current_step = "image_binding"
            execution.error_report_json = self._error_report(
                execution,
                code="IMAGE_BINDING_REQUIRED",
                message="A manual upload or I-system image asset must be bound before export.",
                step="image_binding",
            )
            self._append_trace(
                execution,
                "image_binding",
                "blocked",
                error=execution.error_report_json,
            )
            self.db.add_all([product, execution])
            self.db.flush()
            return execution
        self._transition_state(product, execution, "IMAGE_BOUND", step="image_binding")
        self._mark_export_ready(product, execution)
        self.db.add_all([product, execution])
        self.db.flush()
        return execution

    def _plain_chinese(self, original, label, *, user, request):
        """Best-effort DeepSeek translation of the generated JSON into plain
        Chinese for operator review. Resolves its OWN gate and swallows every
        error: the English original is the ONLY thing sent to P-series / into
        I-series, so a missing/failed translation must never block it.
        """
        try:
            gate_context = self.gate_resolver(
                self.db,
                module_id=MODULE_KEY,
                user=user,
                request=request,
                key_requirements={"translate_zh": "deepseek"},
            )
            key = gate_context.key_for_step("translate_zh")
            ai_input = {
                "module_id": MODULE_KEY,
                "task": "translate_zh",
                "messages": [
                    {"role": "system", "content": plain_chinese_instruction(label)},
                    {
                        "role": "user",
                        "content": json.dumps(original, ensure_ascii=False),
                    },
                ],
            }
            # Release the txn opened by the gate query before the long AI call.
            self.db.commit()
            translated = self._execute_provider(
                provider="deepseek",
                task_type="generate",
                key=key,
                gate_context=gate_context,
                payload=ai_input,
            )
            if isinstance(translated, dict):
                return str(
                    translated.get("content")
                    or translated.get("text")
                    or json.dumps(translated, ensure_ascii=False)
                )
            return str(translated) if translated is not None else None
        except Exception:  # noqa: BLE001 - translation is display-only
            self.db.rollback()
            return None

    def generate_marketing_copy(
        self,
        *,
        product_id: UUID,
        scope_context: KScopeContext,
        request: Request,
        user: User,
    ) -> KProductKnowledgeProduct:
        """On-demand: AI writes the channel-appropriate listing/page copy.

        Machine does the work, operator reviews: the copy is stored on the
        product but nothing is published; export still requires human approval.
        """
        product = self._require_product(product_id, scope_context)
        channel = (product.channel or "dtc").strip().lower()
        skill = copy_skill_context_for_channel(channel)
        gate_context = self.gate_resolver(
            self.db,
            module_id=MODULE_KEY,
            user=user,
            request=request,
            key_requirements={"marketing_copy_generation": "chatgpt"},
        )
        key = gate_context.key_for_step("marketing_copy_generation")
        ai_input = {
            "module_id": MODULE_KEY,
            "task": "marketing_copy_generation",
            "channel": channel,
            "instruction": marketing_copy_instruction(channel),
            "copy_skill": skill,
            "product": _product_snapshot(product),
        }
        # Release the read transaction before the long (~80s) AI call so the DB
        # does not drop the connection on idle-in-transaction timeout.
        self.db.commit()
        result = self._execute_provider(
            provider="chatgpt",
            task_type="generate",
            key=key,
            gate_context=gate_context,
            payload=ai_input,
        )
        zh = self._plain_chinese(result, "文案", user=user, request=request)
        product = self._require_product(product_id, scope_context)
        product.marketing_copy_json = result
        product.marketing_copy_zh = zh
        product.marketing_copy_skill_version = skill["version"]
        product.updated_by_user_id = _user_uuid(user)
        self._add_ai_event(
            product=product,
            execution=self._latest_execution(product),
            event_type="marketing_copy_generation",
            provider_key=key,
            ai_input=ai_input,
            result=result,
            user=user,
        )
        self.db.add(product)
        self.db.flush()
        return product

    def generate_image_brief(
        self,
        *,
        product_id: UUID,
        scope_context: KScopeContext,
        request: Request,
        user: User,
    ) -> KProductKnowledgeProduct:
        """On-demand: AI turns the finished copy into an image art-direction brief.

        Not a hard gate for export (only images are); this brief drives the
        follow-up 'go to I to make images' handoff.
        """
        product = self._require_product(product_id, scope_context)
        if not product.marketing_copy_json:
            raise KWorkflowExecutionError(
                "MARKETING_COPY_REQUIRED_FOR_IMAGE_BRIEF",
                "Generate the marketing copy before the image art-direction brief.",
                status_code=409,
            )
        channel = (product.channel or "dtc").strip().lower()
        skill = image_art_direction_skill_context()
        gate_context = self.gate_resolver(
            self.db,
            module_id=MODULE_KEY,
            user=user,
            request=request,
            key_requirements={"image_brief_generation": "chatgpt"},
        )
        key = gate_context.key_for_step("image_brief_generation")
        ai_input = {
            "module_id": MODULE_KEY,
            "task": "image_brief_generation",
            "channel": channel,
            "instruction": image_art_direction_instruction(),
            "art_direction_skill": skill,
            "product": _product_snapshot(product),
            "marketing_copy": product.marketing_copy_json,
        }
        # Release the read transaction before the long (~80s) AI call so the DB
        # does not drop the connection on idle-in-transaction timeout.
        self.db.commit()
        result = self._execute_provider(
            provider="chatgpt",
            task_type="generate",
            key=key,
            gate_context=gate_context,
            payload=ai_input,
        )
        zh = self._plain_chinese(result, "作图指令", user=user, request=request)
        product = self._require_product(product_id, scope_context)
        product.image_instruction_json = result
        product.image_instruction_zh = zh
        product.image_instruction_skill_version = skill["version"]
        product.updated_by_user_id = _user_uuid(user)
        self._add_ai_event(
            product=product,
            execution=self._latest_execution(product),
            event_type="image_brief_generation",
            provider_key=key,
            ai_input=ai_input,
            result=result,
            user=user,
        )
        self.db.add(product)
        self.db.flush()
        return product

    def _bind_image(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        asset: KProductKnowledgeMediaAsset,
    ) -> None:
        product.selected_image_path = (
            asset.object_key or asset.file_url_placeholder or str(asset.id)
        )
        source_type = _image_source_type(asset)
        metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
        product.image_asset_status = "bound"
        product.media_notes_json = {
            **(product.media_notes_json or {}),
            "bound_asset_id": str(asset.id),
            "image_source_type": source_type,
            "i_system_image_asset_id": _i_system_asset_id(asset),
            "variant_sku": asset.variant_sku,
            "bound_at": _now_iso(),
            "k_image_ai_generation_allowed": False,
            "k_image_review_allowed": False,
            "object_key": asset.object_key,
            "original_url": (
                f"/k/media/{asset.id}/file"
                if asset.object_key
                else asset.file_url_placeholder
            ),
            "preview_url": (
                f"/k/media/{asset.id}/preview"
                if asset.object_key
                else asset.file_url_placeholder
            ),
            "thumbnail_url": (
                f"/k/media/{asset.id}/thumbnail"
                if asset.object_key
                else asset.file_url_placeholder
            ),
        }
        execution.image_binding_json = {
            "status": "bound",
            "source_type": source_type,
            "asset_id": str(asset.id),
            "i_system_image_asset_id": _i_system_asset_id(asset),
            "variant_sku": asset.variant_sku,
            "object_key": asset.object_key,
            "file_url_placeholder": asset.file_url_placeholder,
            "original_url": (
                f"/k/media/{asset.id}/file"
                if asset.object_key
                else asset.file_url_placeholder
            ),
            "preview_url": (
                f"/k/media/{asset.id}/preview"
                if asset.object_key
                else asset.file_url_placeholder
            ),
            "thumbnail_url": (
                f"/k/media/{asset.id}/thumbnail"
                if asset.object_key
                else asset.file_url_placeholder
            ),
            "content_sha256": metadata.get("content_sha256"),
            "file_size": asset.file_size,
            "mime_type": asset.mime_type,
            "width": asset.width,
            "height": asset.height,
            "bound_at": _now_iso(),
        }
        self._append_trace(
            execution,
            "image_binding",
            "completed",
            output_summary=execution.image_binding_json,
        )

    def _mark_export_ready(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> None:
        execution.status = "ready_for_export"
        execution.current_step = "export_p_series"
        execution.error_report_json = None
        self._transition_state(
            product,
            execution,
            "EXPORT_READY",
            step="export_p_series",
            event="export_gate_unlocked",
            details={
                "risk_approved": self._risk_review_is_approved(execution),
                "keywords_finalized": bool(execution.final_keyword_set_json),
                "selling_points_generated": self._selling_points_generated(product),
                "image_bound": self._image_is_bound(product, execution),
            },
        )

    def _block_risk_review(
        self,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> None:
        execution.status = "blocked"
        execution.current_step = "risk_term_manual_review"
        execution.error_report_json = self._error_report(
            execution,
            code="RISK_REVIEW_REQUIRED",
            message="Manual risk keyword review is required before continuing.",
            step="risk_term_manual_review",
            details={"auto_approval_allowed": False},
        )
        self._append_trace(
            execution,
            "risk_term_manual_review",
            "blocked",
            error=execution.error_report_json,
        )
        self.db.add(execution)
        self.db.flush()

    def _transition_state(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        state: str,
        *,
        step: str,
        event: str = "transition",
        details: dict[str, Any] | None = None,
        allow_backward: bool = False,
    ) -> None:
        current = self.state_machine.current_state(execution, product)
        if not allow_backward and not self.state_machine.can_transition(current, state):
            raise KWorkflowExecutionError(
                "K_WORKFLOW_INVALID_TRANSITION",
                f"K workflow cannot transition from {current} to {state}.",
                status_code=409,
            )
        self._append_gate_log(
            execution,
            "workflow_state_machine_v2",
            "allowed",
            {
                "event": event,
                "from_state": current,
                "state": state,
                "step": step,
                "closed_loop": True,
                **(details or {}),
            },
        )

    def _require_workflow_execution(
        self,
        *,
        workflow_id: UUID,
        scope_context: KScopeContext,
    ) -> tuple[KProductKnowledgeProduct, KProductKnowledgeWorkflowExecution]:
        execution = self.db.get(KProductKnowledgeWorkflowExecution, workflow_id)
        if execution is None:
            raise KWorkflowExecutionError(
                "WORKFLOW_EXECUTION_NOT_FOUND",
                "K workflow execution was not found.",
                status_code=404,
            )
        product = self._require_product(execution.product_id, scope_context)
        return product, execution

    def _rerun_from_step(
        self,
        *,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        step: str,
        payload: ProductKnowledgeWorkflowStartRequest,
        scope_context: KScopeContext,
        request: Request,
        user: User,
    ) -> KProductKnowledgeWorkflowExecution:
        del scope_context
        order = _closed_loop_step_order(step)
        if order <= _closed_loop_step_order("product_ingestion"):
            self._validate_organization(product, KScopeContext(
                workspace_key=execution.workspace_key,
                business_context=execution.business_context,
                scope_mode=execution.scope_mode,
            ), execution)
            self._append_trace(execution, "product_ingestion", "completed")
            self._transition_state(
                product,
                execution,
                "PRODUCT_CREATED",
                step="product_ingestion",
                allow_backward=True,
            )

        gate_context = self._require_execution_gate(
            execution=execution,
            request=request,
            user=user,
            key_requirements=CLOSED_LOOP_AI_KEY_REQUIREMENTS,
        )
        if order <= _closed_loop_step_order("deepseek_enrichment"):
            self._run_deepseek_enrichment(
                product=product,
                execution=execution,
                gate_context=gate_context,
                user=user,
            )
            self._transition_state(
                product,
                execution,
                "AI_DEEPSEEK_ENRICHED",
                step="deepseek_enrichment",
                allow_backward=True,
            )

        if order <= _closed_loop_step_order("serp_keyword_fetch"):
            serp_result = self._fetch_serp_keywords(
                product=product,
                execution=execution,
                payload=payload,
                gate_context=gate_context,
                user=user,
            )
            self._transition_state(
                product,
                execution,
                "SERP_ANALYZED",
                step="serp_keyword_fetch",
                allow_backward=True,
            )
        else:
            serp_result = self._latest_serp_result(product, execution)

        if order <= _closed_loop_step_order("ai_filter_chatgpt"):
            chatgpt_result = self._run_chatgpt_filter(
                product=product,
                execution=execution,
                serp_result=serp_result,
                gate_context=gate_context,
                user=user,
            )
            self._transition_state(
                product,
                execution,
                "CHATGPT_FILTERED",
                step="ai_filter_chatgpt",
                allow_backward=True,
            )
        else:
            chatgpt_result = execution.chatgpt_filter_result_json
            if not chatgpt_result:
                raise KWorkflowExecutionError(
                    "CHATGPT_RESULT_REQUIRED_FOR_RETRY",
                    "ChatGPT result is required before retrying downstream steps.",
                    status_code=409,
                )

        if order <= _closed_loop_step_order("ai_filter_claude_opus"):
            claude_result = self._run_claude_filter(
                product=product,
                execution=execution,
                chatgpt_result=chatgpt_result,
                gate_context=gate_context,
                user=user,
            )
            self._transition_state(
                product,
                execution,
                "CLAUDE_FILTERED",
                step="ai_filter_claude_opus",
                allow_backward=True,
            )
        else:
            claude_result = execution.claude_filter_result_json
            if not claude_result:
                raise KWorkflowExecutionError(
                    "CLAUDE_RESULT_REQUIRED_FOR_RETRY",
                    "Claude result is required before retrying downstream steps.",
                    status_code=409,
                )

        if order <= _closed_loop_step_order("risk_term_manual_review"):
            self._create_manual_risk_review_block(
                product=product,
                execution=execution,
                claude_result=claude_result,
            )
            self._transition_state(
                product,
                execution,
                "RISK_PENDING_REVIEW",
                step="risk_term_manual_review",
                event="hard_gate_blocked",
                allow_backward=True,
            )
            return execution

        if not self._risk_review_is_approved(execution):
            self._block_risk_review(execution)
            return execution
        return self._continue_after_risk_review(product, execution, user)

    def _latest_serp_result(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> dict[str, Any]:
        run = self.db.scalar(
            select(KProductKnowledgeResearchRun)
            .where(
                KProductKnowledgeResearchRun.product_id == product.id,
                KProductKnowledgeResearchRun.run_type == "serp_keyword_fetch",
            )
            .order_by(KProductKnowledgeResearchRun.created_at.desc())
            .limit(1)
        )
        if run is None or not isinstance(run.serp_result_summary_json, dict):
            raise KWorkflowExecutionError(
                "SERP_RESULT_REQUIRED_FOR_RETRY",
                "SERP result is required before retrying downstream steps.",
                status_code=409,
            )
        summary = run.serp_result_summary_json
        return {
            "query": summary.get("query"),
            "keywords": _safe_string_list(summary.get("keywords")),
            "organic_results": _organic_results(summary.get("organic_results")),
            "competitors": _safe_string_list(summary.get("competitors")),
            "research_run_id": str(run.id),
            "provider": run.serp_provider,
        }

    def _clear_outputs_from_step(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
        step: str,
        *,
        user: User,
    ) -> None:
        order = _closed_loop_step_order(step)
        if order <= _closed_loop_step_order("deepseek_enrichment"):
            _rollback_deepseek_product_fields(product)
        if order <= _closed_loop_step_order("ai_filter_chatgpt"):
            execution.chatgpt_filter_result_json = None
        if order <= _closed_loop_step_order("ai_filter_claude_opus"):
            execution.claude_filter_result_json = None
            product.risk_keywords_json = None
        if order <= _closed_loop_step_order("risk_term_manual_review"):
            execution.risk_approval_log_json = None
        if order <= _closed_loop_step_order("keyword_optimization_ai"):
            execution.final_keyword_set_json = None
            product.secondary_keywords_json = None
            product.long_tail_keywords_json = None
        if order <= _closed_loop_step_order("unit_conversion_normalization"):
            execution.unit_conversion_json = None
        if step == "image_binding":
            execution.image_binding_json = None
            product.selected_image_path = None
            product.image_asset_status = None
        if order <= _closed_loop_step_order("export_p_series"):
            execution.export_payloads_json = None
        execution.current_step = step
        execution.updated_by_user_id = _user_uuid(user)
