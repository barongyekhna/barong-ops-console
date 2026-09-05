"""写手：把一格填成一条帖子。skill 全文进提示词，输出 JSON 按 skill §8。

出网付费调用当天接台账（PROVIDER_SM_WRITER）。模型输出不做「顺手修正」：
标签超了、首行长了都原样落库，交给审计标出来——静默修正就是把信息压扁。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from r_system_v2.ra.quota_ledger import PROVIDER_SM_WRITER, RAQuotaExhaustedError, try_consume

from ...db.session import SessionLocal
from ...services.ai_provider_router import AIExecutionRouter
from ..k_series.product_knowledge.constants import MODULE_KEY as K_MODULE_KEY
from ..k_series.product_knowledge.constants import TARGET_ORGANIZATION_NAME
from .prompt_skills import OUTPUT_KEYS, build_messages, skill_context
from .profiles import PlatformProfile

logger = logging.getLogger(__name__)

_PROVIDER = "deepseek"
_TASK_TYPE = "generate"


class WriterError(RuntimeError):
    def __init__(self, message: str, *, code: str = "WRITER_FAILED") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class QuotaExhausted(WriterError):
    pass


def _extract_text(raw: Any) -> str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        if any(key in raw for key in ("caption", "title", "blocked_reason")):
            return json.dumps(raw, ensure_ascii=False)
        for key in ("content", "text", "output", "result", "message"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, dict):
                return json.dumps(value, ensure_ascii=False)
    return None


def parse_output(raw: Any) -> dict[str, Any]:
    """模型偶尔把 JSON 包在围栏或散文里；抠出第一段 {...}。"""
    text = _extract_text(raw)
    if not text:
        raise WriterError("模型没有返回可解析的内容。", code="WRITER_EMPTY")
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:] if lines and lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].startswith("```") else lines
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.S)
        if not match:
            raise WriterError("模型输出不是 JSON。", code="WRITER_NOT_JSON") from None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise WriterError("模型输出的 JSON 解析失败。", code="WRITER_NOT_JSON") from exc
    if not isinstance(parsed, dict):
        raise WriterError("模型输出不是 JSON 对象。", code="WRITER_NOT_JSON")
    return normalize_output(parsed)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in re.split(r"[,\n]", value) if part.strip()]
    return []


def normalize_output(parsed: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {key: parsed.get(key) for key in OUTPUT_KEYS}
    for key in ("title", "caption", "first_line", "alt_text", "board", "cta", "keyword_primary", "blocked_reason", "platform", "pillar"):
        value = out.get(key)
        out[key] = str(value).strip() if value not in (None, "") else ""
    hashtags = []
    for tag in _as_list(out.get("hashtags")):
        cleaned = str(tag or "").strip().lstrip("#").lower()
        if cleaned:
            hashtags.append(cleaned)
    out["hashtags"] = hashtags
    out["keywords_secondary"] = [str(k).strip() for k in _as_list(out.get("keywords_secondary")) if str(k).strip()]
    out["facts_used"] = [str(k).strip() for k in _as_list(out.get("facts_used")) if str(k).strip()]
    out["overlay_texts"] = [str(k).strip() for k in _as_list(out.get("overlay_texts")) if str(k).strip()]
    derived = out.get("derived_numbers")
    out["derived_numbers"] = derived if isinstance(derived, list) else []
    return out


def generate(
    db: Session,
    *,
    profile: PlatformProfile,
    pillar: str,
    post_kind: str,
    source_snapshot: dict[str, Any],
    media_plan: list[dict[str, Any]],
    keyword_hints: dict[str, Any],
    user: Any | None,
    critique: list[str] | None = None,
    previous_output: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """调一次模型。返回 (normalized_output, skill_context)。**调用方先放掉长事务。**"""
    try:
        try_consume(db, PROVIDER_SM_WRITER, amount=1)
    except RAQuotaExhaustedError as exc:
        raise QuotaExhausted(f"社媒写手今日额度用尽：{exc}", code="WRITER_QUOTA") from exc
    context = skill_context()
    messages = build_messages(
        skill_markdown=context["skill_markdown"],
        profile=profile,
        pillar=pillar,
        post_kind=post_kind,
        source_snapshot=source_snapshot,
        media_plan=media_plan,
        keyword_hints=keyword_hints,
        critique=critique,
        previous_output=previous_output,
    )
    payload = {"task": "sm_image_post", "messages": messages}
    provider_db = SessionLocal()
    try:
        raw = AIExecutionRouter(provider_db).execute(
            provider=_PROVIDER,
            task_type=_TASK_TYPE,
            payload=payload,
            org=TARGET_ORGANIZATION_NAME,
            module_id=K_MODULE_KEY,
            user=user,
        )
    except Exception as exc:  # noqa: BLE001 - 统一成 WriterError 给任务表
        raise WriterError(f"写手调用失败：{str(exc)[:300]}", code="WRITER_PROVIDER") from exc
    finally:
        provider_db.close()
    return parse_output(raw), context


__all__ = ["QuotaExhausted", "WriterError", "generate", "normalize_output", "parse_output"]
