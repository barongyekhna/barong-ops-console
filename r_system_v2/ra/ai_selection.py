"""Real multi-AI product-selection pipeline for R-A."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.ra.ai_selection_mock import (
    _dict_value,
    _input_summary,
    _int_value,
    _load_candidate_contexts,
    _load_evaluations_by_candidate,
    _load_final_decisions,
    _number,
    _report_count,
    _skill_payload,
)
from r_system_v2.ra.competition import ensure_competition_snapshot
from r_system_v2.ra.profit_service import _json_bind
from r_system_v2.ra.providers import RAnalysisProviderBinding
from r_system_v2.ra.skill_loader import RASkillBundle, load_ra_skill_bundle


RA_AI_PIPELINE_VERSION = "ra_multi_ai_real_v1"
RA_AI_LAYERS = ("deepseek", "gpt", "opus")


class RAAISelectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    role: str
    service: str
    api_key: str
    base_url: str
    model: str


@dataclass(frozen=True)
class LayerDecision:
    layer: str
    model_role: str
    model_name: str
    score: int | None
    verdict: str
    reason: str
    risks: list[str]
    advantages: list[str]
    payload: dict[str, Any]
    in_tokens: int | None = None
    out_tokens: int | None = None
    cost_usd: Decimal | None = None


def run_ai_selection_for_run(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    channel: str = "amazon",
) -> dict[str, object]:
    candidates = _load_candidate_contexts(db, org_id=org_id, run_id=run_id)
    skill_bundle = load_ra_skill_bundle(channel)
    providers = _load_provider_configs(db, org_id=org_id)
    _clear_ai_outputs(db, org_id=org_id, run_id=run_id)
    db.commit()
    counts = _initial_ai_counts(len(candidates))

    for context in candidates:
        _evaluate_and_store_candidate(
            db,
            org_id=org_id,
            run_id=run_id,
            context=context,
            skill_bundle=skill_bundle,
            providers=providers,
            channel=channel,
            counts=counts,
        )

    _merge_run_counts(db, run_id=run_id, counts=counts)
    db.commit()
    return load_ai_selection_for_run(db, org_id=org_id, run_id=run_id)


def run_ai_selection_for_candidate(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    candidate_id: str,
    channel: str = "amazon",
) -> dict[str, object]:
    """Run the real AI chain for one profit-passed candidate without touching siblings."""
    normalized_candidate_id = str(candidate_id or "").strip()
    if not normalized_candidate_id:
        raise RAAISelectionError("缺少 R-A candidate_id，无法启动 AI 链。")
    candidates = [
        context
        for context in _load_candidate_contexts(db, org_id=org_id, run_id=run_id)
        if str(context.get("candidate_id") or "") == normalized_candidate_id
    ]
    if not candidates:
        raise RAAISelectionError("利润通过候选不存在或尚未满足 AI 输入条件。")

    skill_bundle = load_ra_skill_bundle(channel)
    providers = _load_provider_configs(db, org_id=org_id)
    _clear_ai_outputs_for_candidate(
        db,
        org_id=org_id,
        run_id=run_id,
        candidate_id=normalized_candidate_id,
    )
    db.commit()

    counts = _initial_ai_counts(len(candidates))
    for context in candidates:
        _evaluate_and_store_candidate(
            db,
            org_id=org_id,
            run_id=run_id,
            context=context,
            skill_bundle=skill_bundle,
            providers=providers,
            channel=channel,
            counts=counts,
        )

    _merge_run_counts(db, run_id=run_id, counts=counts)
    db.commit()
    summary = load_ai_selection_for_run(db, org_id=org_id, run_id=run_id)
    _merge_run_counts(db, run_id=run_id, counts=_dict_value(summary.get("counts")))
    db.commit()
    return summary


def load_ai_selection_for_run(
    db: Session,
    *,
    org_id: str,
    run_id: str,
) -> dict[str, object]:
    decisions = _load_final_decisions(db, org_id=org_id, run_id=run_id)
    evaluations = _load_evaluations_by_candidate(db, org_id=org_id, run_id=run_id)
    items: list[dict[str, object]] = []
    counts = {
        "ai_candidates": len(decisions),
        "ai_pass": 0,
        "ai_reject": 0,
        "ai_review": 0,
        "ai_evaluations": 0,
        "final_decisions": len(decisions),
        "reports": 0,
    }
    for decision in decisions:
        candidate_id = str(decision.get("candidate_id") or "")
        layer_items = evaluations.get(candidate_id, [])
        counts["ai_evaluations"] += len(layer_items)
        verdict = str(decision.get("verdict") or "review")
        if verdict == "pass":
            counts["ai_pass"] += 1
        elif verdict == "reject":
            counts["ai_reject"] += 1
        else:
            counts["ai_review"] += 1
        payload = _dict_value(decision.get("payload"))
        items.append(
            {
                "candidate_id": candidate_id,
                "asin": decision.get("asin"),
                "final_score": decision.get("final_score"),
                "verdict": verdict,
                "channel": decision.get("channel"),
                "barrier_type": decision.get("barrier_type"),
                "decision_reason": decision.get("decision_reason"),
                "layers": layer_items,
                "report_id": payload.get("report_id"),
                "ai_pipeline_version": payload.get("ai_pipeline_version"),
                "competition": payload.get("competition"),
                "created_at": _iso(decision.get("created_at")),
            }
        )
    counts["reports"] = _report_count(db, org_id=org_id, run_id=run_id)
    merged_counts = {**_load_run_counts(db, run_id=run_id), **counts}
    return {
        "run_id": run_id,
        "runtime_mode": "real_multi_ai",
        "mock": False,
        "ai_pipeline_version": RA_AI_PIPELINE_VERSION,
        "items": items,
        "counts": merged_counts,
    }


def load_ai_selection_by_candidate(
    db: Session,
    *,
    org_id: str,
    run_id: str,
) -> dict[str, dict[str, object]]:
    summary = load_ai_selection_for_run(db, org_id=org_id, run_id=run_id)
    output: dict[str, dict[str, object]] = {}
    for item in summary.get("items") or []:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        if candidate_id:
            output[candidate_id] = item
    return output


def _initial_ai_counts(candidate_count: int) -> dict[str, Any]:
    return {
        "ai_candidates": candidate_count,
        "ai_evaluations": 0,
        "ai_pass": 0,
        "ai_reject": 0,
        "ai_review": 0,
        "final_decisions": 0,
        "reports": 0,
        "real_ai_enabled": True,
        "ai_pipeline_version": RA_AI_PIPELINE_VERSION,
        "rainforest_snapshots": 0,
        "rainforest_credits_used": 0,
        "rainforest_cache_hits": 0,
    }


def _evaluate_and_store_candidate(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    context: dict[str, Any],
    skill_bundle: RASkillBundle,
    providers: dict[str, ProviderConfig],
    channel: str,
    counts: dict[str, Any],
) -> None:
    competition = ensure_competition_snapshot(db, org_id=org_id, context=context)
    context["competition"] = competition
    db.commit()
    counts["rainforest_snapshots"] += 1
    counts["rainforest_credits_used"] += int(competition.get("credits_used_this_call") or 0)
    if competition.get("cache_hit"):
        counts["rainforest_cache_hits"] += 1
    layers = _evaluate_real_layers(
        context,
        skill_bundle=skill_bundle,
        providers=providers,
        channel=channel,
    )
    for layer in layers:
        _insert_ai_evaluation(db, org_id=org_id, run_id=run_id, context=context, layer=layer)
        counts["ai_evaluations"] += 1
    final = _final_decision(context, layers, channel=channel, skill_bundle=skill_bundle)
    final["report_id"] = str(uuid4())
    _insert_final_decision(db, org_id=org_id, run_id=run_id, context=context, final=final)
    _insert_report(db, org_id=org_id, run_id=run_id, context=context, final=final, layers=layers)
    _update_candidate_status(
        db,
        candidate_id=str(context["candidate_id"]),
        verdict=str(final["verdict"]),
    )
    verdict_key = {
        "pass": "ai_pass",
        "reject": "ai_reject",
        "review": "ai_review",
    }.get(str(final["verdict"]), "ai_review")
    counts[verdict_key] += 1
    counts["final_decisions"] += 1
    counts["reports"] += 1
    db.commit()


def _evaluate_real_layers(
    context: dict[str, Any],
    *,
    skill_bundle: RASkillBundle,
    providers: dict[str, ProviderConfig],
    channel: str,
) -> list[LayerDecision]:
    deepseek = _call_layer(
        providers["deepseek"],
        layer="deepseek",
        context=context,
        skill_bundle=skill_bundle,
        channel=channel,
        previous_layers=[],
    )
    layers = [deepseek]
    if deepseek.verdict == "reject":
        return layers
    gpt = _call_layer(
        providers["gpt"],
        layer="gpt",
        context=context,
        skill_bundle=skill_bundle,
        channel=channel,
        previous_layers=layers,
    )
    layers.append(gpt)
    if gpt.verdict == "reject":
        return layers
    opus = _call_layer(
        providers["opus"],
        layer="opus",
        context=context,
        skill_bundle=skill_bundle,
        channel=channel,
        previous_layers=layers,
    )
    layers.append(opus)
    return layers


def _call_layer(
    provider: ProviderConfig,
    *,
    layer: str,
    context: dict[str, Any],
    skill_bundle: RASkillBundle,
    channel: str,
    previous_layers: list[LayerDecision],
) -> LayerDecision:
    request_payload = _layer_request_payload(
        layer=layer,
        context=context,
        skill_bundle=skill_bundle,
        channel=channel,
        previous_layers=previous_layers,
    )
    messages = [
        {
            "role": "system",
            "content": _system_prompt(layer=layer, skill_bundle=skill_bundle),
        },
        {
            "role": "user",
            "content": _json_dumps(request_payload),
        },
    ]
    try:
        response = _chat_completion(provider, messages=messages)
        output = _parse_model_json(response.get("content"))
    except RAAISelectionError as exc:
        return _error_layer_decision(
            layer=layer,
            context=context,
            skill_bundle=skill_bundle,
            provider=provider,
            request_payload=request_payload,
            error=str(exc),
        )
    decision = _normalize_layer_output(
        output,
        layer=layer,
        context=context,
        skill_bundle=skill_bundle,
        provider=provider,
        request_payload=request_payload,
        raw_response=response,
    )
    return decision


def _chat_completion(
    provider: ProviderConfig,
    *,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    last_error: str | None = None
    for spec in _chat_request_specs(provider, messages=messages):
        try:
            return _execute_chat_request(provider, spec=spec)
        except RAAISelectionError as exc:
            last_error = str(exc)
            if provider.role != "opus" or not _empty_content_error(last_error):
                raise
    raise RAAISelectionError(last_error or f"{provider.role} 返回内容为空。")


def _chat_request_specs(
    provider: ProviderConfig,
    *,
    messages: list[dict[str, str]],
) -> list[dict[str, Any]]:
    payload = {
        "model": provider.model,
        "messages": messages,
        "temperature": _float_env("RA_AI_TEMPERATURE", 0.15),
        "response_format": {"type": "json_object"},
    }
    if provider.role != "opus":
        return [{"endpoint": "/v1/chat/completions", "payload": payload, "label": "chat"}]
    system_text = "\n".join(
        message["content"]
        for message in messages
        if message.get("role") == "system" and message.get("content")
    )
    user_messages = [message for message in messages if message.get("role") != "system"]
    max_tokens = _bounded_int(os.getenv("RA_OPUS_MAX_TOKENS"), 1600, 512, 2800)
    return [
        {
            "endpoint": "/v1/messages",
            "label": "messages",
            "payload": {
                "model": provider.model,
                "system": system_text,
                "messages": user_messages,
                "temperature": _float_env("RA_AI_TEMPERATURE", 0.15),
                "max_tokens": max_tokens,
            },
        },
        {
            "endpoint": "/v1/chat/completions",
            "label": "chat_fallback",
            "payload": {
                "model": provider.model,
                "messages": messages,
                "temperature": _float_env("RA_AI_TEMPERATURE", 0.15),
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens,
            },
        },
    ]


def _execute_chat_request(
    provider: ProviderConfig,
    *,
    spec: dict[str, Any],
) -> dict[str, Any]:
    payload = _dict_value(spec.get("payload"))
    endpoint = str(spec.get("endpoint") or "/v1/chat/completions")
    body = _json_dumps(payload).encode("utf-8")
    request = Request(
        _provider_url(provider.base_url, endpoint),
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key}",
            "User-Agent": "barong-ra/1.0",
        },
    )
    try:
        with urlopen(request, timeout=_ai_timeout_seconds()) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RAAISelectionError(
            f"{provider.role} 调用失败：HTTP {exc.code} {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise RAAISelectionError(f"{provider.role} 调用失败：{exc}") from exc
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise RAAISelectionError(f"{provider.role} 返回内容不是 JSON。") from exc
    if not isinstance(parsed, dict):
        raise RAAISelectionError(f"{provider.role} 返回结构异常。")
    content = _response_content(parsed)
    if not isinstance(content, str) or not content.strip():
        raise RAAISelectionError(
            _empty_response_message(provider=provider, parsed=parsed, spec=spec)
        )
    if provider.role == "opus":
        parsed_output = _try_parse_model_json(content)
        if not _structured_model_output(parsed_output):
            raise RAAISelectionError(
                _invalid_json_response_message(
                    provider=provider,
                    content=content,
                    parsed=parsed,
                    spec=spec,
                )
            )
    usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
    return {
        "content": content,
        "raw": parsed,
        "usage": usage,
        "request_endpoint": endpoint,
        "request_label": spec.get("label"),
        "prompt_tokens": _int_value(usage.get("prompt_tokens") or usage.get("input_tokens")),
        "completion_tokens": _int_value(
            usage.get("completion_tokens") or usage.get("output_tokens")
        ),
    }


def _layer_request_payload(
    *,
    layer: str,
    context: dict[str, Any],
    skill_bundle: RASkillBundle,
    channel: str,
    previous_layers: list[LayerDecision],
) -> dict[str, Any]:
    if layer == "opus":
        return _opus_layer_request_payload(
            context=context,
            skill_bundle=skill_bundle,
            channel=channel,
            previous_layers=previous_layers,
        )
    return {
        "task": f"R-A {layer} product selection review",
        "channel": channel,
        "layer": layer,
        "required_json_schema": {
            "score": "0-100 integer",
            "verdict": "pass|reject|review",
            "reason": "short Chinese reason",
            "advantages": ["Chinese bullet"],
            "risks": ["Chinese bullet"],
            "barrier_type": "none|profit|demand|competition|supplier|listing|compliance|manual_review",
            "channel_guess": "amazon|dtc_seo|dtc_ad|both",
        },
        "gating_rule": _layer_gating_rule(layer),
        "skill": _skill_payload(skill_bundle),
        "skill_text": skill_bundle.prompt_text,
        "product": _model_input_summary(context),
        "raw_product": _model_product_payload(context),
        "profit": _dict_value(context.get("profit")),
        "supplier": _dict_value(context.get("supplier")),
        "competition": _competition_payload(context),
        "previous_layers": [layer_decision.payload.get("model_output") for layer_decision in previous_layers],
    }


def _opus_layer_request_payload(
    *,
    context: dict[str, Any],
    skill_bundle: RASkillBundle,
    channel: str,
    previous_layers: list[LayerDecision],
) -> dict[str, Any]:
    return {
        "task": "R-A opus final product selection review",
        "channel": channel,
        "layer": "opus",
        "required_json_schema": {
            "score": "0-100 integer",
            "verdict": "pass|reject|review",
            "reason": "short Chinese reason, <= 120 Chinese chars",
            "advantages": ["Chinese bullet, <= 40 chars each"],
            "risks": ["Chinese bullet, <= 40 chars each"],
            "barrier_type": "none|profit|demand|competition|supplier|listing|compliance|manual_review",
            "channel_guess": "amazon|dtc_seo|dtc_ad|both",
        },
        "gating_rule": _layer_gating_rule("opus"),
        "instruction": (
            "只做最终结论，不展开推理过程。必须只输出一个 JSON 对象。"
            "如果 Rainforest/销量/供应商数据无效或冲突，优先 review，不要强行通过或淘汰。"
        ),
        "skill": _skill_payload(skill_bundle),
        "skill_rules_summary": _opus_skill_summary(skill_bundle),
        "product": _model_input_summary(context),
        "profit": _compact_value(_dict_value(context.get("profit")), max_chars=2200),
        "supplier": _compact_value(_dict_value(context.get("supplier")), max_chars=2200),
        "competition": _competition_payload(context),
        "previous_layers": [
            _compact_value(layer_decision.payload.get("model_output"), max_chars=1400)
            for layer_decision in previous_layers
        ],
    }


def _model_input_summary(context: dict[str, Any]) -> dict[str, Any]:
    product = _dict_value(context.get("product"))
    features = _dict_value(product.get("features"))
    summary = _input_summary(context)
    summary.pop("seller_count", None)
    summary["monthly_sales"] = (
        _int_value(features.get("monthly_sales_value"))
        or _int_value(features.get("monthly_sales_estimate"))
        or _int_value(features.get("monthly_sales"))
    )
    summary["monthly_sales_source"] = (
        features.get("monthly_sales_value_source")
        or features.get("monthly_sales_source")
        or features.get("monthly_sales_estimate_source")
    )
    summary["monthly_sales_confidence"] = features.get("monthly_sales_confidence")
    summary["monthly_sales_data_conflict"] = bool(features.get("monthly_sales_data_conflict"))
    summary["raw_keepa_monthly_sales"] = _int_value(
        features.get("monthly_sales_raw") or features.get("monthly_sales")
    )
    competition = _competition_payload(context)
    summary["market_seller_count_est"] = competition.get("market_seller_count_est")
    summary["market_brand_count_est"] = competition.get("market_brand_count_est")
    summary["competition_data_valid"] = competition.get("competition_data_valid")
    return summary


def _model_product_payload(context: dict[str, Any]) -> dict[str, Any]:
    product = dict(_dict_value(context.get("product")))
    product.pop("seller_count", None)
    features = dict(_dict_value(product.get("features")))
    product["features"] = {
        key: value
        for key, value in features.items()
        if key
        in {
            "monthly_sales",
            "monthly_sales_raw",
            "monthly_sales_value",
            "monthly_sales_value_source",
            "monthly_sales_source",
            "monthly_sales_confidence",
            "monthly_sales_data_conflict",
            "monthly_sales_estimate",
            "monthly_sales_estimate_min",
            "monthly_sales_estimate_max",
            "monthly_sales_estimate_source",
            "fba_fee_usd",
            "amazon_pack_count",
            "amazon_pack_label",
            "subcategory_name",
            "subcategory_rank",
            "parent_category_name",
            "parent_category_rank",
        }
    }
    return product


def _opus_skill_summary(skill_bundle: RASkillBundle) -> str:
    text_value = re.sub(r"\s+", " ", skill_bundle.prompt_text or "").strip()
    if len(text_value) <= 3600:
        return text_value
    return text_value[:1800] + " ... " + text_value[-1400:]


def _compact_value(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if len(_json_dumps(compact)) >= max_chars:
                break
            if key in {"raw", "raw_response", "request", "raw_excerpt"}:
                continue
            compact[str(key)] = _compact_value(item, max_chars=max(200, max_chars // 3))
        return compact
    if isinstance(value, list):
        return [_compact_value(item, max_chars=max(200, max_chars // 4)) for item in value[:6]]
    if isinstance(value, str):
        return value[:max_chars]
    return value


def _error_layer_decision(
    *,
    layer: str,
    context: dict[str, Any],
    skill_bundle: RASkillBundle,
    provider: ProviderConfig,
    request_payload: dict[str, Any],
    error: str,
) -> LayerDecision:
    reason = f"{layer} 调用失败，已转人工复核：{error[:180]}"
    output = {
        "score": 50,
        "verdict": "review",
        "reason": reason,
        "advantages": [],
        "risks": [error[:240]],
        "barrier_type": "manual_review",
        "channel_guess": "amazon",
    }
    return _normalize_layer_output(
        output,
        layer=layer,
        context=context,
        skill_bundle=skill_bundle,
        provider=provider,
        request_payload=request_payload,
        raw_response={
            "content": _json_dumps(output),
            "usage": {},
            "prompt_tokens": None,
            "completion_tokens": None,
            "error": error,
        },
    )


def _system_prompt(*, layer: str, skill_bundle: RASkillBundle) -> str:
    return (
        "你是 R-A 选品链的结构化审核模型。必须严格遵守用户提供的 R 系列 skill。"
        "只输出一个 JSON 对象，不要输出 Markdown。"
        "不要跳过层级，不要编造缺失数据；缺失就写入 risks。"
        "R-A 只做选品漏斗判断，不计算利润公式，不改写 R-W 数据。"
        f"当前层级：{layer}。skill_version={skill_bundle.version}。"
    )


def _layer_gating_rule(layer: str) -> str:
    if layer == "deepseek":
        return (
            "第一层负责便宜快速量化：需求、利润通过事实、评论墙、品牌集中度、"
            "新卖家机会。score >= DEEPSEEK_PASS_SCORE 才进入 GPT；review 可进入下一层。"
        )
    if layer == "gpt":
        return (
            "第二层负责复核 listing、供应商匹配、竞争解释和需求真实性。"
            "score >= GPT_PASS_SCORE 且没有强硬风险才进入 Opus。"
        )
    return (
        "第三层从小卖家冷启动视角做最终判断。只允许对前两层放行产品做 keep/review/reject。"
    )


def _normalize_layer_output(
    output: dict[str, Any],
    *,
    layer: str,
    context: dict[str, Any],
    skill_bundle: RASkillBundle,
    provider: ProviderConfig,
    request_payload: dict[str, Any],
    raw_response: dict[str, Any],
) -> LayerDecision:
    score = _bounded_score(output.get("score"))
    raw_verdict = str(output.get("verdict") or "").strip().lower()
    verdict = _valid_verdict(raw_verdict)
    threshold = _layer_pass_threshold(layer)
    if verdict == "pass" and score < threshold:
        verdict = "review" if score >= max(45, threshold - 12) else "reject"
    if verdict == "review" and score < 45:
        verdict = "reject"
    reason = str(output.get("reason") or "").strip()
    if not reason:
        reason = f"{layer} 已完成结构化审核。"
    advantages = _string_list(output.get("advantages"))
    risks = _string_list(output.get("risks"))
    payload = {
        "mock": False,
        "ai_pipeline_version": RA_AI_PIPELINE_VERSION,
        "skill_version": skill_bundle.version,
        "skill_hash": skill_bundle.combined_hash,
        "skill": _skill_payload(skill_bundle),
        "asin": context.get("asin"),
        "score": score,
        "verdict": verdict,
        "reason": reason,
        "advantages": advantages,
        "risks": risks,
        "barrier_type": output.get("barrier_type"),
        "channel_guess": output.get("channel_guess"),
        "input_summary": _model_input_summary(context),
        "competition": _competition_payload(context),
        "provider": {
            "service": provider.service,
            "role": provider.role,
            "model": provider.model,
            "base_url": _redacted_base_url(provider.base_url),
        },
        "request": _audit_request_payload(request_payload),
        "model_output": output,
        "raw_usage": raw_response.get("usage") or {},
    }
    if raw_response.get("error"):
        payload["provider_error"] = raw_response.get("error")
    return LayerDecision(
        layer=layer,
        model_role=provider.role,
        model_name=provider.model,
        score=score,
        verdict=verdict,
        reason=reason,
        risks=risks,
        advantages=advantages,
        payload=payload,
        in_tokens=raw_response.get("prompt_tokens") or None,
        out_tokens=raw_response.get("completion_tokens") or None,
        cost_usd=_estimated_cost(provider, raw_response.get("usage") or {}),
    )


def _final_decision(
    context: dict[str, Any],
    layers: list[LayerDecision],
    *,
    channel: str,
    skill_bundle: RASkillBundle,
) -> dict[str, Any]:
    scores = [layer.score for layer in layers if layer.score is not None]
    average_score = round(sum(scores) / max(1, len(scores))) if scores else 0
    completed_layers = {layer.layer for layer in layers}
    hard_reasons: list[str] = []
    if "gpt" not in completed_layers:
        hard_reasons.append("DeepSeek 第一层未放行，未进入 GPT/Opus。")
    elif "opus" not in completed_layers:
        hard_reasons.append("GPT 第二层未放行，未进入 Opus。")
    if any(layer.verdict == "reject" for layer in layers):
        hard_reasons.append("至少一层 AI 给出拒绝。")
    opus = next((layer for layer in layers if layer.layer == "opus"), None)
    if hard_reasons:
        verdict = "reject"
        final_score = min(average_score, 59)
        barrier_type = _first_barrier(layers) or "ai_risk"
    elif opus is not None and opus.verdict == "pass" and (opus.score or 0) >= _layer_pass_threshold("opus"):
        verdict = "pass"
        final_score = opus.score or average_score
        barrier_type = "none"
    else:
        verdict = "review"
        final_score = average_score
        barrier_type = _first_barrier(layers) or "manual_review"

    leading_advantages = _dedupe_text(
        advantage
        for layer in layers
        for advantage in layer.advantages
    )[:4]
    leading_risks = _dedupe_text(risk for layer in layers for risk in layer.risks)[:4]
    if verdict == "pass":
        reason = "通过真实三层 AI 评审：利润、需求、竞争和供应商结构达到进入下一步选品链的最低线。"
    elif verdict == "reject":
        reason = "真实三层 AI 评审淘汰：" + "；".join(hard_reasons or leading_risks or ["核心指标不足"])
    else:
        reason = "进入人工复核：部分指标可用，但仍存在需要人工确认的竞争、供应商或需求风险。"

    return {
        "final_score": _bounded_score(final_score),
        "verdict": verdict,
        "channel": channel,
        "barrier_type": barrier_type,
        "decision_reason": reason,
        "advantages": leading_advantages,
        "risks": leading_risks,
        "layer_scores": {layer.layer: layer.score for layer in layers},
        "layer_verdicts": {layer.layer: layer.verdict for layer in layers},
        "ai_pipeline_version": RA_AI_PIPELINE_VERSION,
        "skill_version": skill_bundle.version,
        "skill_hash": skill_bundle.combined_hash,
        "skill": _skill_payload(skill_bundle),
        "competition": _competition_payload(context),
        "created_at": datetime.now(UTC).isoformat(),
    }


def _insert_ai_evaluation(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    context: dict[str, Any],
    layer: LayerDecision,
) -> None:
    db.execute(
        text(
            f"""
            INSERT INTO ra_ai_evaluations (
              id, org_id, run_id, candidate_id, asin, layer, model_role,
              model_name, score, verdict, skill_version, skill_hash, payload,
              in_tokens, out_tokens, cost_usd
            )
            VALUES (
              :id, :org_id, :run_id, :candidate_id, :asin, :layer, :model_role,
              :model_name, :score, :verdict, :skill_version, :skill_hash,
              {_json_bind(db, "payload")}, :in_tokens, :out_tokens, :cost_usd
            )
            """
        ),
        {
            "id": str(uuid4()),
            "org_id": org_id,
            "run_id": run_id,
            "candidate_id": context.get("candidate_id"),
            "asin": context.get("asin"),
            "layer": layer.layer,
            "model_role": layer.model_role,
            "model_name": layer.model_name,
            "score": layer.score,
            "verdict": layer.verdict,
            "skill_version": layer.payload.get("skill_version"),
            "skill_hash": layer.payload.get("skill_hash"),
            "payload": _json_dumps(layer.payload),
            "in_tokens": layer.in_tokens,
            "out_tokens": layer.out_tokens,
            "cost_usd": layer.cost_usd,
        },
    )


def _insert_final_decision(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    context: dict[str, Any],
    final: dict[str, Any],
) -> None:
    payload = {
        **final,
        "mock": False,
        "asin": context.get("asin"),
        "candidate_id": context.get("candidate_id"),
    }
    db.execute(
        text(
            f"""
            INSERT INTO ra_final_decisions (
              id, org_id, run_id, candidate_id, asin, final_score, verdict,
              channel, barrier_type, decision_reason, payload
            )
            VALUES (
              :id, :org_id, :run_id, :candidate_id, :asin, :final_score,
              :verdict, :channel, :barrier_type, :decision_reason,
              {_json_bind(db, "payload")}
            )
            """
        ),
        {
            "id": str(uuid4()),
            "org_id": org_id,
            "run_id": run_id,
            "candidate_id": context.get("candidate_id"),
            "asin": context.get("asin"),
            "final_score": final["final_score"],
            "verdict": final["verdict"],
            "channel": final["channel"],
            "barrier_type": final["barrier_type"],
            "decision_reason": final["decision_reason"],
            "payload": _json_dumps(payload),
        },
    )


def _insert_report(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    context: dict[str, Any],
    final: dict[str, Any],
    layers: list[LayerDecision],
) -> None:
    report_id = str(final.get("report_id") or uuid4())
    product = _dict_value(context.get("product"))
    title = product.get("title_zh") or product.get("title") or context.get("asin")
    summary = f"{title}：{final['decision_reason']}"
    payload = {
        "mock": False,
        "ai_pipeline_version": RA_AI_PIPELINE_VERSION,
        "skill_version": final.get("skill_version"),
        "skill_hash": final.get("skill_hash"),
        "skill": final.get("skill"),
        "final": final,
        "layers": [layer.payload for layer in layers],
        "product": _model_input_summary(context),
        "competition": _competition_payload(context),
    }
    db.execute(
        text(
            f"""
            INSERT INTO ra_reports (
              report_id, org_id, run_id, candidate_id, asin, status,
              title, summary, payload
            )
            VALUES (
              :report_id, :org_id, :run_id, :candidate_id, :asin,
              'ready', :title, :summary, {_json_bind(db, "payload")}
            )
            """
        ),
        {
            "report_id": report_id,
            "org_id": org_id,
            "run_id": run_id,
            "candidate_id": context.get("candidate_id"),
            "asin": context.get("asin"),
            "title": str(title or "")[:400],
            "summary": summary[:1000],
            "payload": _json_dumps(payload),
        },
    )


def _update_candidate_status(db: Session, *, candidate_id: str, verdict: str) -> None:
    status = {
        "pass": "ai_passed",
        "reject": "ai_rejected",
        "review": "ai_review",
    }.get(verdict, "ai_review")
    db.execute(
        text(
            """
            UPDATE ra_candidates
            SET candidate_status = :status, updated_at = CURRENT_TIMESTAMP
            WHERE id = :candidate_id
            """
        ),
        {"candidate_id": candidate_id, "status": status},
    )


def _clear_ai_outputs(db: Session, *, org_id: str, run_id: str) -> None:
    db.execute(
        text(
            """
            DELETE FROM ra_ai_evaluations
            WHERE org_id = :org_id AND run_id = :run_id
              AND layer IN ('deepseek', 'gpt', 'opus')
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    )
    db.execute(
        text(
            """
            DELETE FROM ra_final_decisions
            WHERE org_id = :org_id AND run_id = :run_id
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    )
    db.execute(
        text(
            """
            DELETE FROM ra_reports
            WHERE org_id = :org_id AND run_id = :run_id
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    )


def _clear_ai_outputs_for_candidate(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    candidate_id: str,
) -> None:
    params = {"org_id": org_id, "run_id": run_id, "candidate_id": candidate_id}
    db.execute(
        text(
            """
            DELETE FROM ra_ai_evaluations
            WHERE org_id = :org_id AND run_id = :run_id
              AND candidate_id = :candidate_id
              AND layer IN ('deepseek', 'gpt', 'opus')
            """
        ),
        params,
    )
    db.execute(
        text(
            """
            DELETE FROM ra_final_decisions
            WHERE org_id = :org_id AND run_id = :run_id
              AND candidate_id = :candidate_id
            """
        ),
        params,
    )
    db.execute(
        text(
            """
            DELETE FROM ra_reports
            WHERE org_id = :org_id AND run_id = :run_id
              AND candidate_id = :candidate_id
            """
        ),
        params,
    )


def _merge_run_counts(db: Session, *, run_id: str, counts: dict[str, Any]) -> None:
    row = db.execute(
        text("SELECT counts FROM ra_selection_runs WHERE run_id = :run_id LIMIT 1"),
        {"run_id": run_id},
    ).mappings().first()
    existing = _dict_value(row.get("counts") if row else {})
    existing.update(counts)
    db.execute(
        text(
            f"""
            UPDATE ra_selection_runs
            SET counts = {_json_bind(db, "counts")},
                runtime_mode = 'background_profit_queue_ai_real',
                updated_at = CURRENT_TIMESTAMP
            WHERE run_id = :run_id
            """
        ),
        {"run_id": run_id, "counts": _json_dumps(existing)},
    )


def _load_run_counts(db: Session, *, run_id: str) -> dict[str, Any]:
    row = db.execute(
        text("SELECT counts FROM ra_selection_runs WHERE run_id = :run_id LIMIT 1"),
        {"run_id": run_id},
    ).mappings().first()
    return _dict_value(row.get("counts") if row else {})


def _load_provider_configs(db: Session, *, org_id: str) -> dict[str, ProviderConfig]:
    binding = RAnalysisProviderBinding(
        org_id=org_id,
        secret_manager=SecretManager(db_session=db),
    )
    try:
        deepseek_secret = binding.deepseek_config()
        gpt_secret = binding.gpt_config()
        opus_secret = binding.opus_config()
    except SecretManagerError as exc:
        raise RAAISelectionError(f"R-A AI key 未完整绑定：{exc}") from exc
    deepseek = _provider_config(
        role="deepseek",
        service="deepseek",
        secret=deepseek_secret,
        env_base_url="DEEPSEEK_BASE_URL",
        default_base_url="https://api.deepseek.com",
        env_model="RA_DEEPSEEK_MODEL",
        fallback_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    )
    gpt = _provider_config(
        role="gpt",
        service="4sapi",
        secret=gpt_secret,
        env_base_url="FOURSAPI_BASE_URL",
        default_base_url="https://api.4sapi.com/v1",
        env_model="RA_GPT_MODEL",
        fallback_model="gpt-5.5",
    )
    opus = _provider_config(
        role="opus",
        service="4sapi",
        secret=opus_secret,
        env_base_url="FOURSAPI_BASE_URL",
        default_base_url="https://api.4sapi.com/v1",
        env_model="RA_OPUS_MODEL",
        fallback_model="claude-opus-4-8-thinking",
    )
    return {"deepseek": deepseek, "gpt": gpt, "opus": opus}


def _provider_config(
    *,
    role: str,
    service: str,
    secret: dict[str, Any],
    env_base_url: str,
    default_base_url: str,
    env_model: str,
    fallback_model: str,
) -> ProviderConfig:
    raw_value = str(secret.get("value") or "")
    payload = _dict_value(raw_value)
    api_key = str(
        payload.get("api_key")
        or payload.get("key")
        or payload.get("token")
        or raw_value
        or ""
    ).strip()
    if not api_key:
        raise RAAISelectionError(f"{role} key 未绑定。")
    base_url = (
        str(payload.get("base_url") or payload.get("baseUrl") or "").strip()
        or str(secret.get("url") or "").strip()
        or os.getenv(env_base_url, "").strip()
        or default_base_url
    )
    model = (
        os.getenv(env_model, "").strip()
        or str(payload.get("model") or payload.get("model_name") or "").strip()
        or fallback_model
    )
    return ProviderConfig(
        role=role,
        service=service,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )


def _parse_model_json(content: Any) -> dict[str, Any]:
    parsed = _try_parse_model_json(content)
    if parsed is not None:
        return parsed
    text_value = str(content or "").strip()
    if not text_value:
        return {}
    return {"reason": text_value[:500], "score": 50, "verdict": "review"}


def _try_parse_model_json(content: Any) -> dict[str, Any] | None:
    text_value = str(content or "").strip()
    if not text_value:
        return None
    try:
        parsed = json.loads(text_value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text_value, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _structured_model_output(output: dict[str, Any] | None) -> bool:
    if not isinstance(output, dict):
        return False
    score = output.get("score")
    verdict = str(output.get("verdict") or "").strip().lower()
    reason = str(output.get("reason") or "").strip()
    if verdict not in {"pass", "reject", "review"}:
        return False
    if not reason or reason.startswith("{"):
        return False
    try:
        int(score)
    except (TypeError, ValueError):
        return False
    return True


def _response_content(parsed: dict[str, Any]) -> str | None:
    choices = parsed.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text = "\n".join(
                    str(item.get("text") or "")
                    for item in content
                    if isinstance(item, dict)
                ).strip()
                if text:
                    return text
    content = parsed.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text = "\n".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict)
        ).strip()
        if text:
            return text
    return None


