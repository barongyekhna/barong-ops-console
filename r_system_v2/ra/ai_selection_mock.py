"""Mock multi-AI product-selection pipeline for R-A.

This module intentionally does not resolve or call any external AI provider.
It simulates the documented DeepSeek -> GPT -> Opus review chain with
deterministic local scoring so R-A can exercise persistence, UI, and workflow
shape before real model keys are connected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from r_system_v2.ra.channel_signals import ensure_channel_signals
from r_system_v2.ra.profit_engine import decimal_value
from r_system_v2.ra.profit_service import _json_bind
from r_system_v2.ra.skill_loader import RASkillBundle, load_ra_skill_bundle


MOCK_PIPELINE_VERSION = "ra_multi_ai_mock_v1"
MOCK_LAYERS = ("deepseek", "gpt", "opus")


@dataclass(frozen=True)
class MockLayerDecision:
    layer: str
    model_role: str
    model_name: str
    score: int
    verdict: str
    reason: str
    risks: list[str]
    advantages: list[str]
    payload: dict[str, Any]


def run_mock_ai_selection_for_run(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    channel: str = "amazon",
) -> dict[str, object]:
    """Run the local three-layer AI mock for all candidates in one R-A run."""

    candidates = _load_candidate_contexts(db, org_id=org_id, run_id=run_id)
    skill_bundle = load_ra_skill_bundle(channel)
    _clear_mock_outputs(db, org_id=org_id, run_id=run_id)
    counts = {
        "ai_candidates": len(candidates),
        "ai_evaluations": 0,
        "ai_pass": 0,
        "ai_reject": 0,
        "ai_review": 0,
        "final_decisions": 0,
        "reports": 0,
        "mock_ai_enabled": True,
        "mock_ai_version": MOCK_PIPELINE_VERSION,
        "channel_signals": 0,
    }

    for context in candidates:
        context["channel_signals"] = ensure_channel_signals(
            db,
            org_id=org_id,
            run_id=run_id,
            context=context,
            competition={},
        )
        counts["channel_signals"] += 1
        layers = _evaluate_mock_layers(context, skill_bundle=skill_bundle)
        for layer in layers:
            _insert_ai_evaluation(db, org_id=org_id, run_id=run_id, context=context, layer=layer)
            counts["ai_evaluations"] += 1
        final = _final_decision(context, layers, channel=channel, skill_bundle=skill_bundle)
        final["report_id"] = str(uuid4())
        _insert_final_decision(db, org_id=org_id, run_id=run_id, context=context, final=final)
        _insert_report(db, org_id=org_id, run_id=run_id, context=context, final=final, layers=layers)
        _update_candidate_status(db, candidate_id=str(context["candidate_id"]), verdict=str(final["verdict"]))
        verdict_key = {
            "pass": "ai_pass",
            "reject": "ai_reject",
            "review": "ai_review",
        }.get(str(final["verdict"]), "ai_review")
        counts[verdict_key] += 1
        counts["final_decisions"] += 1
        counts["reports"] += 1

    _merge_run_counts(db, run_id=run_id, counts=counts)
    db.commit()
    return load_mock_ai_selection_for_run(db, org_id=org_id, run_id=run_id)


def run_mock_ai_selection_for_candidate(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    candidate_id: str,
    channel: str = "amazon",
) -> dict[str, object]:
    normalized_candidate_id = str(candidate_id or "").strip()
    if not normalized_candidate_id:
        raise RuntimeError("缺少 R-A candidate_id，无法启动 mock AI 链。")
    candidates = [
        context
        for context in _load_candidate_contexts(db, org_id=org_id, run_id=run_id)
        if str(context.get("candidate_id") or "") == normalized_candidate_id
    ]
    if not candidates:
        raise RuntimeError("利润通过候选不存在或尚未满足 mock AI 输入条件。")
    skill_bundle = load_ra_skill_bundle(channel)
    _clear_mock_outputs_for_candidate(
        db,
        org_id=org_id,
        run_id=run_id,
        candidate_id=normalized_candidate_id,
    )
    counts = {
        "ai_candidates": len(candidates),
        "ai_evaluations": 0,
        "ai_pass": 0,
        "ai_reject": 0,
        "ai_review": 0,
        "final_decisions": 0,
        "reports": 0,
        "mock_ai_enabled": True,
        "mock_ai_version": MOCK_PIPELINE_VERSION,
        "channel_signals": 0,
    }
    for context in candidates:
        context["channel_signals"] = ensure_channel_signals(
            db,
            org_id=org_id,
            run_id=run_id,
            context=context,
            competition={},
        )
        counts["channel_signals"] += 1
        layers = _evaluate_mock_layers(context, skill_bundle=skill_bundle)
        for layer in layers:
            _insert_ai_evaluation(db, org_id=org_id, run_id=run_id, context=context, layer=layer)
            counts["ai_evaluations"] += 1
        final = _final_decision(context, layers, channel=channel, skill_bundle=skill_bundle)
        final["report_id"] = str(uuid4())
        _insert_final_decision(db, org_id=org_id, run_id=run_id, context=context, final=final)
        _insert_report(db, org_id=org_id, run_id=run_id, context=context, final=final, layers=layers)
        _update_candidate_status(db, candidate_id=str(context["candidate_id"]), verdict=str(final["verdict"]))
        verdict_key = {
            "pass": "ai_pass",
            "reject": "ai_reject",
            "review": "ai_review",
        }.get(str(final["verdict"]), "ai_review")
        counts[verdict_key] += 1
        counts["final_decisions"] += 1
        counts["reports"] += 1
    _merge_run_counts(db, run_id=run_id, counts=counts)
    db.commit()
    return load_mock_ai_selection_for_run(db, org_id=org_id, run_id=run_id)


def load_mock_ai_selection_for_run(
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
                "mock_pipeline_version": payload.get("mock_pipeline_version"),
                "channel_routes": payload.get("channel_routes"),
                "primary_channel": payload.get("primary_channel"),
                "created_at": _iso(decision.get("created_at")),
            }
        )
    counts["reports"] = _report_count(db, org_id=org_id, run_id=run_id)
    return {
        "run_id": run_id,
        "runtime_mode": "mock_multi_ai",
        "mock": True,
        "mock_pipeline_version": MOCK_PIPELINE_VERSION,
        "items": items,
        "counts": counts,
    }


def load_mock_ai_selection_by_candidate(
    db: Session,
    *,
    org_id: str,
    run_id: str,
) -> dict[str, dict[str, object]]:
    summary = load_mock_ai_selection_for_run(db, org_id=org_id, run_id=run_id)
    output: dict[str, dict[str, object]] = {}
    for item in summary.get("items") or []:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        if candidate_id:
            output[candidate_id] = item
    return output


AI_DONE_CANDIDATE_STATUSES = (
    "profit_passed",
    "ai_passed",
    "ai_rejected",
    "ai_review",
    "ai_mock_passed",
    "ai_mock_rejected",
    "ai_mock_review",
)


def _load_candidate_contexts(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    statuses: tuple[str, ...] = ("profit_passed",),
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT c.id AS candidate_id, c.source_asin, c.title AS candidate_title,
                   c.title_zh AS candidate_title_zh, c.candidate_status,
                   c.snapshot AS candidate_snapshot,
                   p.asin, p.marketplace, p.source_query, p.title, p.title_zh,
                   p.image_url, p.brand, p.category, p.category_id, p.category_path,
                   p.price, p.bsr, p.reviews, p.seller_count, p.rating,
                   p.skill_score, p.fulfillment_method, p.lithium_battery_warning,
                   p.features
            FROM ra_candidates c
            LEFT JOIN products_rw p ON p.asin = c.source_asin
            WHERE c.org_id = :org_id AND c.run_id = :run_id
              AND c.candidate_status IN :statuses
            ORDER BY c.created_at ASC
            """
        ).bindparams(bindparam("statuses", expanding=True)),
        {"org_id": org_id, "run_id": run_id, "statuses": list(statuses)},
    ).mappings()
    contexts: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        snapshot = _dict_value(data.get("candidate_snapshot"))
        product = {
            "asin": data.get("asin") or data.get("source_asin") or snapshot.get("asin"),
            "marketplace": data.get("marketplace") or snapshot.get("marketplace") or "US",
            "source_query": data.get("source_query") or snapshot.get("source_query"),
            "title": data.get("title") or data.get("candidate_title") or snapshot.get("title"),
            "title_zh": data.get("title_zh")
            or data.get("candidate_title_zh")
            or snapshot.get("title_zh"),
            "image_url": data.get("image_url") or snapshot.get("image_url"),
            "brand": data.get("brand") or snapshot.get("brand"),
            "category": data.get("category") or snapshot.get("category"),
            "category_id": data.get("category_id") or snapshot.get("category_id"),
            "category_path": data.get("category_path") or snapshot.get("category_path"),
            "price": data.get("price") or snapshot.get("price"),
            "bsr": data.get("bsr") or snapshot.get("bsr"),
            "reviews": data.get("reviews") or snapshot.get("reviews"),
            "rating": data.get("rating") or snapshot.get("rating"),
            "skill_score": data.get("skill_score") or snapshot.get("skill_score"),
            "fulfillment_method": data.get("fulfillment_method") or snapshot.get("fulfillment_method"),
            "lithium_battery_warning": data.get("lithium_battery_warning")
            if data.get("lithium_battery_warning") is not None
            else snapshot.get("lithium_battery_warning"),
            "features": _dict_value(data.get("features")) or _dict_value(snapshot.get("features")),
        }
        contexts.append(
            {
                "candidate_id": str(data["candidate_id"]),
                "asin": product["asin"],
                "candidate_status": data.get("candidate_status"),
                "product": product,
                "profit": {},
                "supplier": {},
            }
        )
    _attach_latest_profit_snapshots(db, org_id=org_id, run_id=run_id, contexts=contexts)
    _attach_supplier_fallbacks(db, org_id=org_id, run_id=run_id, contexts=contexts)
    return contexts


