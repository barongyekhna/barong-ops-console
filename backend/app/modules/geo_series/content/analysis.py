"""Per-piece review aid — DeepSeek-flash reads each generated GEO article.

The operator reviews English, AI-written guide content. To judge it they need to
know what it actually says, what job it does in a GEO answer, and why it is
phrased that way. This asks DeepSeek (the cheap ``deepseek-v4-flash`` tier, by
the owner's ruling) to read THAT specific piece and report in Chinese.

Fail-open by design: the analysis is a reading aid, never a gate. If DeepSeek is
down or returns junk, the content still stands and the UI simply shows nothing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_PROVIDER = "deepseek"
_TASK_TYPE = "content_analysis"

ANALYSIS_SKILL_VERSION = "geo-analysis-v1"


def analysis_instruction() -> str:
    return (
        "你是这家 DTC 品牌的 GEO(生成式引擎优化)审稿助手。下面给你**一篇**已经生成的"
        "站内导购内容。请你**真正读完这一篇**,然后用中文回答,帮助运营者审核。\n"
        "\n"
        "**绝对要求:必须针对这一篇的具体内容作答。**禁止套话、禁止泛泛而谈"
        "(例如「这篇内容有助于提升SEO」这种废话)。每一条都要引用/指向这篇里"
        "真实出现的句子、数据或结构。如果这篇写得不好,直接说哪里不好。\n"
        "\n"
        "要回答的:\n"
        "1. translation:把这篇内容(标题+正文/问答)**完整翻译成通顺的中文散文**。"
        "只输出译文本身——不要复述原文的 JSON 结构、不要出现花括号或字段名。\n"
        "2. geo_role:这一篇在 GEO 里具体起什么作用——买家**问什么问题**时,AI 可能"
        "引用它?引用的会是**哪一段**?\n"
        "3. why_written_this_way:为什么这篇要这么组织和措辞(标题为什么这么起、段落"
        "为什么这么排、为什么提到某个事实)。结合这篇的实际写法讲。\n"
        "4. strengths:这一篇具体的优点(2-4 条,每条指向真实内容)。\n"
        "5. risks:这一篇具体的问题或可改进处(1-4 条;真没有就给空数组,别硬凑)。\n"
        "\n"
        "只返回 JSON,不要 markdown 代码块,不要 JSON 之外的任何文字:\n"
        '{"translation":"...","geo_role":"...","why_written_this_way":"...",'
        '"strengths":["..."],"risks":["..."]}'
    )


def _item_payload(item: Any) -> dict[str, Any]:
    body = item.body_json if isinstance(item.body_json, dict) else {}
    return {
        "item_type": item.item_type,
        "title": item.title,
        "sections": body.get("sections") or [],
        "answer_blocks": body.get("answer_blocks") or [],
        "seo": item.seo_json if isinstance(item.seo_json, dict) else {},
    }


def _coerce_result(raw: Any) -> dict[str, Any] | None:
    """Providers occasionally wrap JSON in prose or a code fence."""
    if isinstance(raw, dict) and any(
        key in raw for key in ("translation", "geo_role", "why_written_this_way")
    ):
        return raw
    text: str | None = None
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, dict):
        for key in ("content", "text", "output", "result", "message"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                text = value
                break
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _as_str_list(value: Any, *, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v or "").strip()][:limit]


def analyze_content(
    content: dict[str, Any], *, topic: str, user: Any | None = None
) -> dict[str, Any] | None:
    """Ask DeepSeek-flash to read one piece. Returns None on any failure.

    Takes a plain snapshot (not an ORM object) so callers can release their DB
    transaction before this network call — the ~30s round trip would otherwise be
    killed by the idle-in-transaction timeout.
    """
    from ....db.session import SessionLocal
    from ....services.ai_provider_router import AIExecutionRouter
    from ...k_series.product_knowledge.constants import (
        MODULE_KEY as K_MODULE_KEY,
        TARGET_ORGANIZATION_NAME,
    )

    payload = {
        "task": "geo_content_analysis",
        "instruction": analysis_instruction(),
        "topic": topic,
        "content": content,
    }
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
    except Exception:  # noqa: BLE001 - reading aid must never break generation
        logger.exception("GEO content analysis provider call failed")
        return None
    finally:
        provider_db.close()

    parsed = _coerce_result(raw)
    if parsed is None:
        logger.warning("GEO content analysis returned unparseable output")
        return None
    return {
        "translation": str(parsed.get("translation") or "").strip(),
        "geo_role": str(parsed.get("geo_role") or "").strip(),
        "why_written_this_way": str(parsed.get("why_written_this_way") or "").strip(),
        "strengths": _as_str_list(parsed.get("strengths")),
        "risks": _as_str_list(parsed.get("risks")),
        "model": "deepseek-v4-flash",
        "skill_version": ANALYSIS_SKILL_VERSION,
    }


def analyze_item(item: Any, *, topic: str, user: Any | None = None) -> dict[str, Any] | None:
    """Analyse one ORM item (single-item path; the caller owns its transaction)."""
    return analyze_content(_item_payload(item), topic=topic, user=user)


def attach_analysis_safely(
    db: Any, items: list[Any], *, topic: str, user: Any | None = None
) -> int:
    """Analyse each piece and persist it, one short transaction at a time.

    死规矩(本仓库踩过两次): never hold a DB transaction across an outbound call.
    Snapshot every payload first, COMMIT to release the read transaction, then do
    the (~30s each) DeepSeek round trips with no transaction open, writing each
    result in its own short-lived session. Holding the session across five calls
    got the connection killed by the idle-in-transaction timeout.
    """
    from ....db.session import SessionLocal
    from sqlalchemy import update

    from .models import GeoContentItem

    snapshots = [(item.id, _item_payload(item)) for item in items]
    if not snapshots:
        return 0
    # Release the transaction BEFORE any network call.
    db.commit()

    done = 0
    for item_id, payload in snapshots:
        try:
            result = analyze_content(payload, topic=topic, user=user)
        except Exception:  # noqa: BLE001 - belt and braces
            logger.exception("GEO analysis crashed for item %s", item_id)
            result = None
        if not result:
            continue
        try:
            with SessionLocal() as writer:
                writer.execute(
                    update(GeoContentItem)
                    .where(GeoContentItem.id == item_id)
                    .values(analysis_json=result)
                )
                writer.commit()
            done += 1
        except Exception:  # noqa: BLE001 - persistence of a reading aid is optional
            logger.exception("GEO analysis persist failed for item %s", item_id)
    return done


# Shared with critique.py: providers wrap JSON in prose/code fences.
coerce_json_result = _coerce_result

__all__ = [
    "analysis_instruction",
    "coerce_json_result",
    "analyze_content",
    "analyze_item",
    "attach_analysis_safely",
    "ANALYSIS_SKILL_VERSION",
]
