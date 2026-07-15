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
from r_system_v2.ra.channel_signals import ensure_channel_signals
from r_system_v2.ra.competition import ensure_competition_snapshot
from r_system_v2.ra.deep_enrichment import ensure_deep_enrichment
from r_system_v2.ra.events import emit_event
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
    """Run the real AI chain for one profit-passed candidate without touching siblings.

    已评过的候选（ai_review/ai_passed 等）也允许重审——旧评估/报告会被
    清掉重写，用于渠道抖动后的补审或人工要求的复审。
    """
    from r_system_v2.ra.ai_selection_mock import AI_DONE_CANDIDATE_STATUSES

    normalized_candidate_id = str(candidate_id or "").strip()
    if not normalized_candidate_id:
        raise RAAISelectionError("缺少 R-A candidate_id，无法启动 AI 链。")
    candidates = [
        context
        for context in _load_candidate_contexts(
            db, org_id=org_id, run_id=run_id, statuses=AI_DONE_CANDIDATE_STATUSES
        )
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
                # competition 全量块留在报告里；轮询载荷只带 UI 用得到的字段。
                "channel_routes": payload.get("channel_routes"),
                "primary_channel": payload.get("primary_channel"),
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
        "channel_signals": 0,
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
    asin = str(context.get("asin") or "")
    candidate_id = str(context.get("candidate_id") or "") or None
    competition = ensure_competition_snapshot(db, org_id=org_id, context=context)
    context["competition"] = competition
    # 立即提交：后续 channel_signals 里的 Serper 调用前会 rollback 清事务。
    emit_event(
        db,
        org_id=org_id,
        run_id=run_id,
        stage="competition",
        asin=asin,
        candidate_id=candidate_id,
        verdict=str(competition.get("source") or ""),
        detail={
            "keyword": competition.get("keyword"),
            "review_wall_max": competition.get("review_wall_max"),
            "single_brand_share": competition.get("single_brand_share"),
            "cache_hit": bool(competition.get("cache_hit")),
        },
        commit=True,
    )
    channel_signals = ensure_channel_signals(
        db,
        org_id=org_id,
        run_id=run_id,
        context=context,
        competition=competition,
    )
    context["channel_signals"] = channel_signals
    context["prescreen"] = _load_prescreen_context(db, org_id=org_id, asin=asin)
    emit_event(
        db,
        org_id=org_id,
        run_id=run_id,
        stage="channel_signals",
        asin=asin,
        candidate_id=candidate_id,
        verdict=str(_dict_value(channel_signals.get("primary_route")).get("channel") or ""),
        detail={
            "primary_route": channel_signals.get("primary_route"),
            "keyword": channel_signals.get("keyword"),
        },
        commit=False,
    )
    db.commit()
    counts["rainforest_snapshots"] += 1
    counts["channel_signals"] += 1
    counts["rainforest_credits_used"] += int(competition.get("credits_used_this_call") or 0)
    if competition.get("cache_hit"):
        counts["rainforest_cache_hits"] += 1
    # 深度富化：只有利润幸存者才走到这里，放心花 Keepa token + Rainforest 积分。
    try:
        deep = ensure_deep_enrichment(db, org_id=org_id, asin=asin)
    except Exception as exc:
        deep = {"errors": {"deep_enrichment": str(exc)[:300]}}
    context["deep_enrichment"] = deep
    deep_keepa = _dict_value(deep.get("keepa"))
    emit_event(
        db,
        org_id=org_id,
        run_id=run_id,
        stage="deep_enrichment",
        asin=asin,
        candidate_id=candidate_id,
        verdict="cached" if deep.get("cache_hit") else "fetched",
        detail={
            "bsr_trend_12m": deep_keepa.get("bsr_trend_12m"),
            "has_12m_history": deep_keepa.get("has_12m_history"),
            "price_floor_declining": deep_keepa.get("price_floor_declining"),
            "critical_reviews": len(deep.get("reviews") or []),
            "errors": deep.get("errors") or {},
        },
        commit=True,
    )
    # token 瘦身：按该候选的主渠道只加载对应判断手册，而不是全家桶。
    candidate_channel = _candidate_channel(context, requested_channel=channel)
    candidate_bundle = _bundle_for_channel(candidate_channel, fallback=skill_bundle)
    layers = _evaluate_real_layers(
        context,
        skill_bundle=candidate_bundle,
        providers=providers,
        channel=candidate_channel,
    )
    for layer in layers:
        _insert_ai_evaluation(db, org_id=org_id, run_id=run_id, context=context, layer=layer)
        counts["ai_evaluations"] += 1
        if layer.layer in {"gpt", "opus"}:
            emit_event(
                db,
                org_id=org_id,
                run_id=run_id,
                stage=f"{layer.layer}_review",
                asin=asin,
                candidate_id=candidate_id,
                verdict=layer.verdict,
                detail={"score": layer.score, "reason": layer.reason[:200]},
                commit=False,
            )
    final = _final_decision(context, layers, channel=candidate_channel, skill_bundle=candidate_bundle)
    final["report_id"] = str(uuid4())
    _insert_final_decision(db, org_id=org_id, run_id=run_id, context=context, final=final)
    _insert_report(db, org_id=org_id, run_id=run_id, context=context, final=final, layers=layers)
    emit_event(
        db,
        org_id=org_id,
        run_id=run_id,
        stage="group_assign",
        asin=asin,
        candidate_id=candidate_id,
        verdict=str(final["verdict"]),
        detail={
            "final_score": final.get("final_score"),
            "channel": final.get("channel"),
            "pass_channels": _dict_value(final.get("primary_channel")).get("all_pass_channels")
            or _pass_channels(final.get("channel_routes")),
            "reason": str(final.get("decision_reason") or "")[:200],
            "report_id": final.get("report_id"),
            "title": _dict_value(context.get("product")).get("title_zh")
            or _dict_value(context.get("product")).get("title"),
            "image_url": _dict_value(context.get("product")).get("image_url"),
        },
        commit=False,
    )
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
    """新漏斗：DeepSeek 初筛结果作为上下文层，GPT 是终审法官。

    Opus 不再默认参与每个候选（成本纪律）；RA_OPUS_PER_CANDIDATE=true 时
    才对 GPT 放行的候选追加 Opus 层。每日 top10 复核由 auto-cruise 单独调度。
    """
    layers: list[LayerDecision] = []
    prescreen_layer = _prescreen_layer_decision(context, skill_bundle=skill_bundle)
    if prescreen_layer is not None:
        layers.append(prescreen_layer)
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
    if _opus_per_candidate_enabled():
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


def _opus_per_candidate_enabled() -> bool:
    return os.getenv("RA_OPUS_PER_CANDIDATE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _prescreen_layer_decision(
    context: dict[str, Any],
    *,
    skill_bundle: RASkillBundle,
) -> LayerDecision | None:
    """Surface the stored DeepSeek prescreen as a context layer for the UI/GPT."""
    prescreen = _dict_value(context.get("prescreen"))
    if not prescreen:
        return None
    score = _bounded_score(prescreen.get("score"))
    verdict = {
        "keep": "pass",
        "hold": "review",
        "cut": "reject",
    }.get(str(prescreen.get("verdict") or "").lower(), "review")
    reason = str(prescreen.get("reason") or "DeepSeek 初筛已完成。")
    payload = {
        "mock": False,
        "ai_pipeline_version": RA_AI_PIPELINE_VERSION,
        "skill_version": skill_bundle.version,
        "skill_hash": skill_bundle.combined_hash,
        "asin": context.get("asin"),
        "score": score,
        "verdict": verdict,
        "reason": reason,
        "advantages": [],
        "risks": [],
        "channel_guess": prescreen.get("channel_guess"),
        "model_output": {
            "score": score,
            "verdict": prescreen.get("verdict"),
            "reason": reason,
            "channel_guess": prescreen.get("channel_guess"),
            "evidence": prescreen.get("evidence"),
        },
        "prescreen_id": prescreen.get("id"),
        "prescreen_mode": prescreen.get("mode"),
        "source": "ra_prescreen",
    }
    return LayerDecision(
        layer="prescreen",
        model_role="deepseek",
        model_name=str(prescreen.get("model") or "deepseek"),
        score=score,
        verdict=verdict,
        reason=reason,
        risks=[],
        advantages=[],
        payload=payload,
    )


def _load_prescreen_context(
    db: Session,
    *,
    org_id: str,
    asin: str,
) -> dict[str, Any]:
    if not asin:
        return {}
    try:
        row = db.execute(
            text(
                """
                SELECT id, asin, score, verdict, channel_guess, reason, evidence,
                       model, mode, created_at
                FROM ra_prescreen
                WHERE org_id = :org_id AND UPPER(asin) = :asin
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"org_id": org_id, "asin": asin.strip().upper()},
        ).mappings().first()
    except Exception:
        db.rollback()
        return {}
    return dict(row) if row else {}


_BUNDLE_CACHE: dict[str, RASkillBundle] = {}


def _candidate_channel(context: dict[str, Any], *, requested_channel: str) -> str:
    """Pick the per-candidate skill channel from signals → prescreen → request."""
    signals = _dict_value(context.get("channel_signals"))
    primary = _dict_value(signals.get("primary_route"))
    for value in (
        primary.get("channel"),
        _dict_value(context.get("prescreen")).get("channel_guess"),
        requested_channel,
    ):
        cleaned = str(value or "").strip().lower().replace("-", "_")
        if cleaned in {"amazon", "dtc_ad", "dtc_seo", "both"}:
            return cleaned
    return "both"


def _bundle_for_channel(channel: str, *, fallback: RASkillBundle) -> RASkillBundle:
    cleaned = str(channel or "both").strip().lower()
    if cleaned == fallback.channel:
        return fallback
    cached = _BUNDLE_CACHE.get(cleaned)
    if cached is not None:
        return cached
    try:
        bundle = load_ra_skill_bundle(cleaned)
    except Exception:
        return fallback
    _BUNDLE_CACHE[cleaned] = bundle
    return bundle


def _pass_channels(channel_routes: Any) -> list[str]:
    routes = _dict_value(channel_routes).get("routes")
    if not isinstance(routes, dict):
        return []
    return [
        str(name)
        for name, route in routes.items()
        if isinstance(route, dict) and route.get("verdict") == "pass"
    ]


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
    # thinking 模型的思考过程也消耗输出额度：太小会全花在思考上导致正文为空。
    max_tokens = _bounded_int(os.getenv("RA_OPUS_MAX_TOKENS"), 8000, 1024, 16000)
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


def _retry_sleep(seconds: float) -> None:
    import time as _time

    _time.sleep(seconds)


def _execute_chat_request(
    provider: ProviderConfig,
    *,
    spec: dict[str, Any],
) -> dict[str, Any]:
    payload = _dict_value(spec.get("payload"))
    endpoint = str(spec.get("endpoint") or "/v1/chat/completions")
    body = _json_dumps(payload).encode("utf-8")
    raw_body: str | None = None
    last_error: RAAISelectionError | None = None
    # 4sapi 等分销网关会出现秒级渠道抖动（429/5xx/No available channel）：
    # 瞬时错误退避重试，别把好产品打进待滑堆。
    for attempt in range(3):
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
            break
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            last_error = RAAISelectionError(
                f"{provider.role} 调用失败：HTTP {exc.code} {detail}"
            )
            transient = exc.code in {429, 500, 502, 503, 504} or (
                "No available channel" in detail
            )
            if transient and attempt < 2:
                _retry_sleep(3.0 * (attempt + 1))
                continue
            raise last_error from exc
        except (URLError, TimeoutError) as exc:
            last_error = RAAISelectionError(f"{provider.role} 调用失败：{exc}")
            if attempt < 2:
                _retry_sleep(3.0 * (attempt + 1))
                continue
            raise last_error from exc
    if raw_body is None:
        raise last_error or RAAISelectionError(f"{provider.role} 调用失败。")
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
            "route_recommendations": {
                "amazon": "pass|review|reject plus short reason",
                "dtc_ad": "pass|review|reject plus short reason",
                "dtc_seo": "pass|review|reject plus short reason",
            },
        },
        "gating_rule": _layer_gating_rule(layer),
        "skill": _skill_payload(skill_bundle),
        "skill_text": skill_bundle.prompt_text,
        "product": _model_input_summary(context),
        "raw_product": _model_product_payload(context),
        "profit": _dict_value(context.get("profit")),
        "supplier": _dict_value(context.get("supplier")),
        "competition": _competition_payload(context),
        "channel_signals": _channel_signals_payload(context),
        "deep_enrichment": _deep_enrichment_payload(context),
        "google_ads_planner": _google_ads_planner_payload(context),
        "channel_principles": CHANNEL_PRINCIPLES,
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
            "route_recommendations": {
                "amazon": "pass|review|reject plus short reason",
                "dtc_ad": "pass|review|reject plus short reason",
                "dtc_seo": "pass|review|reject plus short reason",
            },
        },
        "gating_rule": _layer_gating_rule("opus"),
        "instruction": (
            "只做最终结论，不展开推理过程。必须只输出一个 JSON 对象。"
            "如果 Rainforest/销量/供应商数据无效或冲突，优先 review，不要强行通过或淘汰。"
            "route_recommendations 必须严格按 channel_principles 的三托盘原则逐渠道独立判定："
            "亚马逊=备货最严标准；独立站广告=用 google_ads_planner 的 CPC 日常价算获客经济账；"
            "独立站SEO=看月搜索量与CPC含金量及时间匹配。一个渠道的问题不得连坐其他渠道。"
        ),
        "skill": _skill_payload(skill_bundle),
        "skill_rules_summary": _opus_skill_summary(skill_bundle),
        "product": _model_input_summary(context),
        "profit": _compact_value(_dict_value(context.get("profit")), max_chars=2200),
        "supplier": _compact_value(_dict_value(context.get("supplier")), max_chars=2200),
        "competition": _competition_payload(context),
        "channel_signals": _compact_value(_channel_signals_payload(context), max_chars=2200),
        "deep_enrichment": _compact_value(_deep_enrichment_payload(context), max_chars=2600),
        # planner 精华块独立传：不走 compact，防止被 2200 字符截断吃掉。
        "google_ads_planner": _google_ads_planner_payload(context),
        "channel_principles": CHANNEL_PRINCIPLES,
        "previous_layers": [
            _compact_value(layer_decision.payload.get("model_output"), max_chars=1400)
            for layer_decision in previous_layers
        ],
    }


def _google_ads_planner_payload(context: dict[str, Any]) -> dict[str, Any]:
    """Google Keyword Planner 精华块：独立传给模型，绝不被 compact 截断。

    日常价估算口径：实际成交均价通常贴低位区间走，取 low + (high-low)*0.25。
    """
    signals = _dict_value(context.get("channel_signals"))
    planner = _dict_value(_dict_value(signals.get("dtc_seo")).get("keyword_planner"))
    if not planner:
        return {}
    low = planner.get("cpc_low_micros")
    high = planner.get("cpc_high_micros")
    low_usd = round(low / 1e6, 2) if isinstance(low, (int, float)) and low else None
    high_usd = round(high / 1e6, 2) if isinstance(high, (int, float)) and high else None
    typical_usd = (
        round((low + (high - low) * 0.25) / 1e6, 2)
        if isinstance(low, (int, float)) and isinstance(high, (int, float)) and low and high
        else low_usd
    )
    ideas = []
    for idea in (planner.get("keyword_ideas") or [])[:8]:
        if isinstance(idea, dict) and idea.get("keyword"):
            ideas.append(
                {
                    "keyword": idea.get("keyword"),
                    "avg_monthly_searches": idea.get("avg_monthly_searches"),
                    "competition_index": idea.get("competition_index"),
                }
            )
    return {
        "status": planner.get("runtime_status"),
        "keyword": signals.get("keyword"),
        "avg_monthly_searches": planner.get("avg_monthly_searches"),
        "competition_index": planner.get("competition_index"),
        "cpc_low_usd": low_usd,
        "cpc_typical_usd_estimate": typical_usd,
        "cpc_high_usd": high_usd,
        "cpc_note": "CPC高=流量被市场验证值钱=SEO含金量高；广告经济性用日常价估算CAC",
        "top_ideas": ideas,
    }


# 三托盘审核原则：终审/复核模型必须按渠道分别判，不许一票否决拖累其他托盘。
CHANNEL_PRINCIPLES = {
    "amazon": (
        "亚马逊备货托盘=真金压货，标准最严：必须有12个月稳定需求、无价格战"
        "（价格地板未持续下跌）、竞争可入；证据不足或存疑必须 reject，绝不赌。"
    ),
    "dtc_ad": (
        "独立站广告托盘=零库存但花钱买流量：核心是广告经济性——用 CPC 日常价"
        "估算获客成本（CPC÷转化率3-5%）对比单件毛利；毛利扛不住 CAC 就 reject。"
        "爆款/短历史品适合此通道（当天见效，时间匹配）。"
    ),
    "dtc_seo": (
        "独立站SEO托盘=零成本自然流量：看 Google 月搜索量、CPC 含金量"
        "（CPC 越高说明流量越值钱、SEO 越有肉吃）、SERP 弱位。"
        "SEO 见效需数月：昙花款/历史过短的品不适合此通道（排名起来风口已过）。"
    ),
}


def _deep_enrichment_payload(context: dict[str, Any]) -> dict[str, Any]:
    """深度富化证据（Keepa 12 月 + 真实差评）给模型的精简视图。"""
    deep = _dict_value(context.get("deep_enrichment"))
    if not deep:
        return {}
    keepa = _dict_value(deep.get("keepa"))
    product = _dict_value(deep.get("rainforest_product"))
    themes = _dict_value(deep.get("review_themes"))
    reviews = deep.get("reviews") if isinstance(deep.get("reviews"), list) else []
    trimmed_reviews = [
        {
            "rating": _dict_value(review).get("rating"),
            "title": str(_dict_value(review).get("title") or "")[:80],
            "body": str(_dict_value(review).get("body") or "")[:300],
        }
        for review in reviews[:4]
    ]
    return {
        "keepa_12m": {
            "has_12m_history": keepa.get("has_12m_history"),
            "history_days": keepa.get("history_days"),
            "bsr_trend_12m": keepa.get("bsr_trend_12m"),
            "bsr_change_pct_12m": keepa.get("bsr_change_pct_12m"),
            "price_floor_declining": keepa.get("price_floor_declining"),
            "price_floor_change_pct_12m": keepa.get("price_floor_change_pct_12m"),
            "min_price_12m": keepa.get("min_price_12m"),
            "current_new_price": keepa.get("current_new_price"),
            "viral_suspect": keepa.get("viral_suspect"),
        }
        if keepa
        else {},
        "listing_facts": {
            "brand": product.get("brand"),
            "rating": product.get("rating"),
            "ratings_total": product.get("ratings_total"),
            "rating_breakdown": product.get("rating_breakdown"),
            "recent_sales": product.get("recent_sales"),
            "bestsellers_rank": product.get("bestsellers_rank"),
            "buybox_price": product.get("buybox_price"),
            "buybox_fulfillment": product.get("buybox_fulfillment"),
            "variant_count": product.get("variant_count"),
            "has_a_plus_content": product.get("has_a_plus_content"),
            "has_coupon": product.get("has_coupon"),
            "videos_count": product.get("videos_count"),
            "proposition_65_warning": product.get("proposition_65_warning"),
            "listing_keywords": product.get("listing_keywords"),
            "first_available": product.get("first_available"),
        }
        if product
        else {},
        "critical_review_themes": themes.get("top_complaints") or [],
        "critical_review_severity": themes.get("severity"),
        "differentiation_summary": themes.get("differentiation_summary"),
        "critical_reviews_sample": trimmed_reviews,
        "data_gaps": deep.get("errors") or {},
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
    channel_signals = _channel_signals_payload(context)
    summary["primary_channel"] = _dict_value(channel_signals.get("primary_route")).get("channel")
    summary["channel_routes"] = _compact_channel_routes(channel_signals)
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
    if layer == "deepseek" or layer == "prescreen":
        return (
            "初筛层负责便宜快速量化：需求、评论墙、价格带。宁错放不错杀，"
            "它的结论只是上下文，不是终审。"
        )
    if layer == "gpt":
        return (
            "你是终审法官。候选已通过 DeepSeek 初筛与利润硬门，你拿到了全部上下文："
            "利润快照、1688 供应商、Rainforest 页一竞争、三渠道信号、初筛结论。"
            "验证数字之间是否自洽、需求是否真实（非昙花一现）、小卖家靠差异化能不能打进去，"
            "并给出渠道路由。score >= GPT_PASS_SCORE 且 verdict=pass 才入选品分组。"
        )
    return (
        "Opus 复核层从小卖家冷启动视角做最终判断：门槛是钱砌还是本事砌、"
        "真实 P&L 扛不扛得住、下一步行动是什么。只对 GPT 放行的产品运行。"
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
        "channel_signals": _channel_signals_payload(context),
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
    # 新漏斗：GPT 是终审法官；Opus 若运行则以更强模型的结论为准。
    final_layer = next(
        (layer for layer in reversed(layers) if layer.layer in {"gpt", "opus"}),
        None,
    )
    hard_reasons: list[str] = []
    if final_layer is None:
        hard_reasons.append("GPT 终审未运行。")
    if any(
        layer.verdict == "reject"
        for layer in layers
        if layer.layer in {"gpt", "opus"}
    ):
        hard_reasons.append("终审层给出拒绝。")
    if hard_reasons:
        verdict = "reject"
        final_score = min(average_score, 59)
        barrier_type = _first_barrier(layers) or "ai_risk"
    elif (
        final_layer.verdict == "pass"
        and (final_layer.score or 0) >= _layer_pass_threshold(final_layer.layer)
    ):
        verdict = "pass"
        final_score = final_layer.score or average_score
        barrier_type = "none"
    else:
        verdict = "review"
        final_score = average_score
        barrier_type = _first_barrier(layers) or "manual_review"

    channel_routes = _channel_routes(context, layers=layers, requested_channel=channel)
    primary_channel = _primary_channel(channel_routes, layers=layers, requested_channel=channel)
    leading_advantages = _dedupe_text(
        advantage
        for layer in layers
        for advantage in layer.advantages
    )[:4]
    leading_risks = _dedupe_text(risk for layer in layers for risk in layer.risks)[:4]
    if verdict == "pass":
        reason = "通过 R-A 漏斗评审：初筛、利润硬门、竞争富化与 GPT 终审均达到进入分组的最低线。"
    elif verdict == "reject":
        reason = "R-A 终审淘汰：" + "；".join(hard_reasons or leading_risks or ["核心指标不足"])
    else:
        reason = "进入待滑堆：部分指标可用，但仍存在需要人工确认的竞争、供应商或需求风险。"

    return {
        "final_score": _bounded_score(final_score),
        "verdict": verdict,
        "channel": primary_channel.get("channel") or channel,
        "primary_channel": primary_channel,
        "channel_routes": channel_routes,
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
        "channel_signals": _channel_signals_payload(context),
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
        "product_image_url": product.get("image_url"),
        "competition": _competition_payload(context),
        "channel_routes": final.get("channel_routes"),
        "primary_channel": final.get("primary_channel"),
        "channel_signals": _channel_signals_payload(context),
        # K 系列直读的关键词块：Rainforest + Serper + Google Ads 三路汇总。
        "keywords": _report_keywords_block(context),
        # 深度富化：Keepa 12 月 + Rainforest 全量 + 差评主题（详情浮层直读）。
        "deep_enrichment": _dict_value(context.get("deep_enrichment")),
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


def _report_keywords_block(context: dict[str, Any]) -> dict[str, Any]:
    """Assemble the keyword bundle that flows straight into K-series fields."""
    product = _dict_value(context.get("product"))
    competition = _competition_payload(context)
    signals = _channel_signals_payload(context)
    dtc_seo = _dict_value(signals.get("dtc_seo"))
    serp = _dict_value(dtc_seo.get("serp"))
    planner = _dict_value(dtc_seo.get("keyword_planner"))

    primary = str(
        competition.get("keyword")
        or signals.get("keyword")
        or product.get("source_query")
        or product.get("title")
        or ""
    ).strip()

    page_one_titles: list[str] = []
    for item in competition.get("page_one_sample") or []:
        if isinstance(item, dict):
            title = str(item.get("title") or "").strip()
            if title and title not in page_one_titles:
                page_one_titles.append(title)

    secondary: list[str] = []
    for value in serp.get("related_searches") or []:
        cleaned = str(value or "").strip()
        if cleaned and cleaned.lower() != primary.lower() and cleaned not in secondary:
            secondary.append(cleaned)
    long_tail: list[str] = []
    for value in serp.get("people_also_ask") or []:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in long_tail:
            long_tail.append(cleaned)
    google_ideas = []
    for idea in planner.get("keyword_ideas") or []:
        if not isinstance(idea, dict):
            continue
        keyword = str(idea.get("keyword") or "").strip()
        if not keyword:
            continue
        google_ideas.append(
            {
                "keyword": keyword,
                "avg_monthly_searches": idea.get("avg_monthly_searches"),
                "competition_index": idea.get("competition_index"),
            }
        )
        if keyword.lower() != primary.lower() and keyword not in secondary:
            secondary.append(keyword)

    return {
        "primary": primary or None,
        "secondary": secondary[:20],
        "long_tail": long_tail[:20],
        "amazon_page_one_titles": page_one_titles[:10],
        "google_ads": {
            "status": planner.get("runtime_status"),
            "avg_monthly_searches": planner.get("avg_monthly_searches"),
            "competition_index": planner.get("competition_index"),
            "cpc_low_micros": planner.get("cpc_low_micros"),
            "cpc_high_micros": planner.get("cpc_high_micros"),
            "ideas": google_ideas[:10],
        },
        "sources": {
            "primary": competition.get("keyword_source") or "competition_keyword",
            "secondary": "serper_related_searches+google_ads_ideas",
            "long_tail": "serper_people_also_ask",
        },
    }


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
              AND layer IN ('prescreen', 'deepseek', 'gpt', 'opus')
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
              AND layer IN ('prescreen', 'deepseek', 'gpt', 'opus')
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


def run_opus_review_for_report(
    db: Session,
    *,
    org_id: str,
    report_id: str,
) -> dict[str, Any]:
    """手动 Opus 建议：打包该产品全部上下文，让 Opus 出系统性建议。

    由分组/待滑堆里的「Opus 建议」按钮触发；结果写回报告 payload.opus_review。
    """
    row = db.execute(
        text(
            """
            SELECT report_id, run_id, candidate_id, asin
            FROM ra_reports
            WHERE report_id = :report_id AND org_id = :org_id
            LIMIT 1
            """
        ),
        {"report_id": report_id, "org_id": org_id},
    ).mappings().first()
    if row is None:
        raise RAAISelectionError("R-A 报告不存在。")
    run_id = str(row["run_id"] or "")
    candidate_id = str(row["candidate_id"] or "")
    from r_system_v2.ra.ai_selection_mock import AI_DONE_CANDIDATE_STATUSES

    contexts = [
        context
        for context in _load_candidate_contexts(
            db, org_id=org_id, run_id=run_id, statuses=AI_DONE_CANDIDATE_STATUSES
        )
        if str(context.get("candidate_id") or "") == candidate_id
    ]
    if not contexts:
        raise RAAISelectionError("候选上下文不存在，无法生成 Opus 建议。")
    context = contexts[0]
    context["prescreen"] = _load_prescreen_context(
        db, org_id=org_id, asin=str(context.get("asin") or "")
    )
    # 手动复核也要带全上下文：竞争数据（30 天缓存命中零成本）+ 渠道信号。
    competition = ensure_competition_snapshot(db, org_id=org_id, context=context)
    context["competition"] = competition
    context["channel_signals"] = ensure_channel_signals(
        db,
        org_id=org_id,
        run_id=run_id,
        context=context,
        competition=competition,
    )
    db.commit()
    try:
        context["deep_enrichment"] = ensure_deep_enrichment(
            db, org_id=org_id, asin=str(context.get("asin") or "")
        )
    except Exception as exc:
        context["deep_enrichment"] = {"errors": {"deep_enrichment": str(exc)[:300]}}
    channel = _candidate_channel(context, requested_channel="both")
    bundle = _bundle_for_channel(channel, fallback=load_ra_skill_bundle("both"))
    providers = _load_provider_configs(db, org_id=org_id)
    db.rollback()  # Opus 调用要 1-2 分钟：先结束事务防 idle 超时。
    opus = _call_layer(
        providers["opus"],
        layer="opus",
        context=context,
        skill_bundle=bundle,
        channel=channel,
        previous_layers=[],
    )
    _insert_ai_evaluation(db, org_id=org_id, run_id=run_id, context=context, layer=opus)
    review_payload = {
        "score": opus.score,
        "verdict": opus.verdict,
        "reason": opus.reason,
        "risks": opus.risks,
        "advantages": opus.advantages,
        "model": opus.model_name,
        "triggered": "manual_button",
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    db.execute(
        text(
            f"""
            UPDATE ra_reports
            SET payload = payload || {_json_bind(db, "opus_review")},
                updated_at = CURRENT_TIMESTAMP
            WHERE org_id = :org_id AND report_id = :report_id
            """
        ),
        {
            "org_id": org_id,
            "report_id": report_id,
            # 顺手把深度富化回填进旧报告：详情浮层即刻可见。
            "opus_review": _json_dumps(
                {
                    "opus_review": review_payload,
                    "deep_enrichment": _dict_value(context.get("deep_enrichment")),
                }
            ),
        },
    )
    emit_event(
        db,
        org_id=org_id,
        run_id=run_id,
        stage="opus_review",
        asin=str(context.get("asin") or ""),
        candidate_id=candidate_id,
        verdict=opus.verdict,
        detail={"score": opus.score, "reason": opus.reason[:200], "manual": True},
        commit=False,
    )
    db.commit()
    return review_payload


def extract_amazon_ad_keywords(
    db: Session,
    *,
    org_id: str,
    primary: str | None,
    page_one_titles: list[str],
    product_title: str | None,
) -> dict[str, Any]:
    """从亚马逊页一竞品标题中提炼可投广告/写文案的真关键词（DeepSeek）。

    页一标题是卖家的关键词堆砌结果——它们是原材料不是成品；
    这里让 DeepSeek 反向提炼出核心词与长尾词。
    """
    titles = [str(t or "").strip() for t in page_one_titles if str(t or "").strip()]
    if not titles and not primary:
        return {"core_keywords": [], "long_tail_keywords": []}
    provider = _load_provider_configs(db, org_id=org_id)["deepseek"]
    prompt = (
        "你是亚马逊广告关键词专家。下面是某产品的主搜索词和亚马逊页一竞品标题"
        "（标题是卖家关键词堆砌的结果）。请从中提炼买家真实会搜索、可直接用于"
        "广告投放和 listing 文案的英文关键词：\n"
        f"主搜索词：{primary or '(无)'}\n"
        f"本品标题：{str(product_title or '')[:120]}\n"
        f"页一竞品标题：{json.dumps(titles[:10], ensure_ascii=False)}\n\n"
        "要求：① core_keywords：5-8 个核心词（2-3 个单词的短语，购买意图明确）；"
        "② long_tail_keywords：5-8 个长尾词（3-5 个单词，含使用场景/属性/人群）；"
        "③ 全部小写、去品牌名、去规格数字、不重复；④ 按投放优先级排序。\n"
        '只输出 JSON：{"core_keywords":["..."],"long_tail_keywords":["..."]}'
    )
    db.rollback()  # AI 调用前结束事务。
    try:
        response = _execute_chat_request(
            provider,
            spec={
                "endpoint": "/v1/chat/completions",
                "label": "amazon_keywords",
                "payload": {
                    "model": provider.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            },
        )
        output = _try_parse_model_json(response.get("content")) or {}
    except Exception:
        return {"core_keywords": [], "long_tail_keywords": []}

    def _clean_list(values: Any) -> list[str]:
        output_list: list[str] = []
        for value in values if isinstance(values, list) else []:
            cleaned = str(value or "").strip().lower()[:60]
            if cleaned and cleaned not in output_list:
                output_list.append(cleaned)
        return output_list[:10]

    return {
        "core_keywords": _clean_list(output.get("core_keywords")),
        "long_tail_keywords": _clean_list(output.get("long_tail_keywords")),
        "extracted_at": datetime.now(UTC).isoformat(),
        "model": provider.model,
    }


def opus_daily_review_enabled() -> bool:
    return os.getenv("RA_OPUS_DAILY_REVIEW", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def run_opus_daily_review(
    db: Session,
    *,
    org_id: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Opus 复核加餐：对最近 24h GPT 放行的 top N 候选做最终把关。

    只在 RA_OPUS_DAILY_REVIEW=true 时由 auto-cruise 调度调用。
    结果以 opus 层追加进 ra_ai_evaluations，并写回报告 payload.opus_review。
    """
    if not opus_daily_review_enabled():
        return {"enabled": False, "reviewed": 0}
    rows = db.execute(
        text(
            """
            SELECT d.run_id, d.candidate_id, d.asin, d.final_score
            FROM ra_final_decisions d
            WHERE d.org_id = :org_id
              AND d.verdict = 'pass'
              AND d.created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
              AND NOT EXISTS (
                SELECT 1 FROM ra_ai_evaluations e
                WHERE e.org_id = d.org_id
                  AND e.candidate_id = d.candidate_id
                  AND e.run_id = d.run_id
                  AND e.layer = 'opus'
              )
            ORDER BY d.final_score DESC NULLS LAST, d.created_at DESC
            LIMIT :limit
            """
        ),
        {"org_id": org_id, "limit": max(1, min(int(limit or 10), 20))},
    ).mappings().all()
    if not rows:
        return {"enabled": True, "reviewed": 0}
    providers = _load_provider_configs(db, org_id=org_id)
    reviewed = 0
    for row in rows:
        run_id = str(row["run_id"])
        candidate_id = str(row["candidate_id"])
        contexts = [
            context
            for context in _load_candidate_contexts(db, org_id=org_id, run_id=run_id)
            if str(context.get("candidate_id") or "") == candidate_id
        ]
        if not contexts:
            continue
        context = contexts[0]
        context["prescreen"] = _load_prescreen_context(
            db, org_id=org_id, asin=str(context.get("asin") or "")
        )
        channel = _candidate_channel(context, requested_channel="both")
        bundle = _bundle_for_channel(channel, fallback=load_ra_skill_bundle("both"))
        try:
            opus = _call_layer(
                providers["opus"],
                layer="opus",
                context=context,
                skill_bundle=bundle,
                channel=channel,
                previous_layers=[],
            )
        except Exception:
            continue
        _insert_ai_evaluation(db, org_id=org_id, run_id=run_id, context=context, layer=opus)
        db.execute(
            text(
                f"""
                UPDATE ra_reports
                SET payload = payload || {_json_bind(db, "opus_review")},
                    updated_at = CURRENT_TIMESTAMP
                WHERE org_id = :org_id AND run_id = :run_id
                  AND candidate_id = :candidate_id
                """
            ),
            {
                "org_id": org_id,
                "run_id": run_id,
                "candidate_id": candidate_id,
                "opus_review": _json_dumps(
                    {
                        "opus_review": {
                            "score": opus.score,
                            "verdict": opus.verdict,
                            "reason": opus.reason,
                            "risks": opus.risks,
                            "advantages": opus.advantages,
                            "model": opus.model_name,
                            "reviewed_at": datetime.now(UTC).isoformat(),
                        }
                    }
                ),
            },
        )
        emit_event(
            db,
            org_id=org_id,
            run_id=run_id,
            stage="opus_review",
            asin=str(context.get("asin") or ""),
            candidate_id=candidate_id,
            verdict=opus.verdict,
            detail={"score": opus.score, "reason": opus.reason[:200]},
            commit=False,
        )
        db.commit()
        reviewed += 1
    return {"enabled": True, "reviewed": reviewed}


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
        fallback_model="gpt-5.6-luna",
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
    # http→https 会被网关重定向，urllib 对重定向把 POST 降级成 GET → 404。
    # AI 服务商全是 https，密钥里配成 http 的一律纠正。
    if base_url.startswith("http://"):
        base_url = "https://" + base_url[len("http://"):]
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


def _channel_signals_payload(context: dict[str, Any]) -> dict[str, Any]:
    signals = _dict_value(context.get("channel_signals"))
    if not signals:
        return {}
    return {
        "version": signals.get("version"),
        "keyword": signals.get("keyword"),
        "amazon": _dict_value(signals.get("amazon")),
        "dtc_ad": _dict_value(signals.get("dtc_ad")),
        "dtc_seo": _dict_value(signals.get("dtc_seo")),
        "primary_route": _dict_value(signals.get("primary_route")),
        "provider_modes": _dict_value(signals.get("provider_modes")),
        "generated_at": signals.get("generated_at"),
    }


def _compact_channel_routes(signals: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key in ("amazon", "dtc_ad", "dtc_seo"):
        route = _dict_value(signals.get(key))
        if not route:
            continue
        output[key] = {
            "label": route.get("label"),
            "score": route.get("score"),
            "verdict": route.get("verdict"),
            "reasons": route.get("reasons") or [],
            "risks": route.get("risks") or [],
            "provider_mode": route.get("provider_mode"),
        }
    return output


def _channel_routes(
    context: dict[str, Any],
    *,
    layers: list[LayerDecision],
    requested_channel: str,
) -> dict[str, Any]:
    signals = _channel_signals_payload(context)
    routes = _compact_channel_routes(signals)
    model_guesses = [
        _valid_channel(_dict_value(layer.payload.get("model_output")).get("channel_guess"))
        for layer in layers
    ]
    model_guesses = [value for value in model_guesses if value]
    for key, route in routes.items():
        route["model_supported"] = key in model_guesses or "both" in model_guesses
    return {
        "requested_channel": _valid_channel(requested_channel) or "both",
        "routes": routes,
        "model_channel_guesses": model_guesses,
        "provider_modes": _dict_value(signals.get("provider_modes")),
    }


def _primary_channel(
    channel_routes: dict[str, Any],
    *,
    layers: list[LayerDecision],
    requested_channel: str,
) -> dict[str, Any]:
    routes = _dict_value(channel_routes.get("routes"))
    requested = _valid_channel(requested_channel)
    model_guess = None
    for layer in reversed(layers):
        model_guess = _valid_channel(_dict_value(layer.payload.get("model_output")).get("channel_guess"))
        if model_guess:
            break
    if model_guess == "both":
        model_guess = None
    candidates = []
    for key, route in routes.items():
        if not isinstance(route, dict):
            continue
        score = _bounded_score(route.get("score"))
        boost = 6 if key == model_guess else 0
        if requested and requested != "both" and key == requested:
            boost += 4
        candidates.append((score + boost, key, route))
    if candidates:
        _score, key, route = max(candidates, key=lambda item: item[0])
        return {
            "channel": key,
            "label": route.get("label") or _channel_label(key),
            "score": route.get("score"),
            "verdict": route.get("verdict"),
            "source": "channel_signals_plus_ai_guess",
        }
    fallback = requested or model_guess or "amazon"
    return {
        "channel": fallback,
        "label": _channel_label(fallback),
        "score": None,
        "verdict": "review",
        "source": "fallback",
    }


def _valid_channel(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"amazon", "dtc_ad", "dtc_seo", "both"}:
        return normalized
    return None


def _channel_label(value: str) -> str:
    return {
        "amazon": "亚马逊",
        "dtc_ad": "独立站广告",
        "dtc_seo": "独立站 SEO",
        "both": "双平台",
    }.get(value, value)


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
        "channel_signals": payload.get("channel_signals"),
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
