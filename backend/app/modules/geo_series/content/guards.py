"""Output guards for generated GEO content (fail-closed).

Reuses K's tested primitives — brand blacklist + CJK detection — and adds a
numeric-grounding check: any number an AI writes into guide copy must appear in
the product's own verified evidence corpus (specs / selling points / package /
dimensions). This is the "evidence_guard 兜底" for the GEO content engine: it
stops the model from inventing competitor figures or unsupported specs, the same
class of bug the K FAQ fix addressed at the product page.

Brand rule (死命令): the ONLY brand allowed in any output is SITE_BRAND.
"""

from __future__ import annotations

import re
from typing import Any

from ...k_series.product_knowledge.brand_guard import (
    SITE_BRAND,
    blacklist_violations,
)
from ...k_series.product_knowledge.buyer_display import contains_cjk

_NUMBER = re.compile(r"(?<!\d)\d[\d,]*(?:\.\d+)?")
# Non-spec numerics that legitimately appear in prose and never need spec backing.
_GROUNDING_WHITELIST = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "0"}


def _canonical_number(token: str) -> str:
    return token.replace(",", "").rstrip("0").rstrip(".") if "." in token else token.replace(",", "")


def evidence_number_corpus(*fact_texts: Any) -> set[str]:
    """All numeric tokens present in the product's verified evidence."""
    corpus: set[str] = set()
    for text in fact_texts:
        for match in _NUMBER.finditer(str(text or "")):
            corpus.add(_canonical_number(match.group(0)))
    return corpus


def numbers_in_text(text: str) -> set[str]:
    """Spec-shaped numbers appearing in a piece of text."""
    return _numbers_in(text)


def _numbers_in(text: str) -> set[str]:
    return {_canonical_number(m.group(0)) for m in _NUMBER.finditer(text or "")}


def item_text_surfaces(item: dict[str, Any]) -> list[tuple[str, str]]:
    """Buyer-facing text fields of a generated content item (label -> text)."""
    surfaces: list[tuple[str, str]] = []
    title = str(item.get("title") or "").strip()
    if title:
        surfaces.append(("title", title))
    for idx, section in enumerate(item.get("sections") or []):
        if isinstance(section, dict):
            for field in ("heading", "body"):
                value = str(section.get(field) or "").strip()
                if value:
                    surfaces.append((f"section[{idx}].{field}", value))
    for idx, block in enumerate(item.get("answer_blocks") or []):
        if isinstance(block, dict):
            for field in ("question", "answer"):
                value = str(block.get(field) or "").strip()
                if value:
                    surfaces.append((f"answer[{idx}].{field}", value))
    seo = item.get("seo")
    if isinstance(seo, dict):
        for field in ("title", "meta_description"):
            value = str(seo.get(field) or "").strip()
            if value:
                surfaces.append((f"seo.{field}", value))
    return surfaces



# --------------------------------------------------------------- derived numbers
# The grounding rule checks membership in the evidence corpus, which cannot tell
# "invented" from "computed". That punished precision: "approximately 2 minutes"
# passed (2 matched the 2-hour charge time) while the correct "about 2.4 minutes"
# (5 gal ÷ 2.11 GPM) was rejected — and arithmetic is exactly what questions like
# "how long does 5 gallons last" are asking for.
#
# So a computed number is allowed only if the writer SHOWS ITS WORK: it declares
# `{"value": 2.4, "from": "5 / 2.11"}`, every operand is itself grounded (product
# facts) or given by the question, and this guard actually evaluates the expression
# and checks the result. Still fail-closed — a wrong sum or an undeclared operand
# is rejected — but the model may now do arithmetic.

_ARITHMETIC = re.compile(r"^[0-9\s.+\-*/()]+$")


def _safe_eval(expression: str) -> float | None:
    """Evaluate a pure-arithmetic expression. Anything else returns None."""
    import ast

    text = str(expression or "").strip()
    if not text or len(text) > 120 or not _ARITHMETIC.match(text):
        return None
    allowed = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd,
    )
    try:
        tree = ast.parse(text, mode="eval")
        for node in ast.walk(tree):
            if not isinstance(node, allowed):
                return None
            if isinstance(node, ast.Constant) and not isinstance(
                node.value, (int, float)
            ):
                return None
        return float(eval(compile(tree, "<derived>", "eval"), {"__builtins__": {}}, {}))
    except Exception:  # noqa: BLE001 - any parse/zero-division failure means reject
        return None


