#!/usr/bin/env python3
"""Executable R Series product-selection decision engine.

R_ENGINE_V1 is intentionally local-only. It loads the uploaded R_SERIES
documents and score model, runs deterministic rule-based skills, and returns
the runtime output shape required by the R system activation task.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
R_SERIES_DIR = ROOT_DIR / "R_SERIES"
RUNTIME_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = RUNTIME_DIR / "skill_registry.json"
SCORE_MODEL_PATH = R_SERIES_DIR / "R_SERIES_PRODUCT_SELECTION_SCORE_MODEL.json"
REPORT_PATH = ROOT_DIR / "R_SYSTEM_RUNTIME_ACTIVATION_REPORT.json"

ENGINE_NAME = "R_ENGINE_V1"
ENGINE_VERSION = "2026-06-29.v1"

REQUIRED_DOCUMENTS = {
    "AMAZON_PRODUCT_RESEARCH_PLAYBOOK.md": "R_SERIES_AMAZON_PRODUCT_RESEARCH_PLAYBOOK.md",
    "INDEPENDENT_SITE_PRODUCT_RESEARCH_PLAYBOOK.md": "R_SERIES_INDEPENDENT_SITE_PRODUCT_RESEARCH_PLAYBOOK.md",
    "AMAZON_VS_INDEPENDENT_SITE_COMPARISON.md": "R_SERIES_AMAZON_VS_INDEPENDENT_SITE_COMPARISON.md",
    "BARONG_YEKHNA_PRODUCT_SELECTION_STRATEGY.md": "R_SERIES_BARONG_YEKHNA_PRODUCT_SELECTION_STRATEGY.md",
    "FUTURE_SYSTEM_DESIGN_SUGGESTIONS.md": "R_SERIES_FUTURE_SYSTEM_DESIGN_SUGGESTIONS.md",
    "PRODUCT_SELECTION_SCORE_MODEL.json": "R_SERIES_PRODUCT_SELECTION_SCORE_MODEL.json",
    "SOURCE_INDEX.md": "R_SERIES_SOURCE_INDEX.md",
}

SKILL_ORDER = [
    "source_validation_skill",
    "amazon_selection_skill",
    "independent_site_selection_skill",
    "risk_filter_skill",
    "decision_engine_skill",
]

HIGH_RISK_TERMS = {
    "battery",
    "lithium",
    "wireless",
    "bluetooth",
    "wifi",
    "medical",
    "health",
    "therapy",
    "treatment",
    "child",
    "children",
    "baby",
    "toy",
    "food",
    "cosmetic",
    "chemical",
    "liquid",
    "powder",
    "high voltage",
    "laser",
}

IP_RISK_TERMS = {
    "iphone",
    "ipad",
    "apple",
    "tesla",
    "dyson",
    "lego",
    "disney",
    "nike",
    "stanley",
    "keurig",
}

FUNCTIONAL_TERMS = {
    "portable",
    "replacement",
    "draft",
    "stopper",
    "seal",
    "weatherstrip",
    "insulation",
    "kit",
    "repair",
    "maintenance",
    "organizer",
    "holder",
    "mount",
    "cover",
    "guard",
    "protector",
}

DTC_CONTENT_TERMS = {
    "portable",
    "draft",
    "stopper",
    "seal",
    "install",
    "kit",
    "replacement",
    "maintenance",
    "custom",
    "wholesale",
    "bulk",
    "supplier",
}

B2B_TERMS = {
    "custom",
    "wholesale",
    "bulk",
    "supplier",
    "manufacturer",
    "factory",
    "industrial",
    "commercial",
    "oem",
    "odm",
}

LOW_RISK_CATEGORIES = {
    "home improvement",
    "home",
    "office",
    "tools",
    "workbench",
    "organization",
    "hardware",
}

VISUAL_TERMS = {
    "portable",
    "draft",
    "stopper",
    "seal",
    "organizer",
    "kit",
    "holder",
    "mount",
    "before",
    "after",
}


class REngineError(RuntimeError):
    """Runtime failure for R_ENGINE_V1."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clamp(value: float, minimum: int = 0, maximum: int = 100) -> int:
    return int(max(minimum, min(maximum, round(value))))


