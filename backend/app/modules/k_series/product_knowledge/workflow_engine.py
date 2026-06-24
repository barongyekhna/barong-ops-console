from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.organization import OrganizationRecord
from ....models.user import User
from ....services.module_execution_gate import (
    ModuleExecutionContext,
    ModuleExecutionGateError,
    ModuleExecutionKey,
    require_module_execution_ready,
)
from .constants import MODULE_KEY, TARGET_ORGANIZATION_NAME
from .errors import KProductNotFoundError
from .models import (
    KProductKnowledgeAIEvent,
    KProductKnowledgeKeyword,
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeResearchRun,
    KProductKnowledgeRiskTerm,
    KProductKnowledgeWorkflowExecution,
)
from .schemas import (
    ProductKnowledgeImageBindRequest,
    ProductKnowledgeRiskReviewRequest,
    ProductKnowledgeWorkflowExportRequest,
    ProductKnowledgeWorkflowReport,
    ProductKnowledgeWorkflowStartRequest,
)
from .scope_shim import KScopeContext, apply_scope_filters

IMAGE_SOURCE_MANUAL = "manual_upload_image"
IMAGE_SOURCE_I_SYSTEM = "i_system_asset"
BOUND_IMAGE_SOURCES = {IMAGE_SOURCE_MANUAL, IMAGE_SOURCE_I_SYSTEM}