def _empty_response_message(
    *,
    provider: ProviderConfig,
    parsed: dict[str, Any],
    spec: dict[str, Any],
) -> str:
    usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
    output_tokens = _int_value(usage.get("output_tokens") or usage.get("completion_tokens"))
    thinking_tokens = _int_value(
        _dict_value(usage.get("output_tokens_details")).get("thinking_tokens")
    )
    stop_reason = parsed.get("stop_reason") or parsed.get("finish_reason")
    label = str(spec.get("label") or "")
    detail = (
        f"{provider.role} 返回内容为空"
        f"（endpoint={label or spec.get('endpoint')}, stop_reason={stop_reason}, "
        f"output_tokens={output_tokens}, thinking_tokens={thinking_tokens}）。"
    )
    if thinking_tokens and output_tokens and thinking_tokens >= output_tokens:
        detail += "疑似 thinking 模型消耗完输出预算，未生成最终 JSON。"
    return detail


def _invalid_json_response_message(
    *,
    provider: ProviderConfig,
    content: str,
    parsed: dict[str, Any],
    spec: dict[str, Any],
) -> str:
    usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
    output_tokens = _int_value(usage.get("output_tokens") or usage.get("completion_tokens"))
    stop_reason = parsed.get("stop_reason") or parsed.get("finish_reason")
    label = str(spec.get("label") or spec.get("endpoint") or "")
    excerpt = re.sub(r"\s+", " ", content).strip()[:220]
    return (
        f"{provider.role} 返回 JSON 不完整或结构不合格"
        f"（endpoint={label}, stop_reason={stop_reason}, output_tokens={output_tokens}）："
        f"{excerpt}"
    )