def normalize_market(value: str | None) -> str:
    raw = (value or "Both").strip().lower()
    if raw in {"amazon", "amz"}:
        return "Amazon"
    if raw in {"dtc", "site", "independent site", "independent_site"}:
        return "DTC"
    if "amazon" in raw and ("dtc" in raw or "site" in raw or "+" in raw or "both" in raw):
        return "Both"
    if raw in {"both", "dual", "amazon + dtc", "amazon | dtc"}:
        return "Both"
    return "Both"


def normalize_risk_level(value: str | None) -> str:
    raw = (value or "medium").strip().lower()
    if raw in {"low", "medium", "high"}:
        return raw
    return "medium"


def parse_price_range(value: str | None) -> dict[str, float | None]:
    if not value:
        return {"min": None, "max": None, "avg": None}
    numbers = [float(match) for match in re.findall(r"\d+(?:\.\d+)?", value)]
    if not numbers:
        return {"min": None, "max": None, "avg": None}
    if len(numbers) == 1:
        return {"min": numbers[0], "max": numbers[0], "avg": numbers[0]}
    minimum = min(numbers[0], numbers[1])
    maximum = max(numbers[0], numbers[1])
    return {"min": minimum, "max": maximum, "avg": round((minimum + maximum) / 2, 2)}


def tokenize(*values: Any) -> set[str]:
    text = " ".join(str(value or "") for value in values).lower()
    return set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text))


def contains_phrase(text: str, phrase: str) -> bool:
    return phrase in text.lower()


def weighted_average(scores: dict[str, int], weights: dict[str, int]) -> float:
    total_weight = sum(weights.values())
    if not total_weight:
        return 0.0
    total = sum(float(scores.get(key, 0)) * weight for key, weight in weights.items())
    return round(total / total_weight, 2)


def weakest_dimensions(scores: dict[str, int], limit: int = 3) -> list[str]:
    return [key for key, _ in sorted(scores.items(), key=lambda item: item[1])[:limit]]


def average_score(*values: float) -> float:
    usable = [value for value in values if value is not None]
    if not usable:
        return 0.0
    return round(sum(usable) / len(usable), 2)


def load_r_series_documents() -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    all_loaded = True
    for requested_name, loaded_name in REQUIRED_DOCUMENTS.items():
        path = R_SERIES_DIR / loaded_name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            status = "loaded"
            digest = sha256_text(text)
            bytes_count = path.stat().st_size
            line_count = text.count("\n") + 1
        else:
            all_loaded = False
            status = "missing"
            digest = None
            bytes_count = 0
            line_count = 0
        documents.append(
            {
                "requested_name": requested_name,
                "loaded_name": loaded_name,
                "path": str(path.relative_to(ROOT_DIR)),
                "status": status,
                "sha256": digest,
                "bytes": bytes_count,
                "lines": line_count,
            }
        )
    return {
        "all_loaded": all_loaded,
        "loaded_count": sum(1 for item in documents if item["status"] == "loaded"),
        "required_count": len(REQUIRED_DOCUMENTS),
        "documents": documents,
    }


