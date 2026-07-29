"""Refuse to write when there is nothing verifiable to say.

The grounding rule ("never state a number that is not in the product facts") stops
the model from **inventing**. It does nothing about **emptiness**. Given a product
nobody has described, the model does not break a rule — it writes fluent,
audit-clean, entirely hollow prose. That is how AI slop is manufactured, and it is
the one failure the output guards cannot catch, because there is nothing wrong with
any individual sentence.

Live evidence (2026-07-29, same console, same prompt):

    PSPE-001 (camping shower)  22 numbers, 14 selling points  → strong articles
    ET-001…005 (squishy toys)  0-3 numbers, 5-9 selling points → also fine, actually

That second row corrected the first draft of this gate. "Few numbers" was assumed
to mean "nothing to say", and a live run disproved it: the squishy guide came out
specific and honest (cheese vs butter-stick vs cat, TPR, silent, single vs
multi-pack) because **fact density requirements are category-dependent**. A camping
shower is a spec-driven purchase; a squishy toy is a preference-driven one, and its
distinguishing facts are shape, material and noise — which K does hold.

So the gate blocks on genuine emptiness only — no numbers AND no specs AND no
selling points, i.e. a product nobody has described yet — and merely *warns* when
density is low, so the operator knows the piece will read thin. Blocking on low
density would have refused a cluster that writes perfectly well.
"""

from __future__ import annotations

from typing import Any

# A floor against emptiness, not a quality bar; the critique loop handles quality.
# Any ONE of these makes a product describable, because different categories are
# decided on different evidence (measurements vs material/shape/behaviour).
MIN_DESCRIBABLE_FACTS = 1
# Below this the piece will read thin — worth saying out loud, not worth refusing.
LOW_DENSITY_NUMBERS = 3


def product_fact_report(facts: dict[str, Any], numbers: set[str]) -> dict[str, Any]:
    """How much verified material one product actually carries."""
    specs = facts.get("specs")
    selling_points = facts.get("selling_points")
    return {
        "sku": facts.get("sku") or facts.get("product_key") or "",
        "name": facts.get("product_name") or "",
        "numbers": len(numbers),
        "specs": len(specs) if isinstance(specs, (list, dict)) else 0,
        "selling_points": (
            len(selling_points) if isinstance(selling_points, list) else 0
        ),
    }


def _describable(report: dict[str, Any]) -> bool:
    """Has anyone described this product at all?"""
    return (
        int(report.get("numbers") or 0)
        + int(report.get("specs") or 0)
        + int(report.get("selling_points") or 0)
    ) >= MIN_DESCRIBABLE_FACTS


def fact_blockers(reports: list[dict[str, Any]]) -> list[str]:
    """Chinese, actionable: why writing must not start. Empty = go ahead."""
    if not reports:
        return ["这个话题簇下面没有产品——先从 P 上架一个产品把簇挂起来。"]

    empty = [r for r in reports if not _describable(r)]
    if len(empty) == len(reports):
        names = "、".join(str(r.get("sku") or r.get("name") or "?") for r in reports[:5])
        return [
            f"簇里的产品在 K 里还没有任何可用事实（{names}）——没有规格、没有卖点。"
            "现在生成只会写出正确的废话。先去 K 把这些产品描述出来（可测量的数据，"
            "或材质、造型、使用方式这类真实属性），再来生成。"
        ]
    if empty:
        names = "、".join(str(r.get("sku") or r.get("name") or "?") for r in empty[:5])
        return [
            f"有 {len(empty)} 个产品在 K 里完全没有事实：{names}。"
            "它们会被写进内容却无话可说——先补上，或先把它们从这个簇里摘掉。"
        ]
    return []


def fact_warnings(reports: list[dict[str, Any]]) -> list[str]:
    """Not blocking, but the operator should know the piece will read thin."""
    thin = [
        r for r in reports if int(r.get("numbers") or 0) < LOW_DENSITY_NUMBERS
    ]
    if not thin:
        return []
    names = "、".join(str(r.get("sku") or r.get("name") or "?") for r in thin[:5])
    return [
        f"{len(thin)} 个产品的可测量数据偏少（{names}）。内容仍会写，但会更依赖"
        "材质/造型/用法这类定性事实——如果这个品类本来就该有数字（尺寸、容量、"
        "时长），补进 K 会让文章明显更硬。"
    ]


__all__ = [
    "LOW_DENSITY_NUMBERS",
    "MIN_DESCRIBABLE_FACTS",
    "fact_blockers",
    "fact_warnings",
    "product_fact_report",
]
