"""GEO content module constants.

Scope defaults are shared with K so a GEO cluster lives in the same tenant scope
as the K products whose facts it draws from.
"""

from __future__ import annotations

from ...k_series.product_knowledge.constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_SCOPE_MODE,
    DEFAULT_WORKSPACE_KEY,
)

MODULE_KEY = "geo.content"

PERMISSION_READ = "geo.content.read"
PERMISSION_EXECUTE = "geo.content.execute"
PERMISSION_MANAGE = "geo.content.manage"
PERMISSION_KEYS: tuple[str, ...] = (
    PERMISSION_READ,
    PERMISSION_EXECUTE,
    PERMISSION_MANAGE,
)

# The kinds of guide pieces a topic cluster can hold. `hub` is the topic overview
# (how-to-choose); the rest are the AI-citable spokes. `product_spotlight` is the
# opt-in article for a differentiated product inside a shared cluster (e.g. a
# panda-shaped shower next to the plain one) — it keeps that product's distinct
# selling points without splitting the topic into duplicate clusters.
#
# `question_answer` is the one type that REPEATS: one article answering exactly one
# buyer question. The singleton types fill up after five pieces and a cluster goes
# "full", which is wrong — terrain monitoring (M4) showed the winnable ground is
# specific questions ("how long does it last", "what goes wrong"), and each of those
# deserves its own page rather than a paragraph inside a combined FAQ.
ITEM_TYPES: tuple[str, ...] = (
    "hub",
    "how_it_works",
    "comparison",
    "scenario",
    "qa",
    "question_answer",
    "product_spotlight",
)

# Types a cluster may hold more than one of. Everything else is a singleton, so a
# re-run never produces a second hub competing with the first.
REPEATABLE_ITEM_TYPES: frozenset[str] = frozenset(
    {"question_answer", "product_spotlight"}
)

# Generation job types processed by the standalone geo-worker.
JOB_TYPE_CONTENT = "geo_content"
JOB_TYPES: tuple[str, ...] = (JOB_TYPE_CONTENT,)

__all__ = [
    "MODULE_KEY",
    "PERMISSION_READ",
    "PERMISSION_EXECUTE",
    "PERMISSION_MANAGE",
    "PERMISSION_KEYS",
    "ITEM_TYPES",
    "REPEATABLE_ITEM_TYPES",
    "JOB_TYPE_CONTENT",
    "JOB_TYPES",
    "DEFAULT_WORKSPACE_KEY",
    "DEFAULT_BUSINESS_CONTEXT",
    "DEFAULT_SCOPE_MODE",
]