def _empty_content_error(message: str | None) -> bool:
    text_value = str(message or "")
    return (
        "返回内容为空" in text_value
        or "未生成最终 JSON" in text_value
        or "JSON 不完整" in text_value
        or "结构不合格" in text_value
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _competition_payload(context: dict[str, Any]) -> dict[str, Any]:
    competition = _dict_value(context.get("competition"))
    if not competition:
        return {}
    return {
        "keyword": competition.get("keyword"),
        "top3_review_count": competition.get("top3_review_count") or [],
        "review_wall_max": competition.get("review_wall_max"),
        "single_brand_share": competition.get("single_brand_share"),
        "dominant_brand": competition.get("dominant_brand"),
        "new_entrant_ratio_est": competition.get("new_entrant_ratio_est"),
        "page_one_sample": competition.get("page_one_sample") or [],
        "market_seller_count_est": competition.get("market_seller_count_est"),
        "market_brand_count_est": competition.get("market_brand_count_est"),
        "competition_data_valid": competition.get("competition_data_valid"),
        "competition_invalid_reason": competition.get("competition_invalid_reason"),
        "keyword_source": competition.get("keyword_source"),
        "source": competition.get("source"),
        "cache_hit": bool(competition.get("cache_hit")),
        "credits_used": competition.get("credits_used"),
        "credits_used_this_call": competition.get("credits_used_this_call"),
        "error": _dict_value(competition.get("payload")).get("error"),
    }


def _audit_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": payload.get("task"),
        "channel": payload.get("channel"),
        "layer": payload.get("layer"),
        "gating_rule": payload.get("gating_rule"),
        "skill": payload.get("skill"),
        "product": payload.get("product"),
        "profit": payload.get("profit"),
        "supplier": payload.get("supplier"),
        "competition": payload.get("competition"),
        "previous_layers": payload.get("previous_layers"),
    }