def _attach_latest_profit_snapshots(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    contexts: list[dict[str, Any]],
) -> None:
    by_candidate = {str(item["candidate_id"]): item for item in contexts}
    rows = db.execute(
        text(
            """
            SELECT s.candidate_id, s.id AS snapshot_id, s.asin,
                   s.sell_price_usd, s.net_profit_usd, s.net_margin, s.roi,
                   s.confidence, s.payload, s.created_at
            FROM ra_profit_snapshots s
            JOIN ra_candidates c ON c.id = s.candidate_id
            WHERE c.org_id = :org_id AND c.run_id = :run_id
            ORDER BY s.created_at DESC
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings()
    seen: set[str] = set()
    for row in rows:
        candidate_id = str(row["candidate_id"])
        if candidate_id in seen or candidate_id not in by_candidate:
            continue
        seen.add(candidate_id)
        payload = _dict_value(row.get("payload"))
        by_candidate[candidate_id]["profit"] = {
            "snapshot_id": row.get("snapshot_id"),
            "sell_price_usd": row.get("sell_price_usd"),
            "gross_profit_usd": payload.get("gross_profit_usd") or row.get("net_profit_usd"),
            "gross_margin": payload.get("gross_margin") or row.get("net_margin"),
            "roi": payload.get("roi") or row.get("roi"),
            "verdict": payload.get("verdict"),
            "warnings": payload.get("warnings") or [],
            "blocked_reasons": payload.get("blocked_reasons") or [],
            "confidence": row.get("confidence"),
        }
        by_candidate[candidate_id]["supplier"] = _dict_value(payload.get("supplier"))


def _attach_supplier_fallbacks(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    contexts: list[dict[str, Any]],
) -> None:
    by_candidate = {
        str(item["candidate_id"]): item
        for item in contexts
        if not _dict_value(item.get("supplier"))
    }
    if not by_candidate:
        return
    rows = db.execute(
        text(
            """
            SELECT o.candidate_id, o.id AS offer_id, o.supplier_name,
                   o.supplier_url, o.unit_price_cny, o.moq, o.rating,
                   o.match_score, o.offer_status, o.payload
            FROM ra_supplier_offers o
            JOIN ra_candidates c ON c.id = o.candidate_id
            WHERE c.org_id = :org_id AND c.run_id = :run_id
            ORDER BY o.match_score DESC NULLS LAST, o.unit_price_cny ASC NULLS LAST,
                     o.created_at ASC
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings()
    seen: set[str] = set()
    for row in rows:
        candidate_id = str(row["candidate_id"])
        if candidate_id in seen or candidate_id not in by_candidate:
            continue
        seen.add(candidate_id)
        payload = _dict_value(row.get("payload"))
        by_candidate[candidate_id]["supplier"] = {
            "offer_id": row.get("offer_id"),
            "supplier_name": row.get("supplier_name"),
            "supplier_url": row.get("supplier_url"),
            "unit_price_cny": _number(row.get("unit_price_cny")),
            "moq": row.get("moq"),
            "rating": _number(row.get("rating")),
            "match_score": row.get("match_score"),
            "offer_status": row.get("offer_status"),
            "one_piece_hint": bool(payload.get("one_piece_hint")),
            "supplier_alignment": payload.get("supplier_alignment"),
        }


def _evaluate_mock_layers(
    context: dict[str, Any],
    *,
    skill_bundle: RASkillBundle | None = None,
) -> list[MockLayerDecision]:
    bundle = skill_bundle or load_ra_skill_bundle("amazon")
    deepseek = _deepseek_layer(context, skill_bundle=bundle)
    layers = [deepseek]
    if deepseek.verdict == "reject":
        return layers
    gpt = _gpt_layer(context, deepseek, skill_bundle=bundle)
    layers.append(gpt)
    if gpt.verdict == "reject":
        return layers
    opus = _opus_layer(context, deepseek, gpt, skill_bundle=bundle)
    layers.append(opus)
    return layers


def _deepseek_layer(
    context: dict[str, Any],
    *,
    skill_bundle: RASkillBundle,
) -> MockLayerDecision:
    product = _dict_value(context.get("product"))
    features = _dict_value(product.get("features"))
    profit = _dict_value(context.get("profit"))
    score = 48
    advantages: list[str] = []
    risks: list[str] = []

    monthly_sales = _int_value(
        features.get("monthly_sales_value")
        or features.get("monthly_sales")
        or features.get("monthly_sales_estimate")
        or features.get("sales_estimate_30d")
    )
    if monthly_sales >= 500:
        score += 18
        advantages.append(f"月销量约 {monthly_sales}，需求强。")
    elif monthly_sales >= 150:
        score += 12
        advantages.append(f"月销量约 {monthly_sales}，需求可验证。")
    elif monthly_sales >= 50:
        score += 7
        advantages.append(f"月销量约 {monthly_sales}，有基础需求。")
    else:
        score -= 8
        risks.append("月销量不足或缺失，需求置信度偏低。")

    bsr = _int_value(product.get("bsr") or features.get("subcategory_rank"))
    if 0 < bsr <= 5000:
        score += 9
        advantages.append(f"BSR {bsr}，类目动销较好。")
    elif 0 < bsr <= 30000:
        score += 5
        advantages.append(f"BSR {bsr}，仍有动销基础。")
    elif bsr > 0:
        score -= 5
        risks.append(f"BSR {bsr} 偏后，需求需要复核。")

    reviews = _int_value(product.get("reviews"))
    if 30 <= reviews <= 1200:
        score += 7
        advantages.append(f"评论数 {reviews}，不是明显红海。")
    elif reviews > 3000:
        score -= 6
        risks.append(f"评论数 {reviews} 偏高，头部壁垒强。")
    elif reviews < 10:
        score -= 3
        risks.append("评论样本太少，需求稳定性待验证。")

    price = decimal_value(product.get("price"))
    if price is not None and Decimal("25") <= price <= Decimal("70"):
        score += 7
        advantages.append("售价处在 25-70 美金主力区间。")
    else:
        score -= 7
        risks.append("售价不在 R 系列主力价格区间。")

    if str(profit.get("verdict")) == "pass":
        score += 10
        advantages.append("利润引擎初步通过。")
    elif str(profit.get("verdict")) == "reject":
        score -= 12
        risks.append("利润引擎未通过，后续难以推进。")
    elif not profit:
        score -= 6
        risks.append("缺少利润快照，无法确认毛利结构。")

    if _bool_value(product.get("lithium_battery_warning")):
        score -= 3
        risks.append("含锂电提示，后续合规和物流需复核。")

    return _layer_decision(
        layer="deepseek",
        model_name="mock-deepseek-v4-pro",
        score=score,
        advantages=advantages,
        risks=risks,
        reason="DeepSeek mock 完成需求、价格、竞争和利润硬指标量化。",
        context=context,
        skill_bundle=skill_bundle,
    )


def _gpt_layer(
    context: dict[str, Any],
    deepseek: MockLayerDecision,
    *,
    skill_bundle: RASkillBundle,
) -> MockLayerDecision:
    product = _dict_value(context.get("product"))
    supplier = _dict_value(context.get("supplier"))
    features = _dict_value(product.get("features"))
    score = deepseek.score - 2
    advantages: list[str] = []
    risks: list[str] = []

    image_candidates = features.get("image_candidates")
    if isinstance(image_candidates, list) and image_candidates:
        score += 4
        advantages.append("图片候选完整，便于款式复核。")
    elif product.get("image_url"):
        score += 2
        advantages.append("已有主图，可做基础视觉判断。")
    else:
        score -= 6
        risks.append("缺少有效图片，款式判断不可靠。")

    title_text = " ".join(
        str(value or "")
        for value in (product.get("title"), product.get("title_zh"))
    ).lower()
    if any(word in title_text for word in ("replacement", "refill", "parts", "accessory only")):
        score -= 8
        risks.append("标题疑似配件/替换件，需确认是否为完整产品。")
    else:
        score += 4
        advantages.append("标题未出现明显配件化风险。")

    match_score = _int_value(supplier.get("match_score"))
    if match_score >= 80:
        score += 7
        advantages.append(f"供应商匹配分 {match_score}，成本来源可信度较高。")
    elif match_score > 0:
        score -= 3
        risks.append(f"供应商匹配分 {match_score} 偏低，需要人工比对。")
    else:
        score -= 8
        risks.append("缺少供应商匹配分。")

    rating = decimal_value(product.get("rating"))
    if rating is not None and rating >= Decimal("4.2"):
        score += 4
        advantages.append(f"Amazon 评分 {rating}，用户接受度尚可。")
    elif rating is not None and rating < Decimal("4.0"):
        score -= 5
        risks.append(f"Amazon 评分 {rating} 偏低，可能存在质量痛点。")

    return _layer_decision(
        layer="gpt",
        model_name="mock-gpt-5.6-luna",
        score=score,
        advantages=advantages,
        risks=risks,
        reason="GPT mock 完成 listing、图片、供应商匹配和差异化风险复核。",
        context=context,
        skill_bundle=skill_bundle,
    )


def _opus_layer(
    context: dict[str, Any],
    deepseek: MockLayerDecision,
    gpt: MockLayerDecision,
    *,
    skill_bundle: RASkillBundle,
) -> MockLayerDecision:
    profit = _dict_value(context.get("profit"))
    supplier = _dict_value(context.get("supplier"))
    gross_margin = decimal_value(profit.get("gross_margin"))
    score = round((deepseek.score * 0.35) + (gpt.score * 0.35) + 20)
    advantages: list[str] = []
    risks: list[str] = []

    if gross_margin is not None and gross_margin >= Decimal("0.30"):
        score += 10
        advantages.append(f"毛利率约 {float(gross_margin) * 100:.1f}%，适合继续验证。")
    elif gross_margin is not None and gross_margin >= Decimal("0.20"):
        score += 3
        risks.append(f"毛利率约 {float(gross_margin) * 100:.1f}%，只能进入谨慎复核。")
    else:
        score -= 10
        risks.append("毛利率缺失或低于 20%，暂不建议进入下一轮。")

    if _bool_value(supplier.get("one_piece_hint")) or _int_value(supplier.get("moq")) == 1:
        score += 5
        advantages.append("供应商支持一件代发/一件起批，适合小卖家冷启动。")
    else:
        risks.append("供应商 MOQ 或一件代发状态不明确。")

    if str(profit.get("verdict")) == "reject":
        score = min(score, 54)
        risks.append("利润引擎拒绝，Opus mock 不允许直接通过。")

    return _layer_decision(
        layer="opus",
        model_name="mock-claude-opus-4-thinking",
        score=score,
        advantages=advantages,
        risks=risks,
        reason="Opus mock 从小卖家冷启动视角做最终进入/复核/淘汰判断。",
        context=context,
        skill_bundle=skill_bundle,
    )


def _layer_decision(
    *,
    layer: str,
    model_name: str,
    score: int,
    advantages: list[str],
    risks: list[str],
    reason: str,
    context: dict[str, Any],
    skill_bundle: RASkillBundle,
) -> MockLayerDecision:
    bounded = _bounded_score(score)
    verdict = "pass" if bounded >= 72 else "review" if bounded >= 58 else "reject"
    skill_payload = _skill_payload(skill_bundle)
    payload = {
        "mock": True,
        "mock_pipeline_version": MOCK_PIPELINE_VERSION,
        "skill_version": skill_bundle.version,
        "skill_hash": skill_bundle.combined_hash,
        "skill": skill_payload,
        "asin": context.get("asin"),
        "score": bounded,
        "verdict": verdict,
        "reason": reason,
        "advantages": advantages[:6],
        "risks": risks[:6],
        "input_summary": _input_summary(context),
        "channel_signals": _channel_signals_payload(context),
    }
    return MockLayerDecision(
        layer=layer,
        model_role=layer,
        model_name=model_name,
        score=bounded,
        verdict=verdict,
        reason=reason,
        risks=risks[:6],
        advantages=advantages[:6],
        payload=payload,
    )


def _final_decision(
    context: dict[str, Any],
    layers: list[MockLayerDecision],
    *,
    channel: str,
    skill_bundle: RASkillBundle | None = None,
) -> dict[str, Any]:
    bundle = skill_bundle or load_ra_skill_bundle(channel)
    scores = [layer.score for layer in layers]
    average_score = round(sum(scores) / max(1, len(scores)))
    profit = _dict_value(context.get("profit"))
    hard_reasons: list[str] = []
    if str(profit.get("verdict")) == "reject":
        hard_reasons.append("利润引擎未通过。")
    completed_layers = {layer.layer for layer in layers}
    if "gpt" not in completed_layers:
        hard_reasons.append("DeepSeek 第一层未放行，按漏斗规则未进入 GPT/Opus。")
    elif "opus" not in completed_layers:
        hard_reasons.append("GPT 第二层未放行，按漏斗规则未进入 Opus。")
    if any(layer.verdict == "reject" and layer.score < 50 for layer in layers):
        hard_reasons.append("至少一层 AI mock 给出强拒绝。")
    if hard_reasons:
        verdict = "reject"
        final_score = min(average_score, 54)
        barrier_type = "profit" if str(profit.get("verdict")) == "reject" else "ai_risk"
    elif average_score >= 72 and all(layer.verdict != "reject" for layer in layers):
        verdict = "pass"
        final_score = average_score
        barrier_type = "none"
    else:
        verdict = "review"
        final_score = average_score
        barrier_type = "manual_review"

    channel_routes = _channel_routes_from_context(context, requested_channel=channel)
    primary_channel = _primary_channel(channel_routes, requested_channel=channel)
    leading_advantages = _dedupe(
        advantage
        for layer in layers
        for advantage in layer.advantages
    )[:4]
    leading_risks = _dedupe(
        risk
        for layer in layers
        for risk in layer.risks
    )[:4]
    if verdict == "pass":
        reason = "通过 mock 三层评审：需求、竞争、供应商和利润结构均达到进入 R-A 下一步的最低线。"
    elif verdict == "reject":
        reason = "mock 三层评审淘汰：" + "；".join(hard_reasons or leading_risks or ["核心指标不足"])
    else:
        reason = "进入人工复核：部分指标可用，但仍存在需要人工确认的利润、供应商或需求风险。"

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
        "mock_pipeline_version": MOCK_PIPELINE_VERSION,
        "skill_version": bundle.version,
        "skill_hash": bundle.combined_hash,
        "skill": _skill_payload(bundle),
        "channel_signals": _channel_signals_payload(context),
        "created_at": datetime.now(UTC).isoformat(),
    }


def _insert_ai_evaluation(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    context: dict[str, Any],
    layer: MockLayerDecision,
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
            "payload": json.dumps(layer.payload, ensure_ascii=False),
            "in_tokens": 0,
            "out_tokens": 0,
            "cost_usd": Decimal("0.0000"),
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
        "mock": True,
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
            "payload": json.dumps(payload, ensure_ascii=False),
        },
    )


