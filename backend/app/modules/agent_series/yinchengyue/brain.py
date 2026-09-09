"""殷承岳的脑子:两次 flash 调用,都只输出 JSON。

第一次把用户的话(多半是中文)翻成几个英文搜索词;第二次在代码查出来的真实候选里
选一个。模型从头到尾没有机会自己「发明」一个类目——它拿不到候选以外的 id。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from ....db.session import SessionLocal
from ....services.ai_provider_router import AIExecutionRouter
from ...k_series.product_knowledge.constants import (
    MODULE_KEY as K_MODULE_KEY,
    TARGET_ORGANIZATION_NAME,
)
from .constants import MAX_KEYWORDS, ai_timeout_seconds

_LOGGER = logging.getLogger("yinchengyue.brain")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class KeywordHint(BaseModel):
    """第一步的产出:用来查类目表的英文词。"""

    is_product_question: bool = True
    product_en: str = ""
    keywords_en: list[str] = Field(default_factory=list)
    material_en: str | None = None
    use_en: str | None = None

    @field_validator("keywords_en", mode="before")
    @classmethod
    def _clean_keywords(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            word = str(item or "").strip().strip(".,;:\"'")
            if not word or len(word) > 40:
                continue
            if word.lower() in {w.lower() for w in cleaned}:
                continue
            cleaned.append(word)
        return cleaned[:MAX_KEYWORDS]


class AltChoice(BaseModel):
    id: str = ""
    reason_zh: str = ""


class RawChoice(BaseModel):
    """第二步的产出:候选 id + 置信 + 理由。id 是否真在候选里由 classifier 校验。"""

    chosen_id: str = "NONE"
    confidence: Literal["high", "medium", "low"] = "low"
    reason_zh: str = ""
    alternates: list[AltChoice] = Field(default_factory=list)

    @field_validator("chosen_id", mode="before")
    @classmethod
    def _str_id(cls, value: Any) -> str:
        return str(value or "NONE").strip()

    @field_validator("confidence", mode="before")
    @classmethod
    def _norm_conf(cls, value: Any) -> str:
        v = str(value or "low").strip().lower()
        return v if v in {"high", "medium", "low"} else "low"

    @field_validator("alternates", mode="before")
    @classmethod
    def _cap_alternates(cls, value: Any) -> list[Any]:
        if not isinstance(value, list):
            return []
        out = []
        for item in value[:4]:
            if isinstance(item, dict):
                out.append({"id": str(item.get("id") or ""), "reason_zh": str(item.get("reason_zh") or item.get("reason") or "")})
        return out


# 「json」这个词必须出现在提示词里,否则 DeepSeek 的 json_object 模式直接报错。
KEYWORD_PROMPT = """你是贸易公司的产品助理「殷承岳」。用户会用中文或英文描述一个产品(可能是 1688 标题、一句口语、一段规格)。
你的任务只有一个:把它翻成用来在「谷歌商品分类树」(Google Product Taxonomy,英文)里检索的英文词。

只输出一个 JSON 对象,字段:
- is_product_question: 用户是否在描述/询问一个具体产品(true/false)。打招呼、闲聊、问你是谁 → false
- product_en: 一句英文产品描述(≤ 20 词),说清它是什么、给谁用、用在哪
- keywords_en: 3 到 6 个英文检索词,每个 1 到 3 个单词,优先写谷歌分类里常见的类目叫法(如 "camping cookware", "vacuum insulated bottle", "solar lantern"),从具体到宽泛排列
- material_en: 主要材质的英文,没有则 null
- use_en: 使用场景/用途的英文,没有则 null

规则:
- 不要编造用户没说的功能
- 只输出 json,不要解释"""

KEYWORD_FEW_SHOTS: list[tuple[str, dict[str, Any]]] = [
    (
        "露营炊具套装,铝合金锅两个加一个折叠炉头,户外野炊用的",
        {"is_product_question": True, "product_en": "aluminum camping cookware set with two pots and a folding stove for outdoor cooking", "keywords_en": ["camping cookware", "camping cooking set", "portable cooking stove", "outdoor cookware", "camping and hiking"], "material_en": "aluminum alloy", "use_en": "outdoor camping cooking"},
    ),
    (
        "304不锈钢真空保温杯500ml 车载便携 商务礼品定制LOGO",
        {"is_product_question": True, "product_en": "304 stainless steel vacuum insulated travel bottle 500ml for car and business gifts", "keywords_en": ["vacuum insulated bottle", "thermos", "insulated tumbler", "water bottle", "drinkware"], "material_en": "304 stainless steel", "use_en": "keeping drinks hot or cold on the go"},
    ),
    (
        "你好在吗",
        {"is_product_question": False, "product_en": "", "keywords_en": [], "material_en": None, "use_en": None},
    ),
]

CHOICE_PROMPT = """你是贸易公司的产品助理「殷承岳」。下面给你一个产品描述和一份「候选类目清单」(来自谷歌商品分类树,每行:id | 英文完整路径 | 中文名)。
你的任务:从清单里挑出这个产品最应归属的那一个类目。

