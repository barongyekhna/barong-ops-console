"""Turn scattered per-piece critiques into module-level signal.

One critique on one article is a note. The SAME critique across most of a
cluster is a defect in the generation prompt — the fix belongs in the skill, not
in a hand-edit. This aggregates every piece's critiques, asks DeepSeek-flash to
name the recurring patterns, and separates out the critiques that cannot be
fixed by rewriting at all because the product data is missing — those are data
gaps to fill in K.

Deterministic parts (collecting critiques, collecting data gaps) never touch the
network; only the pattern-naming step calls a provider, and it fails open.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PROVIDER = "deepseek"
_TASK_TYPE = "content_analysis"


def summary_instruction() -> str:
    return (
        "下面是同一个话题簇里**多篇**站内导购内容各自收到的审稿批评。请你归纳:"
        "**哪些批评是反复出现的**——也就是说,问题不在某一篇,而在生成这些内容的"
        "**提示词/写作规范**本身。\n"
        "\n"
        "要求:\n"
        "- 只归纳**真正重复出现**的模式(至少影响 2 篇);只出现一次的个别问题不要列。\n"
        "- 每个模式要给出**具体可执行的修改建议**——建议应该是「在写作规范里加/改什么」,"
        "而不是「这篇再改改」。\n"
        "- 用中文。禁止套话,必须贴着这些批评的实际内容讲。\n"
        "- 如果确实没有重复模式,`patterns` 返回空数组,别硬凑。\n"
        "\n"
        "只返回 JSON,不要 markdown:\n"
        '{"patterns":[{"pattern":"<反复出现的问题,一句话>","affected_count":<受影响篇数>,'
        '"suggested_fix":"<对写作规范的具体修改建议>"}]}'
    )


def collect_critiques(items: list[Any]) -> list[dict[str, Any]]:
    """Every outstanding critique, with the piece it came from. Network-free."""
    out: list[dict[str, Any]] = []
    for item in items:
        analysis = item.analysis_json if isinstance(item.analysis_json, dict) else {}
        for risk in analysis.get("risks") or []:
            text = str(risk or "").strip()
            if text:
                out.append(
                    {
                        "item_id": str(item.id),
                        "item_type": item.item_type,
                        "title": item.title,
                        "critique": text,
                    }
                )
    return out


def collect_data_gaps(items: list[Any]) -> list[dict[str, Any]]:
    """Critiques a rewrite refused to fake, grouped by the missing fact.

    These are the ones no amount of rewriting can fix: the product data simply
    does not contain the fact. Fill them in K and the next generation has them.
    """
    gaps: dict[str, dict[str, Any]] = {}
    for item in items:
        revision = item.revision_json if isinstance(item.revision_json, dict) else {}
        for entry in revision.get("unaddressed") or []:
            if not isinstance(entry, dict) or not entry.get("needs_data"):
                continue
            fact = str(entry.get("missing_fact") or "").strip() or "（未指明）"
            bucket = gaps.setdefault(
                fact,
                {"missing_fact": fact, "reason": "", "items": [], "critiques": []},
            )
            bucket["items"].append({"item_id": str(item.id), "title": item.title})
            critique = str(entry.get("critique") or "").strip()
            if critique and critique not in bucket["critiques"]:
                bucket["critiques"].append(critique)
            if not bucket["reason"]:
                bucket["reason"] = str(entry.get("reason") or "").strip()
    return sorted(gaps.values(), key=lambda g: len(g["items"]), reverse=True)


def summarize_patterns(
    critiques: list[dict[str, Any]], *, topic: str, user: Any | None = None
) -> list[dict[str, Any]]:
    """Ask DeepSeek-flash to name the recurring patterns. Fails open to []."""
    if len(critiques) < 2:
        return []
    from ....db.session import SessionLocal
    from ....services.ai_provider_router import AIExecutionRouter
    from ...k_series.product_knowledge.constants import (
        MODULE_KEY as K_MODULE_KEY,
        TARGET_ORGANIZATION_NAME,
    )
    from .analysis import coerce_json_result

    payload = {
        "task": "geo_critique_summary",
        "instruction": summary_instruction(),
        "topic": topic,
        "critiques": [
            {"item_type": c["item_type"], "critique": c["critique"]}
            for c in critiques
        ],
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
    except Exception:  # noqa: BLE001 - a summary is advisory, never a gate
        logger.exception("GEO critique summary provider call failed")
        return []
    finally:
        provider_db.close()

    parsed = coerce_json_result(raw)
    if not isinstance(parsed, dict):
        return []
    patterns: list[dict[str, Any]] = []
    for entry in parsed.get("patterns") or []:
        if not isinstance(entry, dict):
            continue
        pattern = str(entry.get("pattern") or "").strip()
        if not pattern:
            continue
        try:
            count = int(entry.get("affected_count") or 0)
        except (TypeError, ValueError):
            count = 0
        patterns.append(
            {
                "pattern": pattern[:400],
                "affected_count": count,
                "suggested_fix": str(entry.get("suggested_fix") or "").strip()[:600],
            }
        )
    return patterns


__all__ = [
    "collect_critiques",
    "collect_data_gaps",
    "summarize_patterns",
    "summary_instruction",
]
