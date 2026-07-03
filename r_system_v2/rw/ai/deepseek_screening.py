"""DeepSeek first-pass screening skill for rule-passed R-W products."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.rw.core.models import DeepSeekScreening, NormalizedProduct


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_PATH = REPO_ROOT / "r_system_v2" / "docs" / "SKILL.md"
REQUIRED_R_SERIES_DOCS = (
    REPO_ROOT / "r_system_v2" / "docs" / "README.md",
    REPO_ROOT / "r_system_v2" / "docs" / "ARCHITECTURE.md",
    REPO_ROOT / "r_system_v2" / "docs" / "SKILL.md",
    REPO_ROOT / "r_system_v2" / "docs" / "shared.md",
    REPO_ROOT / "r_system_v2" / "docs" / "amazon.md",
    REPO_ROOT / "r_system_v2" / "docs" / "dtc.md",
    REPO_ROOT / "r_system_v2" / "docs" / "dtc_data.md",
)
DEEPSEEK_PASS_SCORE = 60
ALLOWED_VERDICTS = {"keep", "cut", "hold"}
ALLOWED_CHANNELS = {"amazon", "dtc_ad", "dtc_seo", "both"}
STRICT_SCHEMA_KEYS = {
    "score",
    "verdict",
    "competition_attackability",
    "demand_quality",
    "top_reason",
    "channel_guess",
}


class DeepSeekSkillLoadError(RuntimeError):
    """Raised when the product-selection skill cannot be verified."""


class DeepSeekSchemaError(RuntimeError):
    """Raised when the first-pass output violates the strict JSON schema."""


@dataclass(frozen=True)
class DeepSeekSkillStatus:
    skill_path: str
    loaded: bool
    quant_filter_enabled: bool
    rule_based_scoring_active: bool
    output_schema_strict_json: bool
    required_schema_keys: list[str]
    required_docs_present: bool
    required_docs: list[str]

    @property
    def ready(self) -> bool:
        return all(
            [
                self.loaded,
                self.quant_filter_enabled,
                self.rule_based_scoring_active,
                self.output_schema_strict_json,
                self.required_docs_present,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_path": self.skill_path,
            "loaded": self.loaded,
            "quant_filter_enabled": self.quant_filter_enabled,
            "rule_based_scoring_active": self.rule_based_scoring_active,
            "output_schema_strict_json": self.output_schema_strict_json,
            "required_schema_keys": self.required_schema_keys,
            "required_docs_present": self.required_docs_present,
            "required_docs": self.required_docs,
            "ready": self.ready,
        }


@dataclass(frozen=True)
class DeepSeekBatchResult:
    pass_products: list[dict[str, Any]]
    fail_products: list[dict[str, Any]]
    report_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass_products": self.pass_products,
            "fail_products": self.fail_products,
            "report_summary": self.report_summary,
        }


class DeepSeekScreeningSkill:
    """Rule-based batch processor for the documented DeepSeek AI-1 contract."""

    def __init__(
        self,
        skill_path: Path = SKILL_PATH,
        *,
        org_id: str | None = None,
        secret_manager: SecretManager | None = None,
    ) -> None:
        self.skill_path = skill_path
        self.org_id = org_id
        self.secret_manager = secret_manager or SecretManager()
        self._api_key = ""
        self.reload_secret()
        self.status = self._load_status()
        if not self.status.ready:
            raise DeepSeekSkillLoadError("deepseek_skill_contract_incomplete")

    def reload_secret(self) -> str:
        if not self.org_id:
            self._api_key = ""
            return self._api_key
        try:
            self._api_key = self.secret_manager.get_key("deepseek", self.org_id)
        except SecretManagerError:
            self._api_key = ""
        return self._api_key

    def current_api_key(self) -> str:
        return self.reload_secret()

    def api_key_configured(self) -> bool:
        return bool(self.current_api_key())

    def evaluate(self, product: NormalizedProduct) -> DeepSeekScreening:
        demand_quality = _score_demand_quality(product)
        competition_attackability = _score_competition_attackability(product)
        margin_score = _score_margin(product.est_net_margin)
        score = _clamp_int(
            0.40 * demand_quality
            + 0.40 * competition_attackability
            + 0.20 * margin_score
        )
        verdict = _verdict_for_score(score)
        channel_guess = _channel_for_product(product)
        payload = {
            "score": score,
            "verdict": verdict,
            "competition_attackability": competition_attackability,
            "demand_quality": demand_quality,
            "top_reason": _top_reason(product, score),
            "channel_guess": channel_guess,
        }
        strict_json = self._strict_json(payload)
        return DeepSeekScreening(
            asin=product.asin,
            score=score,
            verdict=verdict,
            competition_attackability=competition_attackability,
            demand_quality=demand_quality,
            top_reason=strict_json["top_reason"],
            channel_guess=channel_guess,
            strict_json=strict_json,
            skill_loaded=self.status.loaded,
            quant_filter_enabled=self.status.quant_filter_enabled,
            rule_based_scoring_active=self.status.rule_based_scoring_active,
            output_schema_strict_json=self.status.output_schema_strict_json,
        )

    def evaluate_batch(self, products: list[NormalizedProduct]) -> DeepSeekBatchResult:
        screenings = [self.evaluate(product) for product in products]
        pass_products = [
            {
                "asin": result.asin,
                "score": result.score,
                "verdict": result.verdict,
                "channel_guess": result.channel_guess,
            }
            for result in screenings
            if result.passed
        ]
        fail_products = [
            {
                "asin": result.asin,
                "score": result.score,
                "verdict": result.verdict,
                "channel_guess": result.channel_guess,
            }
            for result in screenings
            if not result.passed
        ]
        return DeepSeekBatchResult(
            pass_products=pass_products,
            fail_products=fail_products,
            report_summary={
                "mode": "batch_processor_only",
                "scheduling_authority": False,
                "total_processed": len(screenings),
                "pass_count": len(pass_products),
                "fail_count": len(fail_products),
                "strict_json_enforced": self.status.output_schema_strict_json,
            },
        )

    def _load_status(self) -> DeepSeekSkillStatus:
        if not self.skill_path.exists():
            return DeepSeekSkillStatus(
                skill_path=str(self.skill_path),
                loaded=False,
                quant_filter_enabled=False,
                rule_based_scoring_active=False,
                output_schema_strict_json=False,
                required_schema_keys=sorted(STRICT_SCHEMA_KEYS),
                required_docs_present=False,
                required_docs=[str(path) for path in REQUIRED_R_SERIES_DOCS],
            )

        text = self.skill_path.read_text(encoding="utf-8")
        required_docs_present = all(path.exists() for path in REQUIRED_R_SERIES_DOCS)
        quant_filter_enabled = "DeepSeek" in text and "量化过滤器" in text
        rule_based_scoring_active = "只吃**结构化 Keepa 字段**" in text or "只吃结构化 Keepa 字段" in text
        output_schema_strict_json = all(key in text for key in STRICT_SCHEMA_KEYS) and "输出:" in text
        return DeepSeekSkillStatus(
            skill_path=str(self.skill_path),
            loaded=True,
            quant_filter_enabled=quant_filter_enabled,
            rule_based_scoring_active=rule_based_scoring_active,
            output_schema_strict_json=output_schema_strict_json,
            required_schema_keys=sorted(STRICT_SCHEMA_KEYS),
            required_docs_present=required_docs_present,
            required_docs=[str(path) for path in REQUIRED_R_SERIES_DOCS],
        )

    def _strict_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != STRICT_SCHEMA_KEYS:
            raise DeepSeekSchemaError("deepseek_schema_keys_mismatch")
        if not isinstance(payload["score"], int) or not 0 <= payload["score"] <= 100:
            raise DeepSeekSchemaError("deepseek_score_out_of_range")
        if payload["verdict"] not in ALLOWED_VERDICTS:
            raise DeepSeekSchemaError("deepseek_verdict_invalid")
        if payload["channel_guess"] not in ALLOWED_CHANNELS:
            raise DeepSeekSchemaError("deepseek_channel_invalid")
        for key in ("competition_attackability", "demand_quality"):
            if not isinstance(payload[key], int) or not 0 <= payload[key] <= 100:
                raise DeepSeekSchemaError(f"deepseek_{key}_out_of_range")
        if not isinstance(payload["top_reason"], str) or not payload["top_reason"].strip():
            raise DeepSeekSchemaError("deepseek_top_reason_invalid")

        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        decoded = json.loads(encoded)
        if decoded != payload:
            raise DeepSeekSchemaError("deepseek_json_roundtrip_failed")
        return decoded


def _clamp_int(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _score_demand_quality(product: NormalizedProduct) -> int:
    score = 45
    if product.bsr <= 10_000:
        score += 30
    elif product.bsr <= 50_000:
        score += 18
    if product.reviews >= 50:
        score += 8
    if product.price_trend in {"stable", "slightly_up", "up"}:
        score += 12
    if product.rating and product.rating >= 4.0:
        score += 5
    return _clamp_int(score)


def _score_competition_attackability(product: NormalizedProduct) -> int:
    score = 80
    if product.seller_count > 10:
        score -= 15
    elif product.seller_count < 3:
        score -= 10
    if product.reviews > 500:
        score -= 25
    elif product.reviews > 300:
        score -= 12
    if product.brand_share > 0.40:
        score -= 18
    elif product.brand_share < 0.30:
        score += 6
    return _clamp_int(score)


def _score_margin(est_net_margin: float | None) -> int:
    if est_net_margin is None:
        return 60
    if est_net_margin >= 0.30:
        return 95
    if est_net_margin >= 0.25:
        return 85
    if est_net_margin >= 0.15:
        return 65
    return 25


def _verdict_for_score(score: int) -> str:
    if score >= 75:
        return "keep"
    if score >= DEEPSEEK_PASS_SCORE:
        return "hold"
    return "cut"


def _channel_for_product(product: NormalizedProduct) -> str:
    if product.category.lower() in {"home & kitchen", "patio, lawn & garden"}:
        return "both"
    return "amazon"


def _top_reason(product: NormalizedProduct, score: int) -> str:
    if score >= 75:
        return "stable demand and attackable competition after hard-rule pass"
    if score >= DEEPSEEK_PASS_SCORE:
        return "rule-passed candidate needs downstream validation"
    return f"weak first-pass score for {product.asin}"