只输出一个 JSON 对象,字段:
- chosen_id: 清单里某一行的 id;清单里没有合适的就填 "NONE"
- confidence: "high" / "medium" / "low"
- reason_zh: 一两句中文,说明为什么是它、为什么不是相近的那个(≤ 120 字)
- alternates: 0 到 2 个备选,每个 {"id": 清单里的 id, "reason_zh": 什么情况下应该选它}

铁律:
- chosen_id 和 alternates 里的 id 必须原样来自清单,清单外的 id 一律不许出现
- 优先选最具体的叶子类目;宁可 "NONE" 也不要硬凑
- 只输出 json,不要解释"""


def _parse_json_result(result: Any) -> dict[str, Any] | None:
    """路由器可能返回解析好的 dict、{"content": raw}、或原始响应。只认能变成 dict 的。"""
    payload: Any = result
    if isinstance(result, dict) and isinstance(result.get("content"), str):
        raw = _FENCE.sub("", result["content"].strip())
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
    elif isinstance(result, str):
        try:
            payload = json.loads(_FENCE.sub("", result.strip()))
        except (TypeError, ValueError):
            return None
    return payload if isinstance(payload, dict) else None


def parse_keyword_hint(result: Any) -> KeywordHint:
    payload = _parse_json_result(result)
    if payload is None:
        return KeywordHint(is_product_question=False)
    try:
        return KeywordHint.model_validate(payload)
    except ValidationError:
        return KeywordHint(is_product_question=False)


def parse_choice(result: Any) -> RawChoice:
    payload = _parse_json_result(result)
    if payload is None:
        return RawChoice()
    try:
        return RawChoice.model_validate(payload)
    except ValidationError:
        return RawChoice()


def build_keyword_messages(text: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": KEYWORD_PROMPT}]
    for user, answer in KEYWORD_FEW_SHOTS:
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})
    messages.append({"role": "user", "content": text})
    return messages


def build_choice_messages(text: str, hint: KeywordHint, candidates: list[Any]) -> list[dict[str, str]]:
    lines = [f"{c.id} | {c.full_path} | {c.name_zh or '-'}" for c in candidates]
    user = (
        f"产品描述(用户原话):{text}\n"
        f"英文理解:{hint.product_en or '-'};材质:{hint.material_en or '-'};用途:{hint.use_en or '-'}\n\n"
        "候选类目清单:\n" + "\n".join(lines)
    )
    return [{"role": "system", "content": CHOICE_PROMPT}, {"role": "user", "content": user}]


def _run_json(messages: list[dict[str, str]]) -> Any:
    """跑一次 flash 并记台账。任何异常往上抛——调用方负责回「没接通」。"""
    from r_system_v2.ra.quota_ledger import (  # noqa: PLC0415
        PROVIDER_AGENT_CHAT_YINCHENGYUE,
        refund,
        try_consume,
    )

    ledger_db = SessionLocal()
    charged = False
    try:
        try_consume(ledger_db, PROVIDER_AGENT_CHAT_YINCHENGYUE)
        charged = True
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("台账记账失败(不拦调用): %s", exc)
    finally:
        ledger_db.close()

    provider_db = SessionLocal()
    try:
        timeout = ai_timeout_seconds()
        return AIExecutionRouter(
            provider_db,
            timeout_seconds=timeout,
            total_budget_seconds=timeout * 1.5,
        ).execute(
            provider="deepseek",
            task_type="agent_chat",
            payload={
                "messages": messages,
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
            org=TARGET_ORGANIZATION_NAME,
            module_id=K_MODULE_KEY,
        )
    except Exception:
        if charged:
            refund_db = SessionLocal()
            try:
                refund(refund_db, PROVIDER_AGENT_CHAT_YINCHENGYUE)
            except Exception:  # noqa: BLE001
                pass
            finally:
                refund_db.close()
        raise
    finally:
        provider_db.close()


def extract_keywords(text: str) -> KeywordHint:
    return parse_keyword_hint(_run_json(build_keyword_messages(text)))


def choose_category(text: str, hint: KeywordHint, candidates: list[Any]) -> RawChoice:
    return parse_choice(_run_json(build_choice_messages(text, hint, candidates)))
