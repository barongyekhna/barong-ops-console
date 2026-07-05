"""DeepSeek first-pass screening skill for rule-passed R-W products."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.rw.ai.model_config import rw_deepseek_model
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
        model = rw_deepseek_model()
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
        edible_reason = _edible_reject_reason(product)
        if edible_reason:
            payload = {
                "score": 0,
                "verdict": "cut",
                "competition_attackability": 0,
                "demand_quality": 0,
                "top_reason": edible_reason,
                "channel_guess": "amazon",
            }
            strict_json = self._strict_json(payload)
            return DeepSeekScreening(
                asin=product.asin,
                score=0,
                verdict="cut",
                competition_attackability=0,
                demand_quality=0,
                top_reason=strict_json["top_reason"],
                channel_guess="amazon",
                strict_json=strict_json,
                skill_loaded=self.status.loaded,
                quant_filter_enabled=self.status.quant_filter_enabled,
                rule_based_scoring_active=self.status.rule_based_scoring_active,
                output_schema_strict_json=self.status.output_schema_strict_json,
            )
        pest_control_reason = _pest_control_reject_reason(product)
        if pest_control_reason:
            payload = {
                "score": 0,
                "verdict": "cut",
                "competition_attackability": 0,
                "demand_quality": 0,
                "top_reason": pest_control_reason,
                "channel_guess": "amazon",
            }
            strict_json = self._strict_json(payload)
            return DeepSeekScreening(
                asin=product.asin,
                score=0,
                verdict="cut",
                competition_attackability=0,
                demand_quality=0,
                top_reason=strict_json["top_reason"],
                channel_guess="amazon",
                strict_json=strict_json,
                skill_loaded=self.status.loaded,
                quant_filter_enabled=self.status.quant_filter_enabled,
                rule_based_scoring_active=self.status.rule_based_scoring_active,
                output_schema_strict_json=self.status.output_schema_strict_json,
            )
        restricted_form_reason = _restricted_form_reject_reason(product)
        if restricted_form_reason:
            payload = {
                "score": 0,
                "verdict": "cut",
                "competition_attackability": 0,
                "demand_quality": 0,
                "top_reason": restricted_form_reason,
                "channel_guess": "amazon",
            }
            strict_json = self._strict_json(payload)
            return DeepSeekScreening(
                asin=product.asin,
                score=0,
                verdict="cut",
                competition_attackability=0,
                demand_quality=0,
                top_reason=strict_json["top_reason"],
                channel_guess="amazon",
                strict_json=strict_json,
                skill_loaded=self.status.loaded,
                quant_filter_enabled=self.status.quant_filter_enabled,
                rule_based_scoring_active=self.status.rule_based_scoring_active,
                output_schema_strict_json=self.status.output_schema_strict_json,
            )
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


def _edible_reject_reason(product: NormalizedProduct) -> str | None:
    haystack = _product_text(product)
    if not haystack:
        return None
    category_text = _product_category_text(product)
    non_edible_context = _contains_any(haystack, _NON_EDIBLE_ACCESSORY_TERMS)
    if _contains_any(category_text, _EDIBLE_CATEGORY_TERMS) and not non_edible_context:
        return "剔除：DeepSeek 判断该产品属于食品、饮品、保健品、药品或宠物可食用品，不进入 R-A。"
    if _contains_any(haystack, _EDIBLE_STRONG_PHRASES) and not non_edible_context:
        return "剔除：DeepSeek 命中食品/保健品/药品/宠物食品关键词，不进入 R-A。"
    if _contains_any(haystack, _EDIBLE_GENERAL_TERMS) and not non_edible_context:
        return "剔除：DeepSeek 判断该产品有可食用属性，不进入 R-A。"
    return None


def _pest_control_reject_reason(product: NormalizedProduct) -> str | None:
    haystack = _product_text(product)
    if not haystack:
        return None
    has_strong_pest_phrase = _contains_any(haystack, _PEST_CONTROL_STRONG_PHRASES)
    if _contains_any(haystack, _NON_INSECT_REPELLENT_TERMS) and not has_strong_pest_phrase:
        return None
    if _contains_any(haystack, _PEST_CONTROL_CATEGORY_TERMS):
        return "剔除：DeepSeek 判断该产品属于杀虫、灭虫、驱虫或虫害控制类产品，不进入 R-A。"
    if has_strong_pest_phrase:
        return "剔除：DeepSeek 命中杀虫剂、灭蚊灯、捕虫器、驱虫喷雾或虫害控制关键词，不进入 R-A。"
    if _contains_pest_general_term(haystack) and _contains_any(
        haystack,
        _PEST_CONTROL_ACTION_TERMS,
    ):
        return "剔除：DeepSeek 判断该产品与杀虫灭虫用途直接相关，不进入 R-A。"
    return None


def _restricted_form_reject_reason(product: NormalizedProduct) -> str | None:
    haystack = _product_text(product)
    if not haystack:
        return None
    if _contains_any(haystack, _SPRAY_CONTAINER_OR_TOOL_TERMS):
        return None
    if _contains_any(haystack, _LIQUID_CONTAINER_OR_TOOL_TERMS):
        return None
    if _contains_any(haystack, _POWDER_FALSE_POSITIVE_TERMS):
        return None
    if _contains_any(haystack, _LIQUID_STRONG_PHRASES):
        return "剔除：DeepSeek 判断该产品本体含液体，不进入 R-A。"
    if _contains_any(haystack, _POWDER_STRONG_PHRASES):
        return "剔除：DeepSeek 判断该产品本体为粉末，不进入 R-A。"
    if _contains_any(haystack, _SPRAY_STRONG_PHRASES):
        return "剔除：DeepSeek 判断该产品本体为喷雾类内容物，不进入 R-A。"
    return None


def deepseek_reject_code(top_reason: str | None) -> str:
    reason = str(top_reason or "").lower()
    if any(term in reason for term in ("杀虫", "灭虫", "驱虫", "灭蚊", "捕虫", "虫害")):
        return "deepseek_pest_control_product"
    if any(term in reason for term in ("液体", "粉末", "喷雾")):
        return "deepseek_liquid_powder_spray_product"
    return "deepseek_edible_product"


def _product_text(product: NormalizedProduct) -> str:
    values: list[str] = [
        product.title,
        product.brand,
        product.category,
        product.source_query,
        " ".join(product.category_path),
    ]
    for key in (
        "amazon_category_path",
        "subcategory_name",
        "parent_category_name",
        "bestseller_parent_category",
    ):
        value = product.features.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value if isinstance(item, str))
    return " ".join(values).lower()


def _product_category_text(product: NormalizedProduct) -> str:
    values: list[str] = [
        product.category,
        product.source_query,
        " ".join(product.category_path),
    ]
    for key in (
        "amazon_category_path",
        "subcategory_name",
        "parent_category_name",
        "bestseller_parent_category",
    ):
        value = product.features.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value if isinstance(item, str))
    return " ".join(values).lower()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _contains_pest_general_term(text: str) -> bool:
    for term in _PEST_CONTROL_GENERAL_TERMS:
        if term.isascii() and term.replace(" ", "").isalpha() and len(term) <= 5:
            if re.search(rf"\b{re.escape(term)}\b", text):
                return True
            continue
        if term in text:
            return True
    return False


_EDIBLE_CATEGORY_TERMS = (
    "grocery",
    "gourmet food",
    "pantry",
    "beverage",
    "coffee",
    "tea",
    "snack",
    "candy",
    "chocolate",
    "pet food",
    "dog food",
    "cat food",
    "vitamins",
    "dietary supplement",
    "sports nutrition",
    "nutrition",
    "营养与保健",
    "运动营养",
    "维生素与膳食补充剂",
    "饮品",
    "保健",
    "药品",
)
_EDIBLE_STRONG_PHRASES = (
    "dog food",
    "cat food",
    "pet food",
    "dog treat",
    "cat treat",
    "pet treat",
    "puppy treat",
    "kitten treat",
    "dietary supplement",
    "vitamin",
    "multivitamin",
    "probiotic",
    "collagen",
    "protein powder",
    "protein bar",
    "omega-3",
    "omega 3",
    "fish oil",
    "medicine",
    "medication",
    "drug",
    "supplement capsule",
    "medicine capsule",
    "vitamin tablet",
    "supplement tablet",
    "gummy vitamins",
    "herbal supplement",
    "baby food",
    "infant formula",
    "coffee beans",
    "coffee bean",
    "ground coffee",
    "instant coffee",
    "coffee pods",
    "coffee pod",
    "k-cup",
    "k cup",
    "tea bags",
    "tea bag",
    "loose leaf tea",
    "herbal tea",
    "milk tea",
    "energy drink",
    "soft drink",
    "drink powder",
    "beverage powder",
    "食品",
    "零食",
    "饮料",
    "保健品",
    "补充剂",
    "维生素",
    "药",
    "宠物粮",
    "狗粮",
    "猫粮",
    "宠物零食",
)
_EDIBLE_GENERAL_TERMS = (
    "snack",
    "candy",
    "cookie",
    "cracker",
    "chocolate",
    "drink mix",
    "juice",
    "soda",
    "sauce",
    "seasoning",
    "spice",
    "honey",
    "syrup",
    "cereal",
    "noodle",
    "pasta",
    "rice",
    "soup",
    "broth",
    "meal",
    "edible",
    "food",
    "treats",
)
_NON_EDIBLE_ACCESSORY_TERMS = (
    "food storage",
    "food container",
    "food processor",
    "food saver",
    "food sealer",
    "food bag",
    "food jar",
    "food bowl",
    "food mat",
    "treat pouch",
    "treat bag",
    "cookie cutter",
    "coffee maker",
    "tea kettle",
    "spice rack",
    "honey dipper",
    "blender",
    "hand blender",
    "immersion blender",
    "milk frother",
    "frother",
    "whisk",
    "emulsifier",
    "mixer",
    "stand mixer",
    "hand mixer",
    "kitchen appliance",
    "small appliance",
    "food blender",
    "smoothie blender",
    "soup maker",
    "food service equipment",
    "commercial kitchen equipment",
    "restaurant equipment",
    "bakery equipment",
    "cafe equipment",
    "coffee shop",
    "bakery organization",
    "label maker",
    "label machine",
    "label printer",
    "labeler",
    "thermal labeler",
    "thermal printer",
    "portable thermal printer",
    "barcode printer",
    "shipping label",
    "label tape",
    "label roll",
    "labels",
    "sticker label",
    "price tag",
    "meal prep container",
    "打奶器",
    "奶泡器",
    "搅拌机",
    "手持搅拌机",
    "料理机",
    "打蛋器",
    "乳化器",
    "厨房电器",
    "食品服务设备",
    "餐饮设备",
    "标签机",
    "标签打印机",
    "热敏打印机",
    "便携打印机",
    "条码打印机",
    "标签纸",
    "标签带",
    "食品容器",
    "食品收纳",
)
_PEST_CONTROL_CATEGORY_TERMS = (
    "insect control",
    "mosquito control",
    "bug control",
    "虫害控制",
    "杀虫",
    "灭虫",
    "灭蚊",
    "驱虫",
)
_PEST_CONTROL_STRONG_PHRASES = (
    "insecticide",
    "pesticide",
    "bug killer",
    "insect killer",
    "mosquito killer",
    "mosquito zapper",
    "bug zapper",
    "fly zapper",
    "electric fly swatter",
    "fly trap",
    "fly repellent",
    "mosquito trap",
    "bug trap",
    "insect trap",
    "ant bait",
    "roach bait",
    "roach killer",
    "cockroach killer",
    "termite killer",
    "wasp killer",
    "hornet killer",
    "bed bug killer",
    "flea killer",
    "tick killer",
    "mite killer",
    "gnat trap",
    "fruit fly trap",
    "insect repellent",
    "bug repellent",
    "mosquito repellent",
    "repellent spray",
    "杀虫剂",
    "杀虫喷雾",
    "灭虫",
    "灭蚊灯",
    "灭蚊器",
    "捕蚊",
    "捕虫",
    "捕蝇",
    "粘虫",
    "粘蝇",
    "驱虫剂",
    "驱蚊",
    "蚊香",
    "蟑螂药",
    "蚂蚁药",
    "白蚁",
    "跳蚤",
    "蜱虫",
    "臭虫",
)
_NON_INSECT_REPELLENT_TERMS = (
    "deer",
    "rabbit",
    "bunny",
    "elk",
    "moose",
    "squirrel",
    "bird",
    "snake",
    "mole",
    "gopher",
    "raccoon",
    "cat repellent",
    "dog repellent",
    "鹿",
    "兔",
    "鸟",
    "蛇",
)
_PEST_CONTROL_GENERAL_TERMS = (
    "mosquito",
    "insect",
    "bug",
    "fly",
    "ant",
    "roach",
    "cockroach",
    "termite",
    "wasp",
    "hornet",
    "gnat",
    "flea",
    "tick",
    "mite",
    "bed bug",
    "蚊",
    "虫",
    "苍蝇",
    "蚂蚁",
    "蟑螂",
    "白蚁",
)
_PEST_CONTROL_ACTION_TERMS = (
    "killer",
    "zapper",
    "trap",
    "bait",
    "repellent",
    "control",
    "spray",
    "poison",
    "杀",
    "灭",
    "驱",
    "捕",
    "粘",
    "诱饵",
)
_LIQUID_STRONG_PHRASES = (
    "liquid",
    "liquid cleaner",
    "liquid soap",
    "liquid detergent",
    "liquid fertilizer",
    "liquid plant food",
    "liquid solution",
    "liquid refill",
    "liquid drops",
    "cleaning solution",
    "soap refill",
    "detergent refill",
    "essential oil",
    "fragrance oil",
    "液体",
    "清洁液",
    "补充液",
    "精油",
)
_POWDER_STRONG_PHRASES = (
    "powder",
    "powdered",
    "cleaning powder",
    "detergent powder",
    "soap powder",
    "deodorizing powder",
    "powder refill",
    "粉末",
    "粉剂",
    "清洁粉",
    "补充粉",
)
_SPRAY_STRONG_PHRASES = (
    "aerosol",
    "spray refill",
    "cleaning spray",
    "room spray",
    "fabric spray",
    "fragrance spray",
    "deodorizing spray",
    "spray cleaner",
    "喷雾",
    "喷剂",
    "喷雾剂",
)
_SPRAY_CONTAINER_OR_TOOL_TERMS = (
    "spray bottle",
    "spray bottles",
    "empty spray bottle",
    "refillable spray bottle",
    "sprayer bottle",
    "mist bottle",
    "misting bottle",
    "trigger sprayer",
    "spray nozzle",
    "sprayer nozzle",
    "spray head",
    "spray gun",
    "paint sprayer",
    "garden sprayer",
    "pump sprayer",
    "spray can holder",
    "spray bottle holder",
    "喷壶",
    "空喷瓶",
    "喷瓶",
    "喷头",
    "喷枪",
    "喷雾瓶",
)
_LIQUID_CONTAINER_OR_TOOL_TERMS = (
    "liquid measuring cup",
    "liquid measuring cups",
    "liquid dispenser",
    "liquid soap dispenser",
    "liquid pump",
    "liquid transfer pump",
    "liquid level sensor",
    "liquid storage tank",
    "liquid container",
    "liquid containers",
    "liquid bottle",
    "liquid bottles",
    "液体容器",
    "液体分配器",
    "皂液器",
)
_POWDER_FALSE_POSITIVE_TERMS = (
    "powder coated",
    "powder-coated",
    "powder coating",
    "powder room",
    "powder puff",
    "powder brush",
    "powder measure",
    "powder funnel",
    "powder dispenser",
    "powder shaker",
    "powder container",
    "powder containers",
    "powder scoop",
    "粉末容器",
    "粉末漏斗",
)


def _score_demand_quality(product: NormalizedProduct) -> int:
    score = 35
    monthly_sales = _monthly_sales_for_scoring(product)
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
    return "hold"


def _channel_for_product(product: NormalizedProduct) -> str:
    if product.category.lower() in {"home & kitchen", "patio, lawn & garden"}:
        return "both"
    return "amazon"


def _top_reason(product: NormalizedProduct, score: int) -> str:
    monthly_sales_label = _monthly_sales_label(product)
    margin_label = (
        "成本缺失按保守分处理"
        if product.est_net_margin is None
        else f"预估净利率 {round(product.est_net_margin * 100, 1)}%"
    )
    if score >= 82:
        return (
            f"通过：BSR {product.bsr}、月销量 {monthly_sales_label}、卖家 {product.seller_count}、"
            f"评论 {product.reviews}，需求和竞争同时达标，{margin_label}。"
        )
    if score >= DEEPSEEK_PASS_SCORE:
        return (
            f"暂通过：BSR {product.bsr}、月销量 {monthly_sales_label}、卖家 {product.seller_count}、"
            f"评论 {product.reviews}，满足最低初筛线，但仍需人工复核，{margin_label}。"
        )
    return (
        f"低分待复核：BSR {product.bsr}、月销量 {monthly_sales_label}、卖家 {product.seller_count}、"
        f"评论 {product.reviews} 的组合存在中小卖家切入风险，{margin_label}。"
    )


def _monthly_sales_label(product: NormalizedProduct) -> str:
    value = product.features.get("monthly_sales")
    parsed_value = _positive_int(value)
    if parsed_value is not None:
        return str(parsed_value)
    estimate = _positive_int(product.features.get("monthly_sales_estimate"))
    minimum = _positive_int(product.features.get("monthly_sales_estimate_min"))
    maximum = _positive_int(product.features.get("monthly_sales_estimate_max"))
    confidence = str(product.features.get("monthly_sales_confidence") or "").strip()
    confidence_label = {
        "high": "高",
        "medium": "中",
        "low": "低",
    }.get(confidence, "低")
    if estimate is None:
        return "未知"
    if minimum is not None and maximum is not None and minimum != maximum:
        return f"约 {minimum}-{maximum}（估算，置信度{confidence_label}）"
    return f"约 {estimate}（估算，置信度{confidence_label}）"


def _monthly_sales_for_scoring(product: NormalizedProduct) -> int:
    return _positive_int(product.features.get("monthly_sales")) or _positive_int(
        product.features.get("monthly_sales_estimate")
    ) or 0


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _int_feature(product: NormalizedProduct, key: str) -> int:
    value = product.features.get(key)
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