WORKFLOW_STEPS = (
    "product_ingestion",
    "serp_keyword_fetch",
    "ai_filter_chatgpt",
    "ai_filter_claude_opus",
    "risk_term_review_manual",
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

IMPERIAL_TARGET_MARKETS = {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}
UNIT_CONVERSIONS = {
    "cm": ("inch", Decimal("0.3937007874")),
    "kg": ("lb", Decimal("2.2046226218")),
    "g": ("oz", Decimal("0.03527396195")),
}


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
        self.error_report = error_report or {
            "code": code,
            "message": message,
            "must_stop": True,
            "timestamp": _now_iso(),
        }
        super().__init__(message)


class KWorkflowProviderError(KWorkflowExecutionError):
    pass


ProviderClient = Callable[[ModuleExecutionKey, dict[str, Any]], dict[str, Any]]
GateResolver = Callable[..., ModuleExecutionContext]


def post_provider_json(
    key: ModuleExecutionKey,
    payload: dict[str, Any],
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = UrlRequest(
        key.url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            key.header_name: key.header_value,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise KWorkflowProviderError(
            "PROVIDER_HTTP_ERROR",
            f"Provider '{key.name}' returned HTTP {exc.code}.",
            status_code=502,
        ) from exc
    except URLError as exc:
        raise KWorkflowProviderError(
            "PROVIDER_REQUEST_FAILED",
            f"Provider '{key.name}' request failed.",
            status_code=502,
        ) from exc
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise KWorkflowProviderError(
            "PROVIDER_NON_JSON",
            f"Provider '{key.name}' returned non-JSON output.",
            status_code=502,
        ) from exc
    if not isinstance(parsed, dict):
        raise KWorkflowProviderError(
            "PROVIDER_UNSUPPORTED_SHAPE",
            f"Provider '{key.name}' returned an unsupported JSON shape.",
            status_code=502,
        )
    return parsed


class KProductKnowledgeWorkflowEngine:
    def __init__(
        self,
        db: Session,
        *,
        provider_client: ProviderClient | None = None,
        gate_resolver: GateResolver | None = None,
    ) -> None:
        self.db = db
        self.provider_client = provider_client or post_provider_json
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
        if execution.current_step != "risk_term_review_manual":
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
                    step="risk_term_review_manual",
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
                step="risk_term_review_manual",
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

        approved = not rejected_terms
        execution.risk_approval_log_json = {
            "approved": approved,
            "reviewed_at": reviewed_at,
            "reviewed_by_user_id": str(user.id),
            "decisions": decisions,
            "confirm_no_risk_terms": payload.confirm_no_risk_terms,
        }
        if not approved:
            execution.status = "blocked"
            execution.error_report_json = self._error_report(
                execution,
                code="RISK_TERM_REJECTED",
                message="One or more risk keywords were rejected by manual review.",
                step="risk_term_review_manual",
                details={"rejected_terms": rejected_terms},
            )
            self._append_trace(
                execution,
                "risk_term_review_manual",
                "blocked",
                output_summary=execution.risk_approval_log_json,
                error=execution.error_report_json,
            )
            self.db.add(execution)
            self.db.flush()
            return execution

        self._append_trace(
            execution,
            "risk_term_review_manual",
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
                "required_order": list(DUAL_AI_KEY_REQUIREMENTS),
            },
        )
        return context

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
                "seed_keywords": payload.seed_keywords,
            },
        )
        key = gate_context.key_for_step("serp_keyword_fetch")
        query = (
            payload.serp_query
            or product.product_name_en
            or product.primary_keyword
            or product.product_key
        )
        provider_output = self.provider_client(
            key,
            {
                "module_id": MODULE_KEY,
                "task": "serp_keyword_fetch",
                "product_id": str(product.id),
                "product_key": product.product_key,
                "query": query,
                "target_market": payload.target_market,
                "target_region": payload.target_region,
                "seed_keywords": payload.seed_keywords,
                "competitors": payload.competitors,
            },
        )
        keywords = _safe_string_list(
            provider_output.get("keywords")
            or provider_output.get("related_keywords")
            or provider_output.get("keyword_candidates")
        )
        organic_results = _organic_results(
            provider_output.get("organic_results")
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
        key = gate_context.key_for_step("ai_filter_chatgpt")
        ai_input = {
            "module_id": MODULE_KEY,
            "task": "ai_filter_chatgpt",
            "product": _product_snapshot(product),
            "serp_keywords": serp_result["keywords"],
            "competitors": serp_result["competitors"],
            "required_output": [
                "cleaned_keywords",
                "filtered_keywords",
                "rejected_keywords",
                "rationale",
            ],
        }
        provider_output = self.provider_client(key, ai_input)
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
        key = gate_context.key_for_step("ai_filter_claude_opus")
        ai_input = {
            "module_id": MODULE_KEY,
            "task": "ai_filter_claude_opus",
            "product": _product_snapshot(product),
            "chatgpt_filter_result": chatgpt_result,
            "required_output": [
                "final_keywords",
                "high_value_keywords",
                "low_value_keywords",
                "risk_keywords",
            ],
        }
        provider_output = self.provider_client(key, ai_input)
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
            step="risk_term_review_manual",
            details={
                "risk_keywords": claude_result["risk_keywords"],
                "auto_approval_allowed": False,
            },
        )
        self._append_trace(
            execution,
            "risk_term_review_manual",
            "blocked",
            output_summary={
                "manual_review_required": True,
                "risk_keyword_count": len(claude_result["risk_keywords"]),
            },
            error=execution.error_report_json,
        )
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
        product.primary_keyword = primary[0] if primary else None
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
        product.image_asset_status = "bound"
        product.media_notes_json = {
            **(product.media_notes_json or {}),
            "bound_asset_id": str(asset.id),
            "image_source_type": source_type,
            "i_system_image_asset_id": _i_system_asset_id(asset),
            "bound_at": _now_iso(),
            "k_image_ai_generation_allowed": False,
            "k_image_review_allowed": False,
        }
        execution.image_binding_json = {
            "status": "bound",
            "source_type": source_type,
            "asset_id": str(asset.id),
            "i_system_image_asset_id": _i_system_asset_id(asset),
            "object_key": asset.object_key,
            "file_url_placeholder": asset.file_url_placeholder,
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
        asset = self._i_system_asset_reference(product, i_system_asset_id)
        if asset is not None:
            return asset
        asset = KProductKnowledgeMediaAsset(
            id=uuid4(),
            product_id=product.id,
            asset_type="image",
            asset_role="main",
            status="available",
            review_status="i_system_managed",
            storage_provider="i_series",
            object_key=f"i-series/{i_system_asset_id}",
            source=IMAGE_SOURCE_I_SYSTEM,
            metadata_json={
                "source_type": IMAGE_SOURCE_I_SYSTEM,
                "i_system_image_asset_id": i_system_asset_id,
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
        image = execution.image_binding_json or {}
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
        if not self._image_is_bound(product, execution):
            blockers.append("manual or I-system image not bound")
        if execution.status not in {"ready_for_export", "exported"}:
            blockers.append(f"workflow status is {execution.status}")
        return blockers

    def _risk_review_is_approved(
        self,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> bool:
        return bool((execution.risk_approval_log_json or {}).get("approved") is True)

    def _i_system_asset_reference(
        self,
        product: KProductKnowledgeProduct,
        i_system_asset_id: str,
    ) -> KProductKnowledgeMediaAsset | None:
        return self.db.scalar(
            select(KProductKnowledgeMediaAsset)
            .where(
                KProductKnowledgeMediaAsset.product_id == product.id,
                KProductKnowledgeMediaAsset.source == IMAGE_SOURCE_I_SYSTEM,
                KProductKnowledgeMediaAsset.object_key == f"i-series/{i_system_asset_id}",
            )
            .order_by(KProductKnowledgeMediaAsset.updated_at.desc())
            .limit(1)
        )

    def _image_is_bound(
        self,
        product: KProductKnowledgeProduct,
        execution: KProductKnowledgeWorkflowExecution,
    ) -> bool:
        image = execution.image_binding_json or {}
        return (
            product.image_asset_status == "bound"
            and image.get("status") == "bound"
            and image.get("source_type") in BOUND_IMAGE_SOURCES
        )

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
                prompt_version="k-workflow-v1",
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
        self.db.add(execution)
        self.db.commit()
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


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe_strings([str(item).strip() for item in value if str(item).strip()])


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


def _normalize_chatgpt_result(provider_output: dict[str, Any]) -> dict[str, Any]:
    filtered = _safe_string_list(provider_output.get("filtered_keywords"))
    cleaned = _safe_string_list(provider_output.get("cleaned_keywords")) or filtered
    rejected = _safe_string_list(provider_output.get("rejected_keywords"))
    rationale = provider_output.get("rationale") or provider_output.get("reasoning") or ""
    return {
        "cleaned_keywords": cleaned,
        "filtered_keywords": filtered or cleaned,
        "rejected_keywords": rejected,
        "rationale": rationale,
    }


def _normalize_claude_result(provider_output: dict[str, Any]) -> dict[str, Any]:
    high_value = _safe_string_list(provider_output.get("high_value_keywords"))
    low_value = _safe_string_list(provider_output.get("low_value_keywords"))
    final = _safe_string_list(provider_output.get("final_keywords")) or _dedupe_strings(
        [*high_value, *low_value]
    )
    return {
        "final_keywords": final,
        "high_value_keywords": high_value,
        "low_value_keywords": low_value,
        "risk_keywords": _normalize_risk_keywords(provider_output.get("risk_keywords")),
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