def _insert_report(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    context: dict[str, Any],
    final: dict[str, Any],
    layers: list[MockLayerDecision],
) -> None:
    report_id = str(final.get("report_id") or uuid4())
    product = _dict_value(context.get("product"))
    title = product.get("title_zh") or product.get("title") or context.get("asin")
    summary = f"{title}：{final['decision_reason']}"
    payload = {
        "mock": True,
        "mock_pipeline_version": MOCK_PIPELINE_VERSION,
        "skill_version": final.get("skill_version"),
        "skill_hash": final.get("skill_hash"),
        "skill": final.get("skill"),
        "final": final,
        "layers": [layer.payload for layer in layers],
        "product": _input_summary(context),
        "channel_routes": final.get("channel_routes"),
        "primary_channel": final.get("primary_channel"),
        "channel_signals": _channel_signals_payload(context),
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
              'mock_ready', :title, :summary, {_json_bind(db, "payload")}
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
            "payload": json.dumps(payload, ensure_ascii=False),
        },
    )


def _update_candidate_status(db: Session, *, candidate_id: str, verdict: str) -> None:
    status = {
        "pass": "ai_mock_passed",
        "reject": "ai_mock_rejected",
        "review": "ai_mock_review",
    }.get(verdict, "ai_mock_review")
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