def verify_derived_numbers(
    derived: Any,
    *,
    evidence_numbers: set[str],
    context_numbers: set[str] | None = None,
) -> tuple[set[str], list[dict[str, str]]]:
    """(numbers now allowed, rejected declarations with a reason).

    ``context_numbers`` are the ones the question itself supplies ("5 gallon"),
    which are given rather than invented.
    """
    known = set(evidence_numbers) | set(context_numbers or set())
    verified: set[str] = set()
    rejected: list[dict[str, str]] = []
    if not isinstance(derived, list):
        return verified, rejected

    for entry in derived[:20]:
        if not isinstance(entry, dict):
            continue
        raw_value = str(entry.get("value") or "").strip()
        expression = str(entry.get("from") or "").strip()
        if not raw_value or not expression:
            rejected.append({"value": raw_value, "from": expression,
                             "reason": "缺少 value 或 from"})
            continue

        # 操作数只认产品事实与问句本身。**不认接地白名单**——白名单是给散文里
        # 无害出现的小数字用的,拿它当算式输入,等于让模型用「3 + 4」拼出一个
        # 凭空的 7 小时续航,给编造洗白。
        operands = {_canonical_number(m.group(0)) for m in _NUMBER.finditer(expression)}
        unknown = sorted(operands - known)
        if unknown:
            rejected.append({"value": raw_value, "from": expression,
                             "reason": f"算式里的 {', '.join(unknown)} 没有来源"})
            continue

        computed = _safe_eval(expression)
        if computed is None:
            rejected.append({"value": raw_value, "from": expression,
                             "reason": "算式无法计算（只允许 + - * / 和括号）"})
            continue

        try:
            declared = float(raw_value.replace(",", ""))
        except ValueError:
            rejected.append({"value": raw_value, "from": expression,
                             "reason": "value 不是数字"})
            continue

        decimals = len(raw_value.split(".")[1]) if "." in raw_value else 0
        if round(computed, decimals) != round(declared, decimals):
            rejected.append({
                "value": raw_value, "from": expression,
                "reason": f"算错了：{expression} = {computed:.4f}，不是 {raw_value}",
            })
            continue
        verified.add(_canonical_number(raw_value))
    return verified, rejected


def audit_content_item(
    item: dict[str, Any],
    *,
    forbidden_terms: list[str],
    evidence_numbers: set[str],
    context_numbers: set[str] | None = None,
) -> dict[str, Any]:
    """Fail-closed audit of one generated content item.

    Returns ``{clean, brand_violations, cjk_surfaces, ungrounded_numbers}``.
    ``clean`` is True only when there are no third-party brands, no CJK leakage,
    and every spec-shaped number is backed by the evidence corpus.
    """
    surfaces = item_text_surfaces(item)

    brand = blacklist_violations(surfaces, forbidden_terms)

    cjk_surfaces = [label for label, text in surfaces if contains_cjk(text)]

    derived_ok, derived_rejected = verify_derived_numbers(
        item.get("derived_numbers"),
        evidence_numbers=evidence_numbers,
        context_numbers=context_numbers,
    )

    ungrounded: list[dict[str, str]] = []
    allowed = evidence_numbers | _GROUNDING_WHITELIST | derived_ok
    for label, text in surfaces:
        for token in _numbers_in(text) - allowed:
            ungrounded.append({"surface": label, "number": token})

    clean = not brand and not cjk_surfaces and not ungrounded and not derived_rejected
    return {
        "clean": clean,
        "site_brand": SITE_BRAND,
        "brand_violations": brand,
        "cjk_surfaces": cjk_surfaces,
        "ungrounded_numbers": ungrounded,
        "bad_derivations": derived_rejected,
    }


__all__ = [
    "numbers_in_text",
    "verify_derived_numbers",
    "evidence_number_corpus",
    "item_text_surfaces",
    "audit_content_item",
]
