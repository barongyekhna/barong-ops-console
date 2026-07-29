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
ITEM_TYPES: tuple[str, ...] = (
    "hub",
    "how_it_works",
    "comparison",
    "scenario",
    "qa",
    "product_spotlight",
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
    "JOB_TYPE_CONTENT",
    "JOB_TYPES",
    "DEFAULT_WORKSPACE_KEY",
    "DEFAULT_BUSINESS_CONTEXT",
    "DEFAULT_SCOPE_MODE",
]