def _clear_mock_outputs(db: Session, *, org_id: str, run_id: str) -> None:
    db.execute(
        text(
            """
            DELETE FROM ra_ai_evaluations
            WHERE org_id = :org_id AND run_id = :run_id
              AND layer IN ('deepseek', 'gpt', 'opus')
              AND model_name LIKE 'mock-%'
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
            WHERE org_id = :org_id AND run_id = :run_id AND status = 'mock_ready'
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    )


def _clear_mock_outputs_for_candidate(
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
                runtime_mode = 'background_profit_queue_ai_mock',
                updated_at = CURRENT_TIMESTAMP
            WHERE run_id = :run_id
            """
        ),
        {"run_id": run_id, "counts": json.dumps(existing, ensure_ascii=False)},
    )


def _load_final_decisions(db: Session, *, org_id: str, run_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT id, candidate_id, asin, final_score, verdict, channel,
                   barrier_type, decision_reason, payload, created_at
            FROM ra_final_decisions
            WHERE org_id = :org_id AND run_id = :run_id
            ORDER BY final_score DESC NULLS LAST, created_at DESC
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings()
    return [dict(row) for row in rows]


def _load_evaluations_by_candidate(
    db: Session,
    *,
    org_id: str,
    run_id: str,
) -> dict[str, list[dict[str, object]]]:
    rows = db.execute(
        text(
            """
            SELECT candidate_id, layer, model_role, model_name, score, verdict,
                   payload, created_at
            FROM ra_ai_evaluations
            WHERE org_id = :org_id AND run_id = :run_id
              AND layer IN ('prescreen', 'deepseek', 'gpt', 'opus')
            ORDER BY created_at ASC
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings()
    output: dict[str, list[dict[str, object]]] = {}
    order = {"prescreen": -1}
    order.update({layer: index for index, layer in enumerate(MOCK_LAYERS)})
    for row in rows:
        candidate_id = str(row["candidate_id"] or "")
        payload = _dict_value(row.get("payload"))
        output.setdefault(candidate_id, []).append(
            {
                "layer": row.get("layer"),
                "model_role": row.get("model_role"),
                "model_name": row.get("model_name"),
                "score": row.get("score"),
                "verdict": row.get("verdict"),
                "reason": payload.get("reason"),
                "advantages": payload.get("advantages") or [],
                "risks": payload.get("risks") or [],
                "created_at": _iso(row.get("created_at")),
            }
        )
    for items in output.values():
        items.sort(key=lambda item: order.get(str(item.get("layer")), 99))
    return output


def _report_count(db: Session, *, org_id: str, run_id: str) -> int:
    row = db.execute(
        text(
            """
            SELECT COUNT(*) AS count
            FROM ra_reports
            WHERE org_id = :org_id AND run_id = :run_id AND status = 'mock_ready'
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings().first()
    return int(row["count"] or 0) if row else 0


def _skill_payload(skill_bundle: RASkillBundle) -> dict[str, Any]:
    return {
        "name": skill_bundle.name,
        "version": skill_bundle.version,
        "channel": skill_bundle.channel,
        "combined_hash": skill_bundle.combined_hash,
        "file_keys": [item.key for item in skill_bundle.files],
        "files": [
            {
                "key": item.key,
                "filename": item.filename,
                "sha256": item.sha256,
                "bytes": item.bytes,
            }
            for item in skill_bundle.files
        ],
        "prompt_char_count": len(skill_bundle.prompt_text),
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


def _channel_routes_from_context(
    context: dict[str, Any],
    *,
    requested_channel: str,
) -> dict[str, Any]:
    signals = _channel_signals_payload(context)
    routes: dict[str, Any] = {}
    for key in ("amazon", "dtc_ad", "dtc_seo"):
        route = _dict_value(signals.get(key))
        if not route:
            continue
        routes[key] = {
            "label": route.get("label"),
            "score": route.get("score"),
            "verdict": route.get("verdict"),
            "reasons": route.get("reasons") or [],
            "risks": route.get("risks") or [],
            "provider_mode": route.get("provider_mode"),
        }
    return {
        "requested_channel": _valid_channel(requested_channel) or "both",
        "routes": routes,
        "model_channel_guesses": [],
        "provider_modes": _dict_value(signals.get("provider_modes")),
    }


def _primary_channel(
    channel_routes: dict[str, Any],
    *,
    requested_channel: str,
) -> dict[str, Any]:
    routes = _dict_value(channel_routes.get("routes"))
    candidates = []
    requested = _valid_channel(requested_channel)
    for key, route in routes.items():
        if not isinstance(route, dict):
            continue
        score = _bounded_score(route.get("score") or 0)
        if requested and requested != "both" and key == requested:
            score += 4
        candidates.append((score, key, route))
    if candidates:
        _score, key, route = max(candidates, key=lambda item: item[0])
        return {
            "channel": key,
            "label": route.get("label") or _channel_label(key),
            "score": route.get("score"),
            "verdict": route.get("verdict"),
            "source": "mock_channel_signals",
        }
    fallback = requested or "amazon"
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


def _input_summary(context: dict[str, Any]) -> dict[str, Any]:
    product = _dict_value(context.get("product"))
    profit = _dict_value(context.get("profit"))
    supplier = _dict_value(context.get("supplier"))
    features = _dict_value(product.get("features"))
    return {
        "asin": context.get("asin"),
        "title": product.get("title"),
        "title_zh": product.get("title_zh"),
        "category": product.get("category"),
        "price": _number(product.get("price")),
        "bsr": _int_value(product.get("bsr")),
        "reviews": _int_value(product.get("reviews")),
        "rating": _number(product.get("rating")),
        "monthly_sales": _int_value(
            features.get("monthly_sales_value")
            or features.get("monthly_sales")
            or features.get("monthly_sales_estimate")
            or features.get("sales_estimate_30d")
        ),
        "profit_verdict": profit.get("verdict"),
        "gross_margin": _number(profit.get("gross_margin")),
        "gross_profit_usd": _number(profit.get("gross_profit_usd")),
        "supplier_name": supplier.get("supplier_name"),
        "supplier_match_score": _int_value(supplier.get("match_score")),
        "primary_channel": _dict_value(_channel_signals_payload(context).get("primary_route")).get("channel"),
    }


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _number(value: Any) -> float | None:
    parsed = decimal_value(value)
    return float(parsed) if parsed is not None else None


def _int_value(value: Any) -> int:
    parsed = decimal_value(value)
    if parsed is None:
        return 0
    return int(parsed)


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _bounded_score(value: int | float | Decimal) -> int:
    return max(0, min(100, int(round(float(value)))))


def _dedupe(values: Any) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text_value = str(value or "").strip()
        if not text_value or text_value in seen:
            continue
        seen.add(text_value)
        output.append(text_value)
    return output


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return str(value)