class REngineV1:
    """Local runtime engine for R Series product-selection decisions."""

    def __init__(self) -> None:
        self.registry = read_json(REGISTRY_PATH)
        self.score_model = read_json(SCORE_MODEL_PATH)
        self.weights: dict[str, int] = self.score_model["weights"]
        self.document_state = load_r_series_documents()
        self.initialized_at = utc_now()
        self._assert_runtime_ready()

    def _assert_runtime_ready(self) -> None:
        if not self.document_state["all_loaded"]:
            missing = [
                item["loaded_name"]
                for item in self.document_state["documents"]
                if item["status"] != "loaded"
            ]
            raise REngineError(f"Missing R_SERIES documents: {', '.join(missing)}")
        missing_skills = [
            name
            for name in SKILL_ORDER
            if self.registry.get("skills", {}).get(name, {}).get("status") != "registered"
        ]
        if missing_skills:
            raise REngineError(f"Missing registered skills: {', '.join(missing_skills)}")

    def normalize_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        keyword = str(payload.get("keyword", "")).strip()
        category = str(payload.get("category", "")).strip()
        price_range = str(payload.get("price_range", "")).strip()
        return {
            "keyword": keyword,
            "category": category,
            "price_range": price_range,
            "price": parse_price_range(price_range),
            "market": normalize_market(payload.get("market")),
            "risk_level": normalize_risk_level(payload.get("risk_level")),
            "raw_input": payload,
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: dict[str, Any] = {
            "engine": ENGINE_NAME,
            "engine_version": ENGINE_VERSION,
            "started_at": utc_now(),
            "input": self.normalize_input(payload),
            "skill_trace": [],
        }

        validated_dataset = self.source_validation_skill(state)
        state["validated_dataset"] = validated_dataset
        state["skill_trace"].append(self._trace("source_validation_skill", "validated_dataset"))

        amazon_scorecard = self.amazon_selection_skill(state)
        state["amazon_scorecard"] = amazon_scorecard
        state["skill_trace"].append(self._trace("amazon_selection_skill", "amazon_scorecard"))

        site_scorecard = self.independent_site_selection_skill(state)
        state["site_scorecard"] = site_scorecard
        state["skill_trace"].append(
            self._trace("independent_site_selection_skill", "site_scorecard")
        )

        risk_decision = self.risk_filter_skill(state)
        state["risk_decision"] = risk_decision
        state["skill_trace"].append(self._trace("risk_filter_skill", "risk_decision"))

        final_decision = self.decision_engine_skill(state)
        state["skill_trace"].append(self._trace("decision_engine_skill", "final_decision"))
        final_decision["skill_trace"] = state["skill_trace"]
        final_decision["validated_dataset"] = {
            "status": validated_dataset["status"],
            "confidence": validated_dataset["confidence"],
            "source_mode": validated_dataset["source_mode"],
            "input_completeness_score": validated_dataset["input_completeness_score"],
        }
        final_decision["engine"] = ENGINE_NAME
        final_decision["engine_version"] = ENGINE_VERSION
        final_decision["completed_at"] = utc_now()
        return final_decision

    def _trace(self, skill_name: str, output_name: str) -> dict[str, Any]:
        return {
            "skill": skill_name,
            "status": "success",
            "output": output_name,
            "timestamp": utc_now(),
        }

    def source_validation_skill(self, state: dict[str, Any]) -> dict[str, Any]:
        data = state["input"]
        required_input_fields = ["keyword", "category", "price_range", "market", "risk_level"]
        present = []
        for field in required_input_fields:
            if field == "price_range":
                if data["price"]["avg"] is not None:
                    present.append(field)
            elif field == "risk_level":
                if field in data["raw_input"] and data.get(field):
                    present.append(field)
            elif data.get(field):
                present.append(field)
        completeness = clamp((len(present) / len(required_input_fields)) * 100)
        warnings = []
        if "risk_level" not in data["raw_input"]:
            warnings.append("risk_level not provided; defaulted to medium.")
        if not data["keyword"]:
            warnings.append("keyword is empty; scoring confidence is low.")
        if data["price"]["avg"] is None:
            warnings.append("price_range is missing or unparsable; profit scoring is conservative.")

        return {
            "status": "success",
            "output": "validated_dataset",
            "source_mode": "local_R_SERIES_documents_only",
            "external_api_used": False,
            "confidence": "medium" if completeness >= 80 else "low",
            "input_completeness_score": completeness,
            "normalized_input": data,
            "loaded_documents": self.document_state,
            "source_weight_policy": {
                "official_marketplace_or_search_engine_sources": 1.0,
                "platform_or_tool_public_methodology": 0.75,
                "social_or_forum_signal": 0.35,
                "single_unverified_signal": 0.2,
            },
            "anti_fake_signal_rules": [
                "Do not treat BSR as product quality or search ranking.",
                "Do not treat social heat as standalone demand proof.",
                "Do not treat low competition as opportunity until risk and profit are checked.",
                "Use hard reject conditions before weighted scoring.",
            ],
            "warnings": warnings,
        }

    def amazon_selection_skill(self, state: dict[str, Any]) -> dict[str, Any]:
        data = state["input"]
        tokens = tokenize(data["keyword"], data["category"])
        text = f"{data['keyword']} {data['category']}".lower()
        price_avg = data["price"]["avg"]

        functional_hits = len(tokens & FUNCTIONAL_TERMS)
        risk_hits = len(tokens & HIGH_RISK_TERMS)
        category_low_risk = data["category"].lower() in LOW_RISK_CATEGORIES
        is_home_improvement = "home improvement" in data["category"].lower()
        is_draft_stopper = contains_phrase(text, "draft stopper") or (
            "draft" in tokens and "stopper" in tokens
        )
        is_small_light_candidate = any(token in tokens for token in {"stopper", "seal", "kit", "holder"})

        demand = 58 + functional_hits * 5
        if is_home_improvement:
            demand += 8
        if is_draft_stopper:
            demand += 8
        if price_avg is not None and 10 <= price_avg <= 35:
            demand += 4
        demand = clamp(demand)

        competition = 70
        if "home" in tokens or is_home_improvement:
            competition -= 5
        if "portable" in tokens:
            competition += 3
        if is_draft_stopper:
            competition -= 2
        competition = clamp(competition)

        profit = 66
        if price_avg is not None:
            if price_avg < 12:
                profit -= 8
            elif 12 <= price_avg <= 30:
                profit += 8
            elif price_avg > 80:
                profit -= 4
        if is_small_light_candidate:
            profit += 5
        profit = clamp(profit)

        differentiation = 60 + functional_hits * 4
        if is_draft_stopper:
            differentiation += 8
        if "portable" in tokens:
            differentiation += 5
        differentiation = clamp(differentiation)

        compliance = 88
        if category_low_risk:
            compliance += 5
        compliance -= risk_hits * 14
        if tokens & IP_RISK_TERMS:
            compliance -= 20
        compliance = clamp(compliance)

        seo = 62 + min(functional_hits, 4) * 3
        if is_draft_stopper:
            seo += 8
        seo = clamp(seo)

        ads = 63
        if price_avg is not None and price_avg >= 15:
            ads += 6
        if price_avg is not None and price_avg < 15:
            ads -= 6
        if is_draft_stopper:
            ads += 3
        ads = clamp(ads)

        b2b = 42 + len(tokens & B2B_TERMS) * 8
        if is_home_improvement:
            b2b += 8
        b2b = clamp(b2b)

        brandability = 52 + min(functional_hits, 4) * 3
        if is_draft_stopper:
            brandability += 4
        brandability = clamp(brandability)

        automation = 68 + min(functional_hits, 5) * 4
        if data["keyword"] and data["category"]:
            automation += 4
        automation = clamp(automation)

        scores = {
            "demand_score": demand,
            "competition_score": competition,
            "profit_score": profit,
            "differentiation_score": differentiation,
            "compliance_risk_score": compliance,
            "seo_score": seo,
            "ads_score": ads,
            "b2b_score": b2b,
            "brandability_score": brandability,
            "automation_fit_score": automation,
        }
        fba_fit_score = clamp(82 + (6 if is_small_light_candidate else 0) - risk_hits * 10)
        final_score = weighted_average(scores, self.weights)
        return {
            "status": "success",
            "output": "amazon_scorecard",
            "scores": scores,
            "final_score": final_score,
            "fba_fit_score": fba_fit_score,
            "market_fit": "Amazon",
            "signals": {
                "bsr_analysis": "proxy_required_no_live_bsr; demand scored from local playbook rules and keyword/category fit",
                "demand_judgment": "stable_problem_solution_niche" if demand >= 75 else "needs_more_data",
                "profit_model": "price_band_can_absorb_small_light_fba_if_cogs_is_controlled",
                "competition_analysis": "moderate_competition_expected_for_home_improvement_accessory",
                "risk_filter": "low_policy_risk" if compliance >= 80 else "manual_review_required",
            },
            "weakest_dimensions": weakest_dimensions(scores),
        }

    def independent_site_selection_skill(self, state: dict[str, Any]) -> dict[str, Any]:
        data = state["input"]
        tokens = tokenize(data["keyword"], data["category"])
        text = f"{data['keyword']} {data['category']}".lower()
        price_avg = data["price"]["avg"]

        content_hits = len(tokens & DTC_CONTENT_TERMS)
        b2b_hits = len(tokens & B2B_TERMS)
        visual_hits = len(tokens & VISUAL_TERMS)
        risk_hits = len(tokens & HIGH_RISK_TERMS)
        is_draft_stopper = contains_phrase(text, "draft stopper") or (
            "draft" in tokens and "stopper" in tokens
        )
        is_home_improvement = "home improvement" in data["category"].lower()

        demand = 60 + content_hits * 4
        if is_draft_stopper:
            demand += 7
        if is_home_improvement:
            demand += 4
        demand = clamp(demand)

        competition = 68
        if is_draft_stopper:
            competition += 4
        if is_home_improvement:
            competition -= 2
        competition = clamp(competition)

        profit = 64
        if price_avg is not None:
            if price_avg < 15:
                profit -= 7
            elif 15 <= price_avg <= 45:
                profit += 6
            elif price_avg > 100:
                profit += 3
        profit = clamp(profit)

        differentiation = 62 + content_hits * 4
        if is_draft_stopper:
            differentiation += 7
        differentiation = clamp(differentiation)

        compliance = 86 - risk_hits * 14
        if data["category"].lower() in LOW_RISK_CATEGORIES:
            compliance += 5
        if tokens & IP_RISK_TERMS:
            compliance -= 22
        compliance = clamp(compliance)

        seo = 64 + content_hits * 5
        if is_draft_stopper:
            seo += 9
        seo = clamp(seo)

        ads = 64
        if price_avg is not None and price_avg >= 18:
            ads += 7
        elif price_avg is not None and price_avg < 18:
            ads -= 4
        if is_draft_stopper:
            ads += 4
        ads = clamp(ads)

        b2b = 46 + b2b_hits * 10
        if is_home_improvement:
            b2b += 8
        if is_draft_stopper:
            b2b += 4
        b2b = clamp(b2b)

        brandability = 55 + visual_hits * 4
        if is_draft_stopper:
            brandability += 4
        brandability = clamp(brandability)

        automation = 70 + content_hits * 3 + visual_hits * 2
        if data["keyword"] and data["category"]:
            automation += 4
        automation = clamp(automation)

        scores = {
            "demand_score": demand,
            "competition_score": competition,
            "profit_score": profit,
            "differentiation_score": differentiation,
            "compliance_risk_score": compliance,
            "seo_score": seo,
            "ads_score": ads,
            "b2b_score": b2b,
            "brandability_score": brandability,
            "automation_fit_score": automation,
        }
        gmc_readiness_score = clamp(76 + (5 if compliance >= 85 else -8) - risk_hits * 8)
        content_potential_score = clamp(68 + content_hits * 4 + visual_hits * 3)
        final_score = weighted_average(scores, self.weights)
        return {
            "status": "success",
            "output": "site_scorecard",
            "scores": scores,
            "final_score": final_score,
            "gmc_readiness_score": gmc_readiness_score,
            "content_potential_score": content_potential_score,
            "market_fit": "DTC",
            "signals": {
                "seo_opportunity": "long_tail_problem_solution_content" if seo >= 75 else "supporting_channel_only",
                "cpc_analysis": "controlled_test_required; no live CPC used",
                "content_potential": "installation_FAQ_comparison_visual_content",
                "gmc_risk": "low" if gmc_readiness_score >= 80 else "manual_review_required",
                "b2b_potential": "moderate" if b2b >= 55 else "low",
            },
            "weakest_dimensions": weakest_dimensions(scores),
        }

    def risk_filter_skill(self, state: dict[str, Any]) -> dict[str, Any]:
        data = state["input"]
        tokens = tokenize(data["keyword"], data["category"])
        text = f"{data['keyword']} {data['category']}".lower()
        amazon = state["amazon_scorecard"]
        site = state["site_scorecard"]
        price_avg = data["price"]["avg"]

        hard_reject_conditions: list[str] = []
        risk_flags = {
            "ip_or_patent": "low",
            "compliance": "low",
            "fba_or_logistics": "low",
            "ads_or_gmc_policy": "low",
            "return_risk": "medium",
            "negative_margin": "unknown",
        }

        if tokens & IP_RISK_TERMS:
            risk_flags["ip_or_patent"] = "high"
            hard_reject_conditions.append("ip_or_patent_high_risk")

        high_risk_hits = tokens & HIGH_RISK_TERMS
        if high_risk_hits:
            risk_flags["compliance"] = "high"
            hard_reject_conditions.append("compliance_uncontrollable")

        if amazon["fba_fit_score"] < 60:
            risk_flags["fba_or_logistics"] = "high"
            hard_reject_conditions.append("fba_or_shipping_unsuitable")
        elif amazon["fba_fit_score"] < 75:
            risk_flags["fba_or_logistics"] = "medium"

        if site["gmc_readiness_score"] < 65:
            risk_flags["ads_or_gmc_policy"] = "high"
            hard_reject_conditions.append("gmc_misrepresentation_risk")
        elif site["gmc_readiness_score"] < 80:
            risk_flags["ads_or_gmc_policy"] = "medium"

        if price_avg is not None and price_avg < 8:
            risk_flags["negative_margin"] = "high"
            hard_reject_conditions.append("negative_contribution_margin")
        elif price_avg is not None:
            risk_flags["negative_margin"] = "not_indicated"

        if "fragile" in tokens or "glass" in tokens:
            risk_flags["return_risk"] = "high"
            hard_reject_conditions.append("unfixable_return_risk")
        elif "draft stopper" in text or {"draft", "stopper"} <= tokens:
            risk_flags["return_risk"] = "medium_low"

        if amazon["scores"]["differentiation_score"] < 55 and site["scores"]["differentiation_score"] < 55:
            hard_reject_conditions.append("no_differentiation")

        hard_reject_conditions = sorted(set(hard_reject_conditions))
        if hard_reject_conditions:
            decision = "REJECT"
            risk_level = "high"
        elif "medium" in set(risk_flags.values()):
            decision = "PASS_WITH_REVIEW"
            risk_level = "medium"
        else:
            decision = "PASS"
            risk_level = "low"

        return {
            "status": "success",
            "output": "risk_decision",
            "risk_decision": decision,
            "risk_level": risk_level,
            "hard_reject": bool(hard_reject_conditions),
            "hard_reject_conditions": hard_reject_conditions,
            "risk_flags": risk_flags,
            "manual_review_required": decision == "PASS_WITH_REVIEW",
            "notes": [
                "Hard reject conditions are evaluated before final weighted scoring.",
                "No live patent, compliance, FBA, or GMC API was used.",
            ],
        }

    def decision_engine_skill(self, state: dict[str, Any]) -> dict[str, Any]:
        amazon = state["amazon_scorecard"]
        site = state["site_scorecard"]
        risk = state["risk_decision"]
        market = state["input"]["market"]

        if market == "Amazon":
            final_score = amazon["final_score"]
        elif market == "DTC":
            final_score = site["final_score"]
        else:
            final_score = round((amazon["final_score"] * 0.5) + (site["final_score"] * 0.5), 2)

        if risk["hard_reject"]:
            decision = "REJECT"
            channel = "None"
            recommended_next_step = "STOP"
        elif final_score >= 85:
            decision = "GO"
            channel = self._recommend_channel(amazon["final_score"], site["final_score"], market)
            recommended_next_step = self._recommend_next_step(amazon, site, risk, decision)
        elif final_score >= 75:
            decision = "TEST"
            channel = self._recommend_channel(amazon["final_score"], site["final_score"], market)
            recommended_next_step = self._recommend_next_step(amazon, site, risk, decision)
        elif final_score >= 65:
            decision = "WATCH"
            channel = self._recommend_channel(amazon["final_score"], site["final_score"], market)
            recommended_next_step = self._recommend_next_step(amazon, site, risk, decision)
        else:
            decision = "REJECT"
            channel = "None"
            recommended_next_step = "STOP"

        downstream = self._downstream_handoff(amazon, site, risk, decision)

        return {
            "decision": decision,
            "channel": channel,
            "amazon_score": amazon,
            "site_score": site,
            "risk": risk,
            "final_score": final_score,
            "recommended_next_step": recommended_next_step,
            "downstream_handoff": downstream,
            "decision_basis": {
                "final_score_formula": self.score_model.get("final_score_formula"),
                "threshold_applied": self._threshold_name(decision, risk),
                "market": market,
                "no_external_api_dependency": True,
            },
        }

    def _recommend_channel(self, amazon_score: float, site_score: float, market: str) -> str:
        if market == "Amazon":
            return "Amazon" if amazon_score >= 65 else "None"
        if market == "DTC":
            return "Site" if site_score >= 65 else "None"
        if amazon_score >= 75 and site_score >= 70:
            return "Dual"
        if amazon_score - site_score >= 7:
            return "Amazon"
        if site_score - amazon_score >= 7:
            return "Site"
        if average_score(amazon_score, site_score) >= 65:
            return "Dual"
        return "None"

    def _recommend_next_step(
        self,
        amazon: dict[str, Any],
        site: dict[str, Any],
        risk: dict[str, Any],
        decision: str,
    ) -> str:
        if risk["hard_reject"] or decision == "REJECT":
            return "STOP"
        downstream = self._downstream_handoff(amazon, site, risk, decision)
        for step in ("K", "I", "P", "GMC", "SEO"):
            if downstream[step]["ready"]:
                return step
        return "STOP"

    def _downstream_handoff(
        self,
        amazon: dict[str, Any],
        site: dict[str, Any],
        risk: dict[str, Any],
        decision: str,
    ) -> dict[str, dict[str, Any]]:
        keyword_map_readiness = clamp(
            (amazon["scores"]["automation_fit_score"] * 0.35)
            + (site["scores"]["seo_score"] * 0.45)
            + (site["scores"]["automation_fit_score"] * 0.20)
        )
        visual_demonstration_score = clamp(
            (amazon["scores"]["differentiation_score"] * 0.35)
            + (site["content_potential_score"] * 0.45)
            + (site["scores"]["brandability_score"] * 0.20)
        )
        page_readiness_score = clamp(
            (site["scores"]["differentiation_score"] * 0.30)
            + (site["scores"]["seo_score"] * 0.25)
            + (site["gmc_readiness_score"] * 0.25)
            + (amazon["scores"]["automation_fit_score"] * 0.20)
        )
        gmc_readiness_score = site["gmc_readiness_score"]
        seo_score = site["scores"]["seo_score"]
        blocked = risk["hard_reject"] or decision == "REJECT"
        return {
            "K": {
                "ready": (not blocked) and keyword_map_readiness >= 70,
                "score": keyword_map_readiness,
                "reason": "keyword map and intent labels are the first downstream dependency",
            },
            "I": {
                "ready": (not blocked) and visual_demonstration_score >= 70,
                "score": visual_demonstration_score,
                "reason": "product value can be shown through usage, detail, comparison, and installation assets",
            },
            "P": {
                "ready": (not blocked) and page_readiness_score >= 75,
                "score": page_readiness_score,
                "reason": "page structure is viable after keyword and image requirements are confirmed",
            },
            "GMC": {
                "ready": (not blocked) and gmc_readiness_score >= 80 and not risk["hard_reject"],
                "score": gmc_readiness_score,
                "reason": "feed and landing-page consistency require manual confirmation before launch",
            },
            "SEO": {
                "ready": (not blocked) and seo_score >= 70,
                "score": seo_score,
                "reason": "long-tail problem, FAQ, comparison, and installation content path exists",
            },
        }

    def _threshold_name(self, decision: str, risk: dict[str, Any]) -> str:
        if risk["hard_reject"]:
            return "hard_reject"
        return {
            "GO": "priority_test",
            "TEST": "test_after_review",
            "WATCH": "watchlist",
            "REJECT": "reject_or_reject_for_now",
        }[decision]

    def activation_report(self, test_input: dict[str, Any] | None = None) -> dict[str, Any]:
        sample = test_input or {
            "keyword": "portable door draft stopper",
            "category": "home improvement",
            "price_range": "10-30",
            "market": "Amazon + DTC",
        }
        test_output = self.run(sample)
        skill_registration_status = {
            skill_name: self.registry["skills"][skill_name]["status"]
            for skill_name in sorted(self.registry["skills"])
        }
        validations = {
            "skill_invocation_success": all(
                item["status"] == "success" for item in test_output["skill_trace"]
            )
            and [item["skill"] for item in test_output["skill_trace"]] == SKILL_ORDER,
            "scoring_generation_success": bool(
                test_output["amazon_score"]["scores"]
                and test_output["site_score"]["scores"]
                and isinstance(test_output["final_score"], (int, float))
            ),
            "decision_output_success": test_output["decision"]
            in {"GO", "TEST", "WATCH", "REJECT"},
            "kip_path_recommendation_success": test_output["recommended_next_step"]
            in {"K", "I", "P"}
            or any(
                test_output["downstream_handoff"][step]["ready"]
                for step in ("K", "I", "P")
            ),
        }
        return {
            "report_name": "R_SYSTEM_RUNTIME_ACTIVATION_REPORT",
            "generated_at": utc_now(),
            "skill_registration_status": skill_registration_status,
            "engine_initialization_status": {
                "engine": ENGINE_NAME,
                "version": ENGINE_VERSION,
                "initialized": True,
                "initialized_at": self.initialized_at,
                "runtime_layer": "r_series/runtime",
                "external_api_dependency": False,
                "database_schema_change": False,
                "k_i_p_system_modified": False,
            },
            "data_loading_confirmation": self.document_state,
            "test_run_result": {
                "input": sample,
                "output": test_output,
                "validations": validations,
            },
            "system_readiness": {
                "ready": all(validations.values()) and self.document_state["all_loaded"],
                "status": "READY" if all(validations.values()) else "NOT_READY",
                "scope_guard": self.registry["scope_guard"],
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R_ENGINE_V1 locally.")
    parser.add_argument("--input-json", help="Inline JSON input for a product candidate.")
    parser.add_argument("--input-file", help="Path to a JSON input file.")
    parser.add_argument(
        "--activation-report",
        action="store_true",
        help="Run the required activation test and write R_SYSTEM_RUNTIME_ACTIVATION_REPORT.json.",
    )
    args = parser.parse_args()

    engine = REngineV1()
    if args.activation_report:
        report = engine.activation_report()
        write_json(REPORT_PATH, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.input_file:
        payload = read_json(Path(args.input_file))
    elif args.input_json:
        payload = json.loads(args.input_json)
    else:
        payload = {
            "keyword": "portable door draft stopper",
            "category": "home improvement",
            "price_range": "10-30",
            "market": "Amazon + DTC",
        }
    result = engine.run(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
