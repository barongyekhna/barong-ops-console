"""K workflow engines: V1 gate engine + V2 orchestrator (one file by design).

导航索引(行号会漂移,按类名/方法名搜索):
  1. KWorkflowStateMachineV2       状态机定义 + 状态迁移合法性       (~L130)
  2. KWorkflowExecutionError       错误类型 + 错误报告构造            (~L240)
  3. KProductKnowledgeWorkflowEngine (V1)
     - start_pipeline / review_risk_terms / bind_image_asset
     - export_payloads(出口硬门: keywords+selling points+image+
       risk review+category 绑定, 见 _export_blockers)              (~L280-620)
     - provider 调用层 _run_deepseek_* / _fetch_serp_* /
       _run_chatgpt_filter / _run_claude_filter                     (~L780-1220)
     - _continue_after_risk_review / _optimize_keywords /
       _normalize_units / 图片绑定 helper                            (~L1220-2060)
  4. KWorkflowOrchestratorV2       V2 闭环编排(run/review/bind/export,
     含 marketing copy 门 + generate_marketing_copy)                (~L2300-EOF)

拆分计划: provider 调用层抽独立模块。因 feature/k-series-product-knowledge
分支(K21)尚有 100+ 未合并提交,拆分推迟到该分支合并后。(2026-07-11 批次3)
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from collections import Counter
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
from ....modules.notifications.service import create_notification
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
from .category_resolver import bind_google_category_id, category_is_bound
from .buyer_display import buyer_display_structured_specs
from .errors import KProductNotFoundError
from .evidence_guard import (
    TitleEvidenceConsistencyError,
    canonical_package_includes,
    enforce_package_evidence_consistency,
    enforce_title_evidence_consistency,
    project_approved_selling_points,
    reconcile_title_numeric_claims,
)
from .faq_research import (
    build_faq_research,
    is_faq_question_candidate,
    is_specification_paraphrase_question,
    sanitize_faq_research,
    structured_spec_number_tokens,
    validate_generated_faq,
)
from .info_overlay import (
    OverlayContractError,
    normalize_overlay_contract,
    resolve_structured_spec_text,
)
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
from .product_naming import sanitize_product_naming_output
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
from .spec_templates import effective_product_category, missing_required_for_product

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
        if (
            self._risk_review_is_approved(execution)
            and execution.final_keyword_set_json
            and self._selling_points_generated(product)
        ):
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
        # DeepSeek may repeat a supplier-private model code from raw_input_text.
        # Normalize the buyer-visible name before diffing, persistence, audit
        # event capture, or any downstream title/schema generation consumes it.
        try:
            provider_output = sanitize_product_naming_output(
                provider_output,
                structured_specs=product.structured_specs_json,
                package_includes=product.package_includes_json,
            )
        except TitleEvidenceConsistencyError as exc:
            raise KWorkflowExecutionError(
                "DEEPSEEK_PRODUCT_NAME_NUMERIC_UNSAFE",
                str(exc),
                status_code=409,
            ) from exc
        diff: dict[str, dict[str, Any]] = {}
        category_hint_before = product.category_hint
        _capture_ai_category_hint(product, provider_output)
        if product.category_hint != category_hint_before:
            diff["category_hint"] = {
                "before": category_hint_before,
                "after": product.category_hint,
            }
        for field in DEEPSEEK_ENRICHMENT_FIELDS:
            value = provider_output.get(field)
            if isinstance(value, str):
                value = value.strip()
                if field == "category_hint":
                    value = value[:255]
            if value in (None, ""):
                continue
            before = getattr(product, field, None)
            if before == value:
                continue
            original_before = diff.get(field, {}).get("before", before)
            diff[field] = {"before": original_before, "after": value}
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
        if not self._selling_points_generated(product):
            execution.status = "blocked"
            execution.current_step = "selling_points_review_manual"
            execution.error_report_json = self._error_report(
                execution,
                code="SELLING_POINTS_APPROVAL_REQUIRED",
                message="Approve evidence-backed selling points before export.",
                step="selling_points_review_manual",
            )
            self._append_trace(
                execution,
                "selling_points_review_manual",
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
            blockers.append("evidence-backed selling points not approved")
        if not self._image_is_bound(product, execution):
            blockers.append("manual or I-system image not bound")
        if execution.status not in {"ready_for_export", "exported"}:
            blockers.append(f"workflow status is {execution.status}")
        if not category_is_bound(product):
            channel = (product.channel or "dtc").strip().lower()
            blockers.append(f"category not bound for {channel} channel")
        if effective_product_category(product) is not None:
            try:
                with self.db.begin_nested():
                    missing_specs = missing_required_for_product(self.db, product)
            except Exception:  # noqa: BLE001 - unavailable gate must fail closed
                logger.exception(
                    "Category specification workflow gate failed product_id=%s",
                    product.id,
                )
                blockers.append(
                    "category specification template validation unavailable"
                )
            else:
                if missing_specs:
                    blockers.append(
                        "required category specifications missing: "
                        + ", ".join(missing_specs)
                    )
        return blockers

    def _risk_review_is_approved(
        self,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> bool:
        return bool((execution.risk_approval_log_json or {}).get("approved") is True)

    def _selling_points_generated(self, product: KProductKnowledgeProduct) -> bool:
        return bool(_approved_selling_points_snapshot(product))

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


def _rollback_deepseek_product_fields(
    db: Session, product: KProductKnowledgeProduct
) -> None:
    diff = (product.field_diff_json or {}).get("deepseek_enrichment")
    if isinstance(diff, dict):
        for field, change in diff.items():
            if not isinstance(change, dict):
                continue
            # Executions created before Google category ids became protected may
            # still carry this field in their diff. Restore only a valid old id.
            if field == "google_product_category":
                bind_google_category_id(db, product, change.get("before"))
                continue
            if field not in DEEPSEEK_ENRICHMENT_FIELDS:
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
        "structured_specs_json": product.structured_specs_json,
        "structured_specs_buyer_display": buyer_display_structured_specs(
            product.structured_specs_json,
            target_market=product.target_market or "US",
        ),
        "organization_name": product.organization_name,
    }


def _copy_evidence_product_snapshot(
    product: KProductKnowledgeProduct,
) -> dict[str, Any]:
    """Minimal copy input: identity plus facts, never legacy narrative claims."""

    package_includes = canonical_package_includes(
        getattr(product, "package_includes_json", None),
        product.structured_specs_json,
    )
    return {
        "id": str(product.id),
        "product_key": product.product_key,
        "sku": product.sku,
        "product_name_en": product.product_name_en,
        "product_type": product.product_type,
        "structured_specs_json": product.structured_specs_json,
        "structured_specs_buyer_display": buyer_display_structured_specs(
            product.structured_specs_json,
            target_market=product.target_market or "US",
        ),
        "package_includes": package_includes,
        "organization_name": product.organization_name,
    }


def _final_keywords_for_copy(
    execution: KProductKnowledgeWorkflowExecution | None,
) -> list[str]:
    """Project the post-risk-review keyword set into copy-generation order."""

    keyword_set = (
        execution.final_keyword_set_json
        if execution is not None
        and (execution.risk_approval_log_json or {}).get("approved") is True
        and isinstance(execution.final_keyword_set_json, dict)
        else {}
    )
    return _dedupe_strings(
        [
            *_safe_string_list(keyword_set.get("primary_keywords")),
            *_safe_string_list(keyword_set.get("secondary_keywords")),
            *_safe_string_list(keyword_set.get("longtail_keywords")),
        ]
    )


_DTC_H1_MAX_LENGTH = 70
_DTC_SEO_TITLE_MAX_LENGTH = 60
_DTC_META_DESCRIPTION_MAX_LENGTH = 160
_SEO_WORD = re.compile(r"[A-Za-z0-9]+(?:[./+'-][A-Za-z0-9]+)*|&")
_SEO_MINOR_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def _clean_seo_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _seo_words(value: Any) -> list[str]:
    return _SEO_WORD.findall(_clean_seo_text(value))


def _seo_word_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _heading_case(value: str) -> str:
    """Title-case ordinary keyword text without damaging technical notation."""

    output: list[str] = []
    for index, word in enumerate(value.split()):
        key = word.casefold().strip(".,;:–—|&")
        if word == "&":
            output.append(word)
        elif index and key in _SEO_MINOR_WORDS:
            output.append(key)
        elif word.isupper() or any(char.isupper() for char in word[1:]):
            output.append(word)
        else:
            output.append("-".join(part.capitalize() for part in word.split("-")))
    return " ".join(output)


def _phrase_is_projected_from_safe_h1(phrase: str, safe_h1: str) -> bool:
    """Allow keyword ordering only when every word already survived evidence gates."""

    phrase_counts = Counter(
        key for word in _seo_words(phrase) if (key := _seo_word_key(word))
    )
    source_counts = Counter(
        key for word in _seo_words(safe_h1) if (key := _seo_word_key(word))
    )
    meaningful = {
        key
        for key in phrase_counts
        if key not in _SEO_MINOR_WORDS and key not in {"product", "products"}
    }
    return (
        len(meaningful) >= 1
        and len(_seo_words(phrase)) <= 7
        and all(source_counts[key] >= count for key, count in phrase_counts.items())
    )


def _strip_site_brand_from_h1(value: str, site_brand: str) -> str:
    clean = _clean_seo_text(value)
    brand = _clean_seo_text(site_brand)
    if not brand:
        return clean
    escaped = re.escape(brand)
    clean = re.sub(
        rf"^\s*{escaped}\s*(?:\||[-–—:]\s*)?",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(
        rf"\s*(?:\||[-–—:])\s*{escaped}\s*$",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    return clean.strip()


def _primary_phrase_from_safe_h1(
    safe_h1: str,
    final_keywords: list[str],
) -> str:
    # Only the first, risk-reviewed keyword is the primary keyword. It may
    # reorder words that already survived the title evidence gate, but it must
    # never introduce a new claim from search data.
    primary = _clean_seo_text(final_keywords[0]) if final_keywords else ""
    if primary and _phrase_is_projected_from_safe_h1(primary, safe_h1):
        return _heading_case(primary)

    first_clause = re.split(r"\s*(?:\||[–—,:;])\s*", safe_h1, maxsplit=1)[0]
    words = [word for word in _seo_words(first_clause) if word != "&"]
    while words and words[0].casefold() in {"a", "an", "the"}:
        words.pop(0)
    keys = [_seo_word_key(word) for word in words]
    # The supplier-name fallback keeps a coherent product head and drops the
    # tail. Publishing the first five arbitrary nouns merely reformats keyword
    # salad without making it readable.
    kit_index = next((index for index, key in enumerate(keys) if key == "kit"), None)
    product_heads = {
        "bag",
        "bottle",
        "burner",
        "camera",
        "chair",
        "charger",
        "cookware",
        "cover",
        "holder",
        "kit",
        "lamp",
        "lantern",
        "light",
        "organizer",
        "pump",
        "rack",
        "set",
        "stove",
        "table",
        "tent",
        "tool",
    }
    head_index = next(
        (index for index, key in enumerate(keys) if key in product_heads),
        None,
    )
    terminal = kit_index if kit_index is not None else head_index
    if terminal is not None:
        words = words[: max(terminal + 1, min(2, len(words)))]
    elif len(words) > 4:
        words = words[:4]
    while words and words[-1].casefold() in _SEO_MINOR_WORDS:
        words.pop()
    return _heading_case(" ".join(words))


_SEO_COMPONENT_ALIASES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("kettle", ("tea kettle", "teakettle", "kettle"), "Kettle"),
    ("pot", ("cooking pot", "stockpot", "saucepan", "pot"), "Pot"),
    ("pan", ("frying pan", "skillet", "pan"), "Pan"),
    ("bowl", ("bowl",), "Bowl"),
    ("plate", ("plate",), "Plate"),
    ("cup", ("cup", "mug"), "Cup"),
    ("lid", ("lid",), "Lid"),
    ("spoon", ("spoon",), "Spoon"),
    ("fork", ("fork",), "Fork"),
    ("knife", ("knife", "knives"), "Knife"),
)


def _seo_alias_match(value: str, aliases: tuple[str, ...]) -> re.Match[str] | None:
    for alias in aliases:
        match = re.search(
            rf"(?<![a-z0-9]){re.escape(alias)}(?:s)?(?![a-z0-9])",
            value,
            flags=re.IGNORECASE,
        )
        if match is not None:
            return match
    return None


def _natural_component_detail(source: str, primary_phrase: str) -> str:
    """Project at most three already-evidence-gated components as a real list."""

    mentions: list[tuple[int, str]] = []
    for _component, aliases, display in _SEO_COMPONENT_ALIASES:
        match = _seo_alias_match(source, aliases)
        if match is None or _seo_alias_match(primary_phrase, aliases) is not None:
            continue
        mentions.append((match.start(), display))
    items = [display for _position, display in sorted(mentions)[:3]]
    if not items:
        return ""
    if len(items) == 1:
        detail = items[0]
    elif len(items) == 2:
        detail = " & ".join(items)
    else:
        detail = f"{', '.join(items[:-1])} & {items[-1]}"
    if re.search(r"\bset\b", source, re.IGNORECASE):
        detail += " Set"
    return detail


def _contiguous_phrase_span(source: str, phrase: str) -> tuple[int, int] | None:
    source_words = [
        (match, _seo_word_key(match.group(0)))
        for match in _SEO_WORD.finditer(source)
        if _seo_word_key(match.group(0))
    ]
    phrase_keys = [
        key for word in _seo_words(phrase) if (key := _seo_word_key(word))
    ]
    if not phrase_keys:
        return None
    for index in range(len(source_words) - len(phrase_keys) + 1):
        candidate = [
            key for _match, key in source_words[index : index + len(phrase_keys)]
        ]
        if candidate == phrase_keys:
            return (
                source_words[index][0].start(),
                source_words[index + len(phrase_keys) - 1][0].end(),
            )
    return None


def _detail_without_primary(source: str, span: tuple[int, int]) -> str:
    left = source[: span[0]].strip(" ,;:–—|-&")
    right = source[span[1] :].strip(" ,;:–—|-&")
    left = re.sub(r"^(?:a|an|the)(?:\s+|$)", "", left, flags=re.IGNORECASE)
    left = re.sub(
        r"\s+(?:and|or|for|of|with|to|by|in|on|from)$",
        "",
        left,
        flags=re.IGNORECASE,
    )
    detail = " ".join(part for part in (left, right) if part)
    return re.sub(r"\s+", " ", detail).strip(" ,;:–—|-&")


def _supplier_noun_tail(value: str) -> bool:
    return len(_seo_words(value)) >= 4 and not re.search(
        r"(?:&|\b(?:and|or|for|with|that|which|to)\b)",
        value,
        flags=re.IGNORECASE,
    )


def _readable_h1(
    safe_h1: str,
    *,
    final_keywords: list[str],
    site_brand: str,
) -> str:
    source = _strip_site_brand_from_h1(safe_h1, site_brand)
    source = re.sub(r"\s*(?:\||[–—])\s*", " – ", source).strip(" –")
    primary = _primary_phrase_from_safe_h1(source, final_keywords)
    if not primary:
        return source
    span = _contiguous_phrase_span(source, primary)
    component_detail = _natural_component_detail(source, primary)
    if span is None:
        # A risk-reviewed keyword may reorder safe source words. Do not remove
        # them as a bag and listify every leftover token: only the reviewed
        # package components form a safe, grammatical detail in that case.
        detail = component_detail
    else:
        left = source[: span[0]].strip(" ,;:\u2013\u2014|-&").casefold()
        right = source[span[1] :].strip(" ,;:\u2013\u2014|-&")
        if (
            left in {"", "a", "an", "the"}
            and re.match(r"^(?:for|with|in|on|of|to|from|by)\b", right, re.IGNORECASE)
            and re.search(r"(?:\s\u2013\s|,\s*)", right)
        ):
            # The primary phrase already leads a grammatical audience/use
            # phrase and an authored detail clause.  Preserve that sentence
            # shape instead of producing "Primary – For ... – Detail".
            return f"{primary} {right}"
        detail = _detail_without_primary(source, span)
        if _supplier_noun_tail(detail):
            detail = component_detail
    if not detail:
        return primary
    if detail[0].isalpha():
        detail = detail[0].upper() + detail[1:]
    return f"{primary} – {detail}"


def _truncate_heading(value: str, limit: int) -> str:
    clean = _clean_seo_text(value)
    if len(clean) <= limit:
        return clean
    clipped = clean[: limit + 1]
    if len(clipped) > limit and not clipped[-1].isspace():
        clipped = clipped.rsplit(" ", 1)[0]
    clipped = clipped[:limit].rstrip(" ,;:–—|-&")
    # If a hard boundary cuts a comma/dash detail clause, keep the last
    # complete clause instead of publishing fragments such as "with Nested".
    clause_boundaries = [
        clipped.rfind(separator)
        for separator in (", ", " – ")
        if separator in clipped
    ]
    if clause_boundaries:
        boundary = max(clause_boundaries)
        if boundary >= max(20, limit // 2):
            clipped = clipped[:boundary].rstrip(" ,;:–—|-&")
    # A boundary cut must not turn a complete audience/capacity phrase into
    # an unsupported fragment such as "for 2-3", nor leave an orphaned
    # preposition at the end of a heading.
    clipped = re.sub(
        r"\s+(?:for\s+)?\d+(?:\.\d+)?(?:\s*(?:-|–|to)\s*\d+(?:\.\d+)?)?\s*$",
        "",
        clipped,
        flags=re.IGNORECASE,
    ).rstrip(" ,;:–—|-&")
    words = clipped.split()
    while words and words[-1].casefold().strip(".,;:") in _SEO_MINOR_WORDS:
        words.pop()
    clipped = " ".join(words).rstrip(" ,;:–—|-&")
    return clipped or clean[:limit].rstrip()


def _truncate_meta_description(value: Any) -> str:
    clean = _clean_seo_text(value)
    if len(clean) <= _DTC_META_DESCRIPTION_MAX_LENGTH:
        return clean
    window = clean[:_DTC_META_DESCRIPTION_MAX_LENGTH]
    sentence_ends = [match.end() for match in re.finditer(r"[.!?](?:\s|$)", window)]
    if sentence_ends and sentence_ends[-1] >= 80:
        return window[: sentence_ends[-1]].strip()
    clipped = window.rsplit(" ", 1)[0].rstrip(" ,;:–—|-")
    if not clipped:
        return window.rstrip()
    return f"{clipped[: _DTC_META_DESCRIPTION_MAX_LENGTH - 1].rstrip()}."


def _finalize_dtc_seo(
    result: dict[str, Any],
    *,
    final_keywords: list[str],
    site_brand: str,
    structured_specs: dict[str, Any] | None,
    package_includes: Any = None,
) -> dict[str, Any]:
    """Close DTC title fallbacks into one evidence-safe publishing identity."""

    output = dict(result)
    raw_seo = output.get("seo")
    seo = dict(raw_seo) if isinstance(raw_seo, dict) else {}
    safe_h1 = reconcile_title_numeric_claims(
        seo.get("h1"),
        structured_specs,
        package_includes=package_includes,
    )
    h1 = _readable_h1(
        safe_h1,
        final_keywords=final_keywords,
        site_brand=site_brand,
    )
    h1 = reconcile_title_numeric_claims(
        h1,
        structured_specs,
        package_includes=package_includes,
    )
    h1 = _truncate_heading(h1, _DTC_H1_MAX_LENGTH)
    h1 = reconcile_title_numeric_claims(
        h1,
        structured_specs,
        package_includes=package_includes,
    )
    h1 = _truncate_heading(h1, _DTC_H1_MAX_LENGTH)

    primary_phrase = _primary_phrase_from_safe_h1(h1, final_keywords)
    phrase_limit = _DTC_SEO_TITLE_MAX_LENGTH - len(f" | {site_brand}")
    primary_phrase = _truncate_heading(primary_phrase, max(1, phrase_limit))
    primary_phrase = reconcile_title_numeric_claims(
        primary_phrase,
        structured_specs,
        package_includes=package_includes,
    )
    primary_phrase = _truncate_heading(primary_phrase, max(1, phrase_limit))
    title = f"{primary_phrase} | {site_brand}"
    title = reconcile_title_numeric_claims(
        title,
        structured_specs,
        package_includes=package_includes,
    )

    seo["h1"] = h1
    seo["title"] = title
    raw_meta = seo.get("meta_description")
    if not isinstance(raw_meta, str) or not raw_meta.strip():
        raw_meta = seo.get("description")
    if isinstance(raw_meta, str) and raw_meta.strip():
        seo["meta_description"] = _truncate_meta_description(raw_meta)
    output["seo"] = seo

    json_ld = output.get("json_ld")
    if isinstance(json_ld, dict) and isinstance(json_ld.get("data"), dict):
        projected_json_ld = dict(json_ld)
        data = dict(projected_json_ld["data"])
        # Product schema follows the same clean short identity as Yoast's
        # <title>, while Woo's visible product name continues to use the H1.
        data["name"] = title
        projected_json_ld["data"] = data
        output["json_ld"] = projected_json_ld

    output["seo_format"] = {
        "status": "normalized",
        "h1_max_length": _DTC_H1_MAX_LENGTH,
        "title_max_length": _DTC_SEO_TITLE_MAX_LENGTH,
        "meta_description_max_length": _DTC_META_DESCRIPTION_MAX_LENGTH,
        "schema_name_projected_from_short_title": (
            isinstance(output.get("json_ld"), dict)
            and isinstance(output["json_ld"].get("data"), dict)
        ),
    }
    return output


def _keyword_coverage_receipt(
    result: dict[str, Any],
    final_keywords: list[str],
    *,
    threshold: float = 0.60,
) -> dict[str, Any]:
    """Measure exact normalized phrase coverage on customer-facing copy only."""

    surfaces = [
        result.get("listing_copy"),
        result.get("a_plus_outline"),
        result.get("product_page_copy"),
        result.get("page_faq"),
        result.get("json_ld"),
        result.get("seo"),
    ]

    def flatten(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [text for nested in value.values() for text in flatten(nested)]
        if isinstance(value, list):
            return [text for nested in value for text in flatten(nested)]
        return [str(value)] if isinstance(value, str) else []

    corpus = " ".join(text for surface in surfaces for text in flatten(surface))
    corpus = re.sub(r"<[^>]+>", " ", corpus)
    corpus = re.sub(r"[^a-z0-9]+", " ", corpus.casefold()).strip()
    keywords = _dedupe_strings(_safe_string_list(final_keywords))
    covered: list[str] = []
    missing: list[str] = []
    for keyword in keywords:
        normalized = re.sub(r"[^a-z0-9]+", " ", keyword.casefold()).strip()
        if normalized and re.search(rf"(?:^|\s){re.escape(normalized)}(?:$|\s)", corpus):
            covered.append(keyword)
        else:
            missing.append(keyword)
    rate = (len(covered) / len(keywords)) if keywords else None
    warning = rate is not None and rate < threshold
    return {
        "status": "warning" if warning else "passed" if keywords else "not_applicable",
        "threshold": threshold,
        "rate": round(rate, 4) if rate is not None else None,
        "percent": round(rate * 100, 1) if rate is not None else None,
        "keyword_count": len(keywords),
        "covered_count": len(covered),
        "covered_keywords": covered,
        "missing_keywords": missing,
        "warning": warning,
    }


def _stamp_keyword_coverage(
    result: dict[str, Any], final_keywords: list[str]
) -> dict[str, Any]:
    output = dict(result)
    coverage = _keyword_coverage_receipt(output, final_keywords)
    output["coverage"] = coverage
    if coverage["warning"]:
        raw_warnings = output.get("warnings")
        warnings = list(raw_warnings) if isinstance(raw_warnings, list) else []
        warnings.append(
            {
                "code": "FINAL_KEYWORD_COVERAGE_LOW",
                "message": "Final keyword coverage is below 60%; review copy wording.",
                "coverage_rate": coverage["rate"],
            }
        )
        output["warnings"] = warnings
    return output


_IMAGE_BRIEF_ROLE_ALIASES = {
    "main": "main",
    "hero_main": "main",
    "主图": "main",
    "白底主图": "main",
    "proof_scene": "proof_scene",
    "proof-shot": "proof_scene",
    "proof_shot": "proof_scene",
    "scene": "proof_scene",
    "证据场景": "proof_scene",
    "场景图": "proof_scene",
    "dimension": "dimension",
    "尺寸图": "dimension",
    "feature_callout": "feature_callout",
    "卖点信息图": "feature_callout",
    "spec": "spec",
    "规格图": "spec",
    "accessory": "accessory",
    "配件图": "accessory",
    "开箱图": "accessory",
    "detail": "detail",
    "细节图": "detail",
}
_IMAGE_BRIEF_POINT_BOUND_ROLES = frozenset({"proof_scene", "accessory", "detail"})
_IMAGE_BRIEF_OVERLAY_ROLES = frozenset({"dimension", "feature_callout", "spec"})
_IMAGE_BRIEF_GALLERY_MINIMUM = 6
_IMAGE_BRIEF_GALLERY_ACCESSORY_EXEMPT_MINIMUM = 5
_IMAGE_BRIEF_DESCRIPTION_PROOF_SCENE_MINIMUM = 3
_VALID_SELLING_POINT_EVIDENCE_PREFIXES = ("spec:", "verified_feature:")


def _approved_selling_points_snapshot(
    product: KProductKnowledgeProduct,
) -> list[dict[str, Any]]:
    """Return only the human-approved authority used by downstream image work."""
    payload = getattr(product, "selling_points_approved_json", None)
    if (
        not isinstance(payload, dict)
        or str(payload.get("review_status") or "").strip().lower() != "approved"
    ):
        return []
    bullets = payload.get("bullets")
    if not isinstance(bullets, list):
        return []
    output: list[dict[str, Any]] = []
    for index, item in enumerate(bullets, start=1):
        if not isinstance(item, dict):
            continue
        text_value = str(item.get("text") or "").strip()
        if not text_value:
            continue
        normalized = dict(item)
        normalized["id"] = str(item.get("id") or f"sp-{index}")
        normalized["text"] = text_value
        evidence = str(normalized.get("evidence") or "").strip()
        if not (
            evidence == "operator_fact"
            or any(
                evidence.startswith(prefix) and evidence[len(prefix) :].strip()
                for prefix in _VALID_SELLING_POINT_EVIDENCE_PREFIXES
            )
        ):
            continue
        if str(normalized.get("verification_status") or "").lower() != "verified":
            continue
        evidence_snapshot = normalized.get("evidence_snapshot")
        evidence_digest = str(normalized.get("evidence_digest") or "").strip()
        if not isinstance(evidence_snapshot, dict) or evidence_digest != hashlib.sha256(
            json.dumps(
                evidence_snapshot,
                default=str,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest():
            continue
        normalized["verification_status"] = "verified"
        output.append(normalized)
    return output


def _image_brief_evidence_digest(
    product: KProductKnowledgeProduct,
    approved_points: list[dict[str, Any]] | None = None,
) -> str:
    points = (
        approved_points
        if approved_points is not None
        else _approved_selling_points_snapshot(product)
    )
    payload = {
        "selling_points_approved": points,
        "structured_specs_json": getattr(product, "structured_specs_json", None),
    }
    package_includes = canonical_package_includes(
        getattr(product, "package_includes_json", None),
        getattr(product, "structured_specs_json", None),
    )
    if package_includes:
        payload["package_includes"] = package_includes
    return _hash_json(payload)


def _image_brief_error(message: str) -> KWorkflowExecutionError:
    return KWorkflowExecutionError(
        "IMAGE_BRIEF_EVIDENCE_CONTRACT_INVALID",
        message,
        status_code=502,
    )


def _image_brief_gallery_error(
    issues: list[dict[str, Any]],
    *,
    accessory_required: bool,
) -> KWorkflowExecutionError:
    minimum = (
        _IMAGE_BRIEF_GALLERY_MINIMUM
        if accessory_required
        else _IMAGE_BRIEF_GALLERY_ACCESSORY_EXEMPT_MINIMUM
    )
    summary = "; ".join(str(issue.get("message") or "") for issue in issues)
    return KWorkflowExecutionError(
        "IMAGE_BRIEF_GALLERY_COMPOSITION_INVALID",
        f"Image brief composition is invalid: {summary}",
        status_code=502,
        error_report={
            "status": "failed",
            "reason": "gallery_composition_invalid",
            "code": "IMAGE_BRIEF_GALLERY_COMPOSITION_INVALID",
            "message": summary,
            "must_stop": False,
            "issues": issues,
            "accessory_required": accessory_required,
            "gallery_minimum": minimum,
            "description_proof_scene_minimum": (
                _IMAGE_BRIEF_DESCRIPTION_PROOF_SCENE_MINIMUM
            ),
            "timestamp": _now_iso(),
        },
    )


def _validate_image_brief_gallery_composition(
    result: dict[str, Any],
    *,
    accessory_required: bool,
    dimension_evidence_available: bool = True,
) -> dict[str, Any]:
    """Enforce gallery and description quotas as independent compositions.

    This is deliberately separate from the evidence-contract normalizer.  A
    provider may get one chance to rearrange a structurally safe brief, while
    malformed/unbound visual claims remain hard failures and are never admitted
    through the layout fail-safe.
    """

    raw_images = result.get("images")
    images = raw_images if isinstance(raw_images, list) else []
    gallery = [
        image
        for image in images
        if isinstance(image, dict)
        and str(image.get("placement") or "gallery").strip().lower() == "gallery"
    ]
    description = [
        image
        for image in images
        if isinstance(image, dict)
        and str(image.get("placement") or "gallery").strip().lower()
        == "description"
    ]
    role_counts: dict[str, int] = {}
    for image in gallery:
        role = str(image.get("role") or "").strip().lower()
        role_counts[role] = role_counts.get(role, 0) + 1

    issues: list[dict[str, Any]] = []

    def require_exactly_one(role: str) -> None:
        count = role_counts.get(role, 0)
        if count != 1:
            issues.append(
                {
                    "role": role,
                    "expected": 1,
                    "actual": count,
                    "message": f"gallery requires exactly one {role} image (found {count})",
                }
            )

    require_exactly_one("main")
    require_exactly_one("feature_callout")
    if dimension_evidence_available:
        require_exactly_one("dimension")
    else:
        issues.append(
            {
                "role": "dimension",
                "expected": 1,
                "actual": role_counts.get("dimension", 0),
                "message": (
                    "gallery dimension quota has no verified dimensions evidence; "
                    "do not fabricate a source_field or measurement"
                ),
            }
        )
    if accessory_required:
        require_exactly_one("accessory")
    proof_count = role_counts.get("proof_scene", 0)
    if proof_count < 2:
        issues.append(
            {
                "role": "proof_scene",
                "expected_minimum": 2,
                "actual": proof_count,
                "message": (
                    "gallery requires at least two proof_scene images "
                    f"(found {proof_count})"
                ),
            }
        )
    minimum = (
        _IMAGE_BRIEF_GALLERY_MINIMUM
        if accessory_required
        else _IMAGE_BRIEF_GALLERY_ACCESSORY_EXEMPT_MINIMUM
    )
    if len(gallery) < minimum:
        issues.append(
            {
                "role": "gallery_total",
                "expected_minimum": minimum,
                "actual": len(gallery),
                "message": (
                    f"gallery requires at least {minimum} images "
                    f"(found {len(gallery)}); description images do not count"
                ),
            }
        )
    description_proof_count = sum(
        1
        for image in description
        if str(image.get("role") or "").strip().lower() == "proof_scene"
    )
    if description_proof_count < _IMAGE_BRIEF_DESCRIPTION_PROOF_SCENE_MINIMUM:
        issues.append(
            {
                "role": "description_proof_scene",
                "expected_minimum": _IMAGE_BRIEF_DESCRIPTION_PROOF_SCENE_MINIMUM,
                "actual": description_proof_count,
                "message": (
                    "description requires at least "
                    f"{_IMAGE_BRIEF_DESCRIPTION_PROOF_SCENE_MINIMUM} separate "
                    "placement=description proof_scene images; they never count "
                    "toward the gallery quota"
                ),
            }
        )
    if issues:
        raise _image_brief_gallery_error(
            issues,
            accessory_required=accessory_required,
        )
    return result


def _bind_image_to_selling_point(
    image: dict[str, Any],
    approved_points: list[dict[str, Any]],
) -> dict[str, Any] | None:
    point_id = str(image.get("selling_point_id") or "").strip()
    if point_id:
        matched_id = next(
            (
                point
                for point in approved_points
                if str(point.get("id") or "").strip() == point_id
            ),
            None,
        )
        if matched_id is None:
            return None

        conflicts: list[str] = []
        raw_index = image.get("selling_point_index")
        if raw_index not in (None, ""):
            try:
                point_index = int(raw_index)
            except (TypeError, ValueError):
                conflicts.append("index_invalid")
            else:
                if not 1 <= point_index <= len(approved_points):
                    conflicts.append("index_out_of_range")
                elif approved_points[point_index - 1] is not matched_id:
                    conflicts.append("index_mismatch")

        point_text = str(image.get("selling_point_text") or "").strip()
        if point_text and point_text != str(matched_id.get("text") or "").strip():
            conflicts.append("text_mismatch")

        if conflicts:
            logger.debug(
                "Image brief selling-point metadata conflicts with exact id; "
                "binding by id",
                extra={
                    "selling_point_id": point_id,
                    "selling_point_index": raw_index,
                    "selling_point_binding_conflicts": conflicts,
                },
            )
        return matched_id

    matches: list[dict[str, Any]] = []
    raw_index = image.get("selling_point_index")
    try:
        point_index = int(raw_index) if raw_index not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if point_index is not None:
        if not 1 <= point_index <= len(approved_points):
            return None
        matches.append(approved_points[point_index - 1])
    point_text = str(image.get("selling_point_text") or "").strip()
    if point_text:
        matched_text = next(
            (
                point
                for point in approved_points
                if str(point.get("text") or "").strip() == point_text
            ),
            None,
        )
        if matched_text is None:
            return None
        matches.append(matched_text)
    if not matches:
        return None
    first_id = str(matches[0].get("id") or "")
    return (
        matches[0]
        if all(str(point.get("id") or "") == first_id for point in matches)
        else None
    )


def _normalize_evidence_driven_image_brief(
    result: Any,
    approved_points: list[dict[str, Any]],
    *,
    require_dimension: bool = False,
) -> dict[str, Any]:
    """Validate the AI plan before it becomes an executable image brief."""
    if not isinstance(result, dict):
        raise _image_brief_error("Image brief provider output must be a JSON object.")
    raw_images = result.get("images")
    if not isinstance(raw_images, list) or not raw_images:
        raise _image_brief_error("Image brief must include a non-empty images array.")
    images: list[dict[str, Any]] = []
    main_count = 0
    dimension_count = 0
    seen_positions: set[int] = set()
    approved_ids = {
        str(point.get("id") or ""): index
        for index, point in enumerate(approved_points, start=1)
    }
    for fallback_position, raw in enumerate(raw_images, start=1):
        if not isinstance(raw, dict):
            raise _image_brief_error("Every image brief item must be an object.")
        image = dict(raw)
        try:
            position = int(raw.get("position") or fallback_position)
        except (TypeError, ValueError) as exc:
            raise _image_brief_error("Image positions must be integers.") from exc
        if position < 1 or position in seen_positions:
            raise _image_brief_error("Image positions must be unique positive integers.")
        seen_positions.add(position)
        raw_role = str(raw.get("role") or "").strip().lower()
        role = _IMAGE_BRIEF_ROLE_ALIASES.get(raw_role)
        if role is None:
            raise _image_brief_error(
                f"Image position {position} has unsupported role: {raw_role or '<empty>'}."
            )
        image["position"] = position
        image["role"] = role
        if role == "main":
            main_count += 1
            if position != 1:
                raise _image_brief_error("The single white-background main must be position 1.")
            image["placement"] = "gallery"
            image["overlay"] = None
        elif role == "dimension":
            dimension_count += 1
            image["placement"] = "gallery"

        if role in _IMAGE_BRIEF_POINT_BOUND_ROLES:
            point = _bind_image_to_selling_point(image, approved_points)
            proof_intent = str(image.get("proof_intent") or "").strip()
            if point is None or not proof_intent:
                raise _image_brief_error(
                    f"Image position {position} ({role}) must bind one approved "
                    "selling point and state a visible proof_intent."
                )
            point_id = str(point.get("id") or "")
            image["selling_point_id"] = point_id
            image["selling_point_index"] = approved_ids[point_id]
            image["selling_point_text"] = str(point.get("text") or "")
            image["proof_intent"] = proof_intent
        elif role in _IMAGE_BRIEF_OVERLAY_ROLES:
            overlay = image.get("overlay")
            if not isinstance(overlay, dict):
                raise _image_brief_error(
                    f"Image position {position} ({role}) requires a structured overlay."
                )
            overlay_role = str(overlay.get("role") or "").strip().lower()
            if overlay_role != role:
                raise _image_brief_error(
                    f"Image position {position} role and overlay.role must match."
                )
            try:
                image["overlay"] = normalize_overlay_contract(overlay)
            except OverlayContractError as exc:
                raise _image_brief_error(
                    f"Image position {position} has an invalid structured overlay: {exc}"
                ) from exc
        images.append(image)
    if main_count != 1:
        raise _image_brief_error("Image brief must contain exactly one main image.")
    if require_dimension and dimension_count == 0:
        raise _image_brief_error(
            "Image brief must contain a dimension image when verified dimensions exist."
        )
    normalized = dict(result)
    normalized["images"] = images
    normalized["image_count"] = len(images)
    normalized["selling_points_digest"] = _hash_json(approved_points)
    normalized["evidence_contract"] = "selling-points-approved-v1"
    return normalized


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


def _capture_ai_category_hint(
    product: KProductKnowledgeProduct,
    provider_output: dict[str, Any],
) -> None:
    """Keep an AI-suggested taxonomy path without granting id-field access."""
    merged = _merge_provider_output(provider_output)
    for field in (
        "category_hint",
        "category_path_text",
        "merchant_category_hint",
        "google_product_category",
    ):
        value = merged.get(field)
        if not isinstance(value, str):
            continue
        hint = re.sub(r"\s+", " ", value).strip()
        if not hint or not re.search(r"[>›]", hint):
            continue
        # category_hint is VARCHAR(255); the unabridged provider output remains
        # available in the corresponding structured-output JSON audit record.
        product.category_hint = hint[:255]
        return


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


def _faq_question_clusters(research: Any) -> list[dict[str, Any]]:
    """Project FAQ research into deterministic, source-backed question clusters.

    The copy provider receives this compact contract instead of having to infer
    cluster membership from two loosely-related maps.  Source IDs and questions
    stay server-owned; the model is only allowed to author an answer.
    """

    if not isinstance(research, dict):
        return []
    raw_sources = research.get("sources")
    if not isinstance(raw_sources, list):
        return []
    sources = [
        source
        for source in raw_sources
        if isinstance(source, dict)
        and str(source.get("id") or "").strip()
        and str(source.get("question") or "").strip()
        and is_faq_question_candidate(source.get("question"))
        and not is_specification_paraphrase_question(source.get("question"))
    ]
    sources_by_id = {
        str(source.get("id")).strip(): source
        for source in sources
    }
    ordered_clusters: list[tuple[str, list[str]]] = []
    seen_clusters: set[str] = set()
    raw_clusters = research.get("clusters")
    if isinstance(raw_clusters, dict):
        for raw_cluster, raw_ids in raw_clusters.items():
            cluster = str(raw_cluster or "").strip()
            if not cluster or cluster in seen_clusters or not isinstance(raw_ids, list):
                continue
            source_ids = [
                str(source_id).strip()
                for source_id in raw_ids
                if str(source_id).strip() in sources_by_id
            ]
            if not source_ids:
                continue
            seen_clusters.add(cluster)
            ordered_clusters.append((cluster, source_ids))
    for source in sources:
        cluster = str(source.get("intent_cluster") or "buyer_concern").strip()
        if not cluster or cluster in seen_clusters:
            continue
        source_ids = [
            str(candidate.get("id")).strip()
            for candidate in sources
            if str(candidate.get("intent_cluster") or "buyer_concern").strip()
            == cluster
        ]
        if source_ids:
            seen_clusters.add(cluster)
            ordered_clusters.append((cluster, source_ids))

    output: list[dict[str, Any]] = []
    for cluster, source_ids in ordered_clusters:
        cluster_sources = []
        for source_id in source_ids:
            source = sources_by_id[source_id]
            cluster_sources.append(
                {
                    "id": source_id,
                    "question": str(source.get("question") or "").strip(),
                    "snippet": str(source.get("snippet") or "").strip(),
                    "source_type": str(source.get("source_type") or "").strip(),
                }
            )
        if cluster_sources:
            output.append(
                {
                    "intent_cluster": cluster,
                    "sources": cluster_sources,
                    "preferred_question": cluster_sources[0]["question"],
                    "preferred_evidence_refs": [cluster_sources[0]["id"]],
                }
            )
    return output


def _canonicalize_generated_faq(
    result: Any,
    clusters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keep only exact server-projected FAQ questions and provenance.

    The general FAQ validator intentionally supports evidence-bound paraphrases
    for non-generation callers.  The generation workflow has a stricter Round 5
    contract: providers may write answers, but questions, source IDs, and intent
    clusters remain server-owned.
    """

    output = dict(result) if isinstance(result, dict) else {}
    raw_items = output.get("page_faq")
    items = raw_items if isinstance(raw_items, list) else []
    canonical_by_question: dict[str, dict[str, Any]] = {}
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        question = str(cluster.get("preferred_question") or "").strip()
        intent_cluster = str(cluster.get("intent_cluster") or "").strip()
        raw_refs = cluster.get("preferred_evidence_refs")
        refs = (
            [str(ref).strip() for ref in raw_refs if str(ref).strip()]
            if isinstance(raw_refs, list)
            else []
        )
        if question and intent_cluster and refs:
            canonical_by_question[question] = {
                "question": question,
                "evidence_refs": refs,
                "intent_cluster": intent_cluster,
            }

    canonical_items: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        canonical = canonical_by_question.get(question)
        if canonical is None or question in seen_questions:
            continue
        seen_questions.add(question)
        canonical_items.append(
            {
                **canonical,
                "answer": item.get("answer"),
            }
        )
    output["page_faq"] = canonical_items
    return output


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

    def _research_faq_pain_points_fail_safe(
        self,
        *,
        product: KProductKnowledgeProduct,
        request: Request,
        user: User,
    ) -> dict[str, Any]:
        """Best-effort Serper PAA/forum/review research for real buyer FAQ.

        This stage deliberately degrades to an ineligible FAQ verdict when the
        key, provider, response, or persistence fails.  Copy generation and P
        publication continue; only low-confidence FAQ/schema are omitted.
        """

        query_seed = (
            product.primary_keyword
            or product.product_name_en
            or product.product_type
            or product.product_key
        )
        target_market = (product.target_market or "US").strip().upper()
        target_language = (product.canonical_language or "en").strip().lower()
        queries = [
            str(query_seed).strip(),
            f"{query_seed} problems forum",
            f"{query_seed} reviews complaints questions",
        ]
        try:
            gate_context = self.gate_resolver(
                self.db,
                module_id=MODULE_KEY,
                user=user,
                request=request,
                key_requirements={"faq_research": "serp"},
            )
            key = gate_context.key_for_step("faq_research")
            self.db.commit()
            responses = [
                self._execute_provider(
                    provider="serp",
                    task_type="search",
                    key=key,
                    gate_context=gate_context,
                    payload={
                        "module_id": MODULE_KEY,
                        "task": "faq_pain_point_research",
                        "query": query,
                        "main_keyword": str(query_seed),
                        "target_market": target_market,
                        "target_language": target_language,
                    },
                )
                for query in queries
            ]
            research = build_faq_research(responses, queries=queries)
            research["provider"] = key.name
            run = KProductKnowledgeResearchRun(
                id=uuid4(),
                product_id=product.id,
                run_type="faq_pain_point_research",
                status=(
                    "succeeded"
                    if research.get("status") == "completed"
                    else "needs_review"
                ),
                requested_by_user_id=_user_uuid(user) if user is not None else None,
                target_market=target_market,
                target_language=target_language,
                seed_keywords_json=queries,
                serp_provider=key.name,
                serp_result_summary_json=research,
                selected_keyword_ids_json=[
                    item.get("id")
                    for item in research.get("sources") or []
                    if isinstance(item, dict) and item.get("id")
                ],
                started_at=_now(),
                finished_at=_now(),
                created_by_user_id=_user_uuid(user) if user is not None else None,
                updated_by_user_id=_user_uuid(user) if user is not None else None,
            )
            self.db.add(run)
            self.db.flush()
            research["research_run_id"] = str(run.id)
            return research
        except Exception as exc:  # noqa: BLE001 - FAQ never blocks copy/P
            self.db.rollback()
            logger.warning(
                "FAQ pain-point research degraded product_id=%s error=%s",
                product.id,
                exc.__class__.__name__,
                exc_info=True,
            )
            return {
                "status": "failed",
                "quality_ready": False,
                "queries": queries,
                "sources": [],
                "clusters": {},
                "source_count": 0,
                "error_class": exc.__class__.__name__,
                "fail_safe": True,
            }

    def _validate_faq_with_single_rewrite(
        self,
        result: dict[str, Any],
        *,
        research: dict[str, Any],
        approved_points: list[dict[str, Any]],
        structured_specs: dict[str, Any] | None,
        package_includes: list[str],
        key: ModuleExecutionKey,
        gate_context: ModuleExecutionContext,
    ) -> dict[str, Any]:
        """Regenerate missing/invalid FAQ once from server-owned research clusters."""

        quality_ready = research.get("quality_ready") is True
        clusters = _faq_question_clusters(research) if quality_ready else []
        canonical_result = _canonicalize_generated_faq(result, clusters)
        validated = validate_generated_faq(
            canonical_result,
            research,
            approved_selling_points=approved_points,
            structured_specs=structured_specs,
            package_includes=package_includes,
        )
        quality = validated.get("faq_quality")
        dropped = quality.get("dropped") if isinstance(quality, dict) else []
        numeric_questions = {
            str(item.get("question") or "").strip()
            for item in dropped or []
            if isinstance(item, dict)
            and item.get("reason") == "answer_repeats_product_specification_number"
            and str(item.get("question") or "").strip()
        }
        accepted = [
            dict(item)
            for item in (validated.get("page_faq") or [])
            if isinstance(item, dict)
        ]
        target_count = min(3, len(clusters))
        eligible = isinstance(quality, dict) and quality.get("eligible_for_schema") is True
        if not quality_ready or target_count < 2 or (
            eligible and len(accepted) >= target_count
        ):
            return validated

        accepted_clusters = {
            str(item.get("intent_cluster") or "buyer_concern").strip()
            for item in accepted
        }
        accepted_questions = {
            str(item.get("question") or "").strip().casefold()
            for item in accepted
        }
        requested_count = max(
            target_count - len(accepted),
            2 - len(accepted_clusters),
            1 if not eligible else 0,
        )
        rewrite_items: list[dict[str, Any]] = []
        for cluster in clusters:
            intent_cluster = str(cluster.get("intent_cluster") or "").strip()
            question = str(cluster.get("preferred_question") or "").strip()
            refs = cluster.get("preferred_evidence_refs")
            evidence_refs = (
                [str(ref).strip() for ref in refs if str(ref).strip()]
                if isinstance(refs, list)
                else []
            )
            if (
                not intent_cluster
                or not question
                or not evidence_refs
                or intent_cluster in accepted_clusters
                or question.casefold() in accepted_questions
            ):
                continue
            rewrite_items.append(
                {
                    "question": question,
                    "answer": "",
                    "evidence_refs": evidence_refs,
                    "intent_cluster": intent_cluster,
                }
            )
            if len(rewrite_items) >= requested_count:
                break
        if not rewrite_items:
            return validated
        rewrite_audit: dict[str, Any] = {
            "attempted": True,
            "requested_count": len(rewrite_items),
            "target_count": target_count,
            "initial_accepted_count": len(accepted),
            "initial_dropped": list(dropped or []),
            "status": "failed",
        }
        try:
            rewritten = self._execute_provider(
                provider="chatgpt",
                task_type="generate",
                key=key,
                gate_context=gate_context,
                payload={
                    "module_id": MODULE_KEY,
                    "task": "faq_cluster_rewrite",
                    "instruction": (
                        "Write only the answer for every supplied canonical research "
                        "question. Copy question, evidence_refs, and intent_cluster "
                        "unchanged. Use the cited source snippets plus approved facts; "
                        "answer with practical advice, method, or tradeoffs. Never repeat "
                        "a product-specific number. Return only JSON with page_faq."
                    ),
                    "page_faq": rewrite_items,
                    "faq_question_clusters": clusters,
                    "selling_points_approved": approved_points,
                    "structured_specs_json": structured_specs or {},
                    "forbidden_product_spec_numbers": sorted(
                        {
                            *structured_spec_number_tokens(structured_specs),
                            *([str(len(package_includes))] if package_includes else []),
                        }
                    ),
                },
            )
            rewritten_items = (
                rewritten.get("page_faq") if isinstance(rewritten, dict) else None
            )
            if not isinstance(rewritten_items, list):
                raise ValueError("FAQ rewrite response did not contain page_faq")
            rewritten_answers = {
                str(item.get("question") or "").strip(): str(
                    item.get("answer") or ""
                ).strip()
                for item in rewritten_items
                if isinstance(item, dict)
                and str(item.get("question") or "").strip()
                in {
                    str(original.get("question") or "").strip()
                    for original in rewrite_items
                }
                and str(item.get("answer") or "").strip()
            }
            safe_rewrites: list[dict[str, Any]] = []
            for original in rewrite_items:
                question = str(original.get("question") or "").strip()
                rewritten_answer = rewritten_answers.get(question)
                # On an unknown/changed question, retain the original invalid
                # item so deterministic validation drops it. Never trust the
                # provider to rewrite refs, clusters, or the research question.
                merged = dict(original)
                if rewritten_answer:
                    merged["answer"] = rewritten_answer
                safe_rewrites.append(merged)
            safe_by_question = {
                str(item.get("question") or "").strip(): item
                for item in safe_rewrites
            }
            retry_input = dict(canonical_result)
            retry_input["page_faq"] = [*accepted, *safe_by_question.values()]
            validated = validate_generated_faq(
                retry_input,
                research,
                approved_selling_points=approved_points,
                structured_specs=structured_specs,
                package_includes=package_includes,
            )
            final_quality = validated.get("faq_quality") or {}
            final_count = int(final_quality.get("accepted_count") or 0)
            final_eligible = final_quality.get("eligible_for_schema") is True
            rewrite_audit.update(
                {
                    "status": (
                        "succeeded"
                        if final_eligible and final_count >= min(2, target_count)
                        else "partial"
                        if final_count > len(accepted)
                        else "discarded_after_retry"
                    ),
                    "accepted_after_retry": final_count,
                    "discarded_after_retry": max(
                        0,
                        len(rewrite_items) - (final_count - len(accepted)),
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - FAQ never blocks copy/P
            logger.warning(
                "FAQ research-cluster rewrite degraded error=%s",
                exc.__class__.__name__,
                exc_info=True,
            )
            rewrite_audit["error_class"] = exc.__class__.__name__
        final_quality = dict(validated.get("faq_quality") or {})
        final_quality["faq_cluster_rewrite"] = rewrite_audit
        if numeric_questions:
            # Compatibility receipt for Round 3: numeric FAQ still follows the
            # same single cluster rewrite, never a second provider attempt.
            final_quality["numeric_answer_rewrite"] = {
                "attempted": True,
                "requested_count": len(numeric_questions),
                "status": rewrite_audit["status"],
            }
        validated["faq_quality"] = final_quality
        return validated

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
        approved_points = _approved_selling_points_snapshot(product)
        if not approved_points:
            raise KWorkflowExecutionError(
                "SELLING_POINTS_APPROVAL_REQUIRED_FOR_COPY",
                "Approve at least one evidence-backed selling point before generating marketing copy.",
                status_code=409,
            )
        execution = self._latest_execution(product)
        final_keywords = _final_keywords_for_copy(execution)
        package_includes = canonical_package_includes(
            getattr(product, "package_includes_json", None),
            product.structured_specs_json,
        )
        evidence_digest = _image_brief_evidence_digest(product, approved_points)
        stored_faq_research = product.faq_research_json
        if channel == "dtc":
            # FAQ research is durable evidence, not disposable copy input.
            # Regeneration must reuse the exact reviewed question/source set;
            # only a product with no persisted research runs Serper first.
            faq_research = (
                dict(stored_faq_research)
                if isinstance(stored_faq_research, dict)
                and stored_faq_research
                else self._research_faq_pain_points_fail_safe(
                    product=product,
                    request=request,
                    user=user,
                )
            )
        else:
            faq_research = {
                "status": "not_applicable",
                "quality_ready": False,
                "sources": [],
                "source_count": 0,
            }
        # Persisted FAQ research predates the current candidate safety gate in
        # some products.  Sanitize once here so provider input, canonical
        # clusters, validation, audit input, and persistence all share the same
        # source IDs and rebuilt quality metadata.
        faq_research = sanitize_faq_research(faq_research)
        faq_question_clusters = (
            _faq_question_clusters(faq_research)
            if faq_research.get("quality_ready") is True
            else []
        )
        skill = copy_skill_context_for_channel(channel)
        gate_context = self.gate_resolver(
            self.db,
            module_id=MODULE_KEY,
            user=user,
            request=request,
            key_requirements={"marketing_copy_generation": "chatgpt"},
        )
        key = gate_context.key_for_step("marketing_copy_generation")
        from .brand_guard import (
            SITE_BRAND,
            normalized_brand_terms,
            sanitize_snapshot_for_generation,
        )

        ai_input = {
            "module_id": MODULE_KEY,
            "task": "marketing_copy_generation",
            "channel": channel,
            "instruction": marketing_copy_instruction(channel),
            "copy_skill": skill,
            # 品牌红线：快照先消毒（AI 看不到第三方品牌），黑名单显式下发
            "product": sanitize_snapshot_for_generation(
                _copy_evidence_product_snapshot(product), product
            ),
            "selling_points_approved": approved_points,
            # SEO wording only. The instruction explicitly prevents keywords
            # from becoming evidence for claims or concrete components.
            "final_keywords": final_keywords,
            "evidence_digest": evidence_digest,
            "faq_research": faq_research,
            # Server-projected cluster/source pairs make the allowed FAQ
            # questions explicit; the model authors answers, not provenance.
            "faq_question_clusters": faq_question_clusters,
            "site_brand": SITE_BRAND,
            "forbidden_brand_terms": normalized_brand_terms(product),
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
        if not isinstance(result, dict):
            raise KWorkflowExecutionError(
                "MARKETING_COPY_SCHEMA_INVALID",
                "Marketing copy provider output must be a JSON object.",
                status_code=502,
            )
        result = project_approved_selling_points(result, approved_points)
        try:
            result = enforce_package_evidence_consistency(
                result,
                package_includes=package_includes,
                structured_specs=product.structured_specs_json,
            )
        except TitleEvidenceConsistencyError as exc:
            raise KWorkflowExecutionError(
                "MARKETING_COPY_TITLE_NUMERIC_UNSAFE",
                str(exc),
                status_code=409,
            ) from exc
        if channel == "dtc":
            result = self._validate_faq_with_single_rewrite(
                result,
                research=faq_research,
                approved_points=approved_points,
                structured_specs=product.structured_specs_json,
                package_includes=package_includes,
                key=key,
                gate_context=gate_context,
            )
            try:
                result = enforce_title_evidence_consistency(
                    result,
                    # product_name_en is the only customer identity fallback.
                    # A keyword must never replace a degenerated product title.
                    product_name=product.product_name_en,
                    product_type=product.product_type,
                    category_name=(
                        product.category_path
                        or product.merchant_product_type
                        or product.category_hint
                    ),
                    site_brand=SITE_BRAND,
                    approved_selling_points={"bullets": approved_points},
                    structured_specs=product.structured_specs_json,
                    package_includes=package_includes,
                )
                # Evidence and numeric reconciliation run before wording changes.
                # The finalizer then closes normal and product-name fallback paths
                # into the same H1/title/meta contract and re-runs the shared
                # numeric helper as a last-mile publishing defense.
                result = _finalize_dtc_seo(
                    result,
                    final_keywords=final_keywords,
                    site_brand=SITE_BRAND,
                    structured_specs=product.structured_specs_json,
                    package_includes=package_includes,
                )
            except TitleEvidenceConsistencyError as exc:
                raise KWorkflowExecutionError(
                    "MARKETING_COPY_TITLE_DEGENERATE",
                    str(exc),
                    status_code=409,
                ) from exc
        result = _stamp_keyword_coverage(result, final_keywords)
        result["evidence_contract"] = "pdp-evidence-v1"
        result["evidence_digest"] = evidence_digest
        result["selling_points_digest"] = _hash_json(approved_points)
        zh = self._plain_chinese(result, "文案", user=user, request=request)
        product = self._require_product(product_id, scope_context)
        self.db.refresh(product)
        current_points = _approved_selling_points_snapshot(product)
        if _image_brief_evidence_digest(product, current_points) != evidence_digest:
            raise KWorkflowExecutionError(
                "MARKETING_COPY_EVIDENCE_CHANGED",
                "Approved selling points or specifications changed while copy was generated; regenerate from the current evidence.",
                status_code=409,
            )
        _capture_ai_category_hint(product, result)
        product.faq_research_json = faq_research
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
        approved_points = _approved_selling_points_snapshot(product)
        if not approved_points:
            raise KWorkflowExecutionError(
                "SELLING_POINTS_APPROVAL_REQUIRED_FOR_IMAGE_BRIEF",
                "Approve at least one evidence-backed selling point before generating the image brief.",
                status_code=409,
            )
        evidence_digest = _image_brief_evidence_digest(product, approved_points)
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
        from .brand_guard import (
            SITE_BRAND,
            normalized_brand_terms,
            sanitize_snapshot_for_generation,
        )

        ai_input = {
            "module_id": MODULE_KEY,
            "task": "image_brief_generation",
            "channel": channel,
            "instruction": image_art_direction_instruction(),
            "art_direction_skill": skill,
            "product": sanitize_snapshot_for_generation(
                _copy_evidence_product_snapshot(product), product
            ),
            # The approved set is the sole claim authority for image planning.
            # Marketing copy is intentionally not passed here: stale/unreviewed
            # prose must not become a visual product claim.
            "selling_points_approved": approved_points,
            "selling_points_digest": _hash_json(approved_points),
            "evidence_digest": evidence_digest,
            "site_brand": SITE_BRAND,
            "forbidden_brand_terms": normalized_brand_terms(product),
        }
        # Release the read transaction before the long (~80s) AI call so the DB
        # does not drop the connection on idle-in-transaction timeout.
        self.db.commit()
        provider_result = self._execute_provider(
            provider="chatgpt",
            task_type="generate",
            key=key,
            gate_context=gate_context,
            payload=ai_input,
        )
        structured_specs = (
            product.structured_specs_json
            if isinstance(product.structured_specs_json, dict)
            else {}
        )
        require_dimension = any(
            resolve_structured_spec_text(
                structured_specs,
                f"dimensions.{axis}",
                target_market=getattr(product, "target_market", None),
            )
            is not None
            for axis in ("length", "width", "height")
        )
        package_includes = canonical_package_includes(
            getattr(product, "package_includes_json", None),
            structured_specs,
        )
        # A reviewed multi-item package needs a dedicated gallery contents shot.
        # Empty/one-item packages are the explicit single-product exemption.
        accessory_required = len(package_includes) > 1
        result = _normalize_evidence_driven_image_brief(
            provider_result,
            approved_points,
        )
        try:
            _validate_image_brief_gallery_composition(
                result,
                accessory_required=accessory_required,
                dimension_evidence_available=require_dimension,
            )
            result["gallery_composition_validation"] = {
                "attempted_rearrangement": False,
                "status": "passed",
                "accessory_required": accessory_required,
                "dimension_evidence_available": require_dimension,
                "gallery_minimum": (
                    _IMAGE_BRIEF_GALLERY_MINIMUM
                    if accessory_required
                    else _IMAGE_BRIEF_GALLERY_ACCESSORY_EXEMPT_MINIMUM
                ),
                "description_proof_scene_minimum": (
                    _IMAGE_BRIEF_DESCRIPTION_PROOF_SCENE_MINIMUM
                ),
            }
        except KWorkflowExecutionError as first_error:
            if first_error.code != "IMAGE_BRIEF_GALLERY_COMPOSITION_INVALID":
                raise
            initial_issues = list(first_error.error_report.get("issues") or [])
            missing_dimension = any(
                issue.get("role") == "dimension" for issue in initial_issues
            )
            if require_dimension and missing_dimension:
                retry_task = "image_brief_generation_dimension_retry"
                correction_prefix = (
                    "The previous plan omitted the mandatory role=dimension image. "
                )
            else:
                retry_task = "image_brief_generation_gallery_retry"
                correction_prefix = (
                    "The previous plan violated the gallery or description image quota. "
                )
            accessory_rule = (
                "exactly one gallery accessory image"
                if accessory_required
                else "accessory may be omitted because the reviewed package has at most one item"
            )
            dimension_rule = (
                "exactly one gallery dimension image whose overlay resolves to the supplied verified dimensions"
                if require_dimension
                else (
                    "no fabricated dimension image/source_field/value because no verified "
                    "dimension evidence is available (the quota must fail safe for review)"
                )
            )
            retry_input = {
                **ai_input,
                "task": retry_task,
                "correction": (
                    correction_prefix
                    + "Return a corrected FULL brief (including description images) with "
                    "gallery containing exactly one main, exactly one feature_callout, "
                    f"{accessory_rule}, {dimension_rule}, at least two proof_scene "
                    "images, and the required gallery minimum. Also include at least three "
                    "separate placement=description proof_scene images in landscape "
                    "composition; "
                    "description images never count toward the gallery minimum. Preserve "
                    "all evidence bindings and structured overlays."
                ),
                "gallery_validation_issues": initial_issues,
                "previous_invalid_output": provider_result,
            }
            retry_result = self._execute_provider(
                provider="chatgpt",
                task_type="generate",
                key=key,
                gate_context=gate_context,
                payload=retry_input,
            )
            # Evidence/overlay failures remain fail-closed. Only a second valid
            # evidence contract with a bad image composition may fail open.
            result = _normalize_evidence_driven_image_brief(
                retry_result,
                approved_points,
            )
            remaining_issues: list[dict[str, Any]] = []
            try:
                _validate_image_brief_gallery_composition(
                    result,
                    accessory_required=accessory_required,
                    dimension_evidence_available=require_dimension,
                )
                layout_status = "succeeded"
            except KWorkflowExecutionError as second_error:
                if second_error.code != "IMAGE_BRIEF_GALLERY_COMPOSITION_INVALID":
                    raise
                layout_status = "failed_open"
                remaining_issues = list(
                    second_error.error_report.get("issues") or []
                )
            result["gallery_composition_validation"] = {
                "attempted_rearrangement": True,
                "status": layout_status,
                "accessory_required": accessory_required,
                "dimension_evidence_available": require_dimension,
                "gallery_minimum": (
                    _IMAGE_BRIEF_GALLERY_MINIMUM
                    if accessory_required
                    else _IMAGE_BRIEF_GALLERY_ACCESSORY_EXEMPT_MINIMUM
                ),
                "description_proof_scene_minimum": (
                    _IMAGE_BRIEF_DESCRIPTION_PROOF_SCENE_MINIMUM
                ),
                "initial_issues": initial_issues,
                "remaining_issues": remaining_issues,
            }
            if require_dimension and missing_dimension:
                dimension_count = sum(
                    1
                    for image in result.get("images", [])
                    if isinstance(image, dict)
                    and image.get("role") == "dimension"
                    and image.get("placement") == "gallery"
                )
                result["dimension_retry"] = {
                    "attempted": True,
                    "status": "succeeded" if dimension_count == 1 else "failed_open",
                }
            if layout_status == "failed_open":
                warnings = (
                    list(result.get("warnings"))
                    if isinstance(result.get("warnings"), list)
                    else []
                )
                warnings.append(
                    {
                        "code": "IMAGE_BRIEF_GALLERY_COMPOSITION_FAILED_OPEN",
                        "message": (
                            "Image brief composition remained invalid after one full-brief "
                            "rearrangement; fail-safe preserved the evidence-valid plan."
                        ),
                        "issues": remaining_issues,
                    }
                )
                result["warnings"] = warnings
                logger.error(
                    "image brief composition failed open product=%s issues=%s",
                    product.id,
                    remaining_issues,
                )
                try:
                    create_notification(
                        self.db,
                        event_type="k.image_brief.gallery_failed_open",
                        title=(
                            "作图指令图片布局配额重排后仍不合格："
                            f"{product.sku or product.product_key or product.id}"
                        ),
                        body="证据合同有效，已按 fail-safe 放行；请人工检查图位后再渲染。",
                        level="error",
                        source="k.image_brief",
                        product_id=product.id,
                        payload={
                            "issues": remaining_issues,
                            "accessory_required": accessory_required,
                            "dimension_evidence_available": require_dimension,
                            "gallery_minimum": (
                                _IMAGE_BRIEF_GALLERY_MINIMUM
                                if accessory_required
                                else _IMAGE_BRIEF_GALLERY_ACCESSORY_EXEMPT_MINIMUM
                            ),
                            "description_proof_scene_minimum": (
                                _IMAGE_BRIEF_DESCRIPTION_PROOF_SCENE_MINIMUM
                            ),
                        },
                    )
                except Exception:  # noqa: BLE001 - alerting must not defeat fail-safe
                    logger.exception(
                        "image brief composition fail-open notification failed product=%s",
                        product.id,
                    )
        result["evidence_digest"] = evidence_digest
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
        if not self._selling_points_generated(product):
            execution.status = "blocked"
            execution.current_step = "selling_points_review_manual"
            execution.error_report_json = self._error_report(
                execution,
                code="SELLING_POINTS_APPROVAL_REQUIRED",
                message="Approve evidence-backed selling points before export.",
                step="selling_points_review_manual",
            )
            self._append_trace(
                execution,
                "selling_points_review_manual",
                "blocked",
                error=execution.error_report_json,
            )
            return
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
            _rollback_deepseek_product_fields(self.db, product)
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