def _provider_url(base_url: str, endpoint: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    suffix = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    if base.endswith("/v1") and suffix.startswith("/v1/"):
        suffix = suffix[3:]
    return f"{base}{suffix}"


def _valid_verdict(value: str) -> str:
    if value in {"pass", "reject", "review"}:
        return value
    if value in {"keep", "approve", "passed"}:
        return "pass"
    if value in {"cut", "fail", "failed", "no"}:
        return "reject"
    return "review"


def _layer_pass_threshold(layer: str) -> int:
    env_name = {
        "deepseek": "DEEPSEEK_PASS_SCORE",
        "gpt": "GPT_PASS_SCORE",
        "opus": "OPUS_KEEP_SCORE",
    }.get(layer, "OPUS_KEEP_SCORE")
    defaults = {"deepseek": 60, "gpt": 65, "opus": 70}
    return _bounded_int(os.getenv(env_name), defaults.get(layer, 70), 0, 100)


def _bounded_score(value: Any) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 50.0
    return max(0, min(100, int(round(parsed))))


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default


def _ai_timeout_seconds() -> int:
    return _bounded_int(os.getenv("RA_AI_TIMEOUT_SECONDS"), 75, 10, 180)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()][:8]


def _dedupe_text(values: Any) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text_value = str(value or "").strip()
        if not text_value or text_value in seen:
            continue
        seen.add(text_value)
        output.append(text_value)
    return output


def _first_barrier(layers: list[LayerDecision]) -> str | None:
    for layer in layers:
        barrier = str(layer.payload.get("barrier_type") or "").strip()
        if barrier and barrier != "none":
            return barrier[:32]
    return None


def _estimated_cost(provider: ProviderConfig, usage: dict[str, Any]) -> Decimal | None:
    input_tokens = _int_value(usage.get("prompt_tokens"))
    output_tokens = _int_value(usage.get("completion_tokens"))
    in_rate = _rate_env(f"RA_{provider.role.upper()}_INPUT_USD_PER_1M")
    out_rate = _rate_env(f"RA_{provider.role.upper()}_OUTPUT_USD_PER_1M")
    if in_rate is None and out_rate is None:
        return None
    total = (Decimal(input_tokens) * (in_rate or Decimal("0")) / Decimal("1000000")) + (
        Decimal(output_tokens) * (out_rate or Decimal("0")) / Decimal("1000000")
    )
    return total.quantize(Decimal("0.0001"))


def _rate_env(name: str) -> Decimal | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return Decimal(value)
    except Exception:
        return None


def _redacted_base_url(value: str) -> str:
    cleaned = str(value or "").strip()
    return cleaned[:120]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return str(value)
