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

from ..k_series.product_knowledge.brand_guard import (
    SITE_BRAND,
    blacklist_violations,
)
from ..k_series.product_knowledge.buyer_display import contains_cjk

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
    previous_audit: dict[str, Any] | None = None,
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

    audit = {
        "site_brand": SITE_BRAND,
        "brand_violations": brand,
        "cjk_surfaces": cjk_surfaces,
        "ungrounded_numbers": ungrounded,
        "bad_derivations": derived_rejected,
        # 人工放行清单跨重写**结转**:重写会从零重算这份 audit,不带过来的话
        # 上一轮放行过的误报下一轮又把文章拦住,而且人不知道为什么。
        "ignored_findings": sorted(
            {
                str(fp)
                for fp in (previous_audit or {}).get("ignored_findings") or []
                if str(fp).strip()
            }
        ),
    }
    # `clean` 只在这一个地方被决定(见 recompute_audit_clean 的 docstring)。
    return recompute_audit_clean(audit)


# ---------------------------------------------------------------- 人工放行

# 能被人工放行的三族。**``bad_derivations`` 不在里面,而且永远不该在。**
IGNORABLE_KINDS: tuple[str, ...] = ("brand", "cjk", "number")
DERIVATION_KIND = "derivation"


class UnignorableFinding(ValueError):
    """试图放行一条不允许放行的发现。"""


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def content_finding_fingerprint(kind: str, finding: Any) -> str:
    """一条发现的稳定指纹,跨审查重跑保持一致。格式照 K 的
    ``brand_guard.brand_finding_fingerprint``,只是内容侧有四族而不是两族。

    ``surface`` 用 ``item_text_surfaces`` 生成的标签(``section[0].heading``
    / ``answer[2].answer`` / ``seo.title`` / ``title``)。
    """
    data = finding if isinstance(finding, dict) else {"surface": finding}
    if kind == "brand":
        return f"brand::{_norm(data.get('surface'))}::{_norm(data.get('term'))}"
    if kind == "cjk":
        return f"cjk::{_norm(data.get('surface'))}"
    if kind == "number":
        return f"number::{_norm(data.get('surface'))}::{_norm(data.get('number'))}"
    if kind == DERIVATION_KIND:
        # 有指纹是为了能在日志/诊断里指认它,**不代表它可以被放行**。
        return f"derivation::{_norm(data.get('value'))}::{_norm(data.get('from'))}"
    return f"{kind}::{_norm(data)}"


def assert_ignorable(kind: str) -> None:
    """``bad_derivations`` 永远不能人工放行。

    它不是误报族。``verify_derived_numbers`` **真的把算式算了一遍** —— 落进
    ``bad_derivations`` 意味着模型声明的算式和它写出来的数字对不上,或者操作数
    根本没有来源。放行它 = 主动把一个算错的数字发到面向美国买家的页面上。
    要么改数,要么重写。
    """
    if kind not in IGNORABLE_KINDS:
        raise UnignorableFinding(
            "算错的数字不能人工放行——校验器真的算过一遍。改数或者重写。"
            if kind == DERIVATION_KIND
            else f"未知的发现类型：{kind!r}"
        )


def audit_finding_fingerprints(audit: Any) -> list[str]:
    """这份 audit 里全部**可放行**发现的指纹。

    ``bad_derivations`` **不计入** —— 它不可放行,所以永远算作未解决,
    否则「放行完就 clean 了」会把一个算错的数字放上线。
    """
    data = audit if isinstance(audit, dict) else {}
    out = [
        content_finding_fingerprint("brand", v)
        for v in data.get("brand_violations") or []
    ]
    out += [
        content_finding_fingerprint("cjk", {"surface": s})
        for s in data.get("cjk_surfaces") or []
    ]
    out += [
        content_finding_fingerprint("number", v)
        for v in data.get("ungrounded_numbers") or []
    ]
    return out


def audit_unresolved(audit: Any) -> list[str]:
    """扣掉放行清单之后仍未解决的发现。"""
    data = audit if isinstance(audit, dict) else {}
    ignored = {str(fp) for fp in data.get("ignored_findings") or []}
    unresolved = [fp for fp in audit_finding_fingerprints(data) if fp not in ignored]
    # 算错的数永不可忽略,直接计入未解决。
    unresolved += [
        content_finding_fingerprint(DERIVATION_KIND, row)
        for row in data.get("bad_derivations") or []
    ]
    return unresolved


def recompute_audit_clean(audit: dict[str, Any]) -> dict[str, Any]:
    """按放行清单重算 ``clean``,原地写回并返回同一个 dict。

    **全仓库只有这一个地方决定 clean 是什么。** 原来 ``audit_content_item``
    里有一行内联的 `clean = not brand and not cjk and ...`,而四个门禁各自
    ``.get("clean")`` —— 其中 SEO 两处还写的是 ``.get("clean", True)``
    (缺审查记录 = 放行),和 GEO 正好相反。收敛成一处之后这类分叉不可能再发生。
    """
    unresolved = audit_unresolved(audit)
    audit["unresolved_count"] = len(unresolved)
    audit["clean"] = not unresolved
    return audit


def audit_is_clean(audit: Any) -> bool:
    """门禁统一读这个。**缺审查记录一律当作不通过**(fail-closed)。

    没审过不等于审过了。SEO 原来两处是 fail-open,一篇从没审过的文章可以直接
    批准并发布出去。
    """
    return bool(isinstance(audit, dict) and audit and audit.get("clean"))


__all__ = [
    "DERIVATION_KIND",
    "IGNORABLE_KINDS",
    "UnignorableFinding",
    "assert_ignorable",
    "audit_content_item",
    "audit_finding_fingerprints",
    "audit_is_clean",
    "audit_unresolved",
    "content_finding_fingerprint",
    "evidence_number_corpus",
    "item_text_surfaces",
    "numbers_in_text",
    "recompute_audit_clean",
    "verify_derived_numbers",
]
