"""DeepSeek first-pass screening skill for rule-passed R-W products."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
DEEPSEEK_PASS_SCORE = 70
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


@dataclass(frozen=True)
class DeepSeekTitleTranslation:
    title_zh: str | None
    source: str
    error: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "title_zh": self.title_zh,
            "source": self.source,
            "error": self.error,
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

    def translate_title(self, title: str) -> DeepSeekTitleTranslation:
        cleaned = " ".join(str(title or "").split())
        if not cleaned:
            return DeepSeekTitleTranslation(
                title_zh=None,
                source="empty_title",
                error="empty_title",
            )
        api_key = self.current_api_key()
        if not api_key:
            return DeepSeekTitleTranslation(
                title_zh=None,
                source="deepseek_key_missing",
                error="deepseek_api_key_missing",
            )
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        timeout = _float_env("RW_DEEPSEEK_TRANSLATION_TIMEOUT_SECONDS", 8.0)
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是电商产品标题翻译器。只输出简体中文产品名，"
                        "不要解释，不要加引号，不要输出品牌判断。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"翻译这个 Amazon 产品标题：{cleaned}",
                },
            ],
        }
        request = Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed DeepSeek URL.
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return DeepSeekTitleTranslation(
                title_zh=None,
                source="deepseek_api_error",
                error=str(exc)[:240],
            )
        translated = _extract_translation_text(data)
        if not translated:
            return DeepSeekTitleTranslation(
                title_zh=None,
                source="deepseek_empty_response",
                error="deepseek_empty_response",
            )
        return DeepSeekTitleTranslation(
            title_zh=translated,
            source="deepseek_realtime_title_translation",
        )

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


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _extract_translation_text(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, str):
        return None
    translated = " ".join(content.replace("\n", " ").split()).strip(" '\"“”")
    if not translated:
        return None
    return translated[:160]


def _clamp_int(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _score_demand_quality(product: NormalizedProduct) -> int:
    score = 35
    monthly_sales = _int_feature(product, "monthly_sales")
    if product.bsr <= 5_000:
        score += 28
    elif product.bsr <= 20_000:
        score += 18
    elif product.bsr <= 50_000:
        score += 8
    if monthly_sales >= 1_000:
        score += 16
    elif monthly_sales >= 300:
        score += 10
    elif monthly_sales >= 50:
        score += 5
    if 20 <= product.reviews <= 300:
        score += 8
    elif product.reviews == 0:
        score -= 10
    if product.price_trend in {"stable", "slightly_up", "up"}:
        score += 8
    if product.rating and product.rating >= 4.0:
        score += 5
    return _clamp_int(score)


def _score_competition_attackability(product: NormalizedProduct) -> int:
    score = 60
    if product.seller_count > 10:
        score -= 20
    elif product.seller_count >= 6:
        score -= 8
    elif 2 <= product.seller_count <= 5:
        score += 14
    elif product.seller_count <= 1:
        score -= 22
    if product.reviews > 500:
        score -= 30
    elif product.reviews > 300:
        score -= 22
    elif product.reviews > 150:
        score -= 10
    elif product.reviews < 20:
        score -= 6
    if product.brand_share > 0.40:
        score -= 20
    elif product.brand_share and product.brand_share < 0.25:
        score += 8
    return _clamp_int(score)


def _score_margin(est_net_margin: float | None) -> int:
    if est_net_margin is None:
        return 45
    if est_net_margin >= 0.30:
        return 95
    if est_net_margin >= 0.25:
        return 85
    if est_net_margin >= 0.15:
        return 65
    return 25


def _verdict_for_score(score: int) -> str:
    if score >= 82:
        return "keep"
    if score >= DEEPSEEK_PASS_SCORE:
        return "hold"
    return "cut"


def _channel_for_product(product: NormalizedProduct) -> str:
    if product.category.lower() in {"home & kitchen", "patio, lawn & garden"}:
        return "both"
    return "amazon"


def _top_reason(product: NormalizedProduct, score: int) -> str:
    monthly_sales = _int_feature(product, "monthly_sales")
    margin_label = (
        "成本缺失按保守分处理"
        if product.est_net_margin is None
        else f"预估净利率 {round(product.est_net_margin * 100, 1)}%"
    )
    if score >= 82:
        return (
            f"通过：BSR {product.bsr}、月销量 {monthly_sales}、卖家 {product.seller_count}、"
            f"评论 {product.reviews}，需求和竞争同时达标，{margin_label}。"
        )
    if score >= DEEPSEEK_PASS_SCORE:
        return (
            f"暂通过：BSR {product.bsr}、月销量 {monthly_sales}、卖家 {product.seller_count}、"
            f"评论 {product.reviews}，满足最低初筛线，但仍需人工复核，{margin_label}。"
        )
    return (
        f"剔除：BSR {product.bsr}、月销量 {monthly_sales}、卖家 {product.seller_count}、"
        f"评论 {product.reviews} 的组合不适合中小卖家首轮切入，{margin_label}。"
    )


def _int_feature(product: NormalizedProduct, key: str) -> int:
    value = product.features.get(key)
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
