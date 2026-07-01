"""Core Warehouse data contracts.

Runtime classes are imported from their concrete modules to avoid package-level
cycles between providers and the warehouse engine.
"""

from r_system_v2.rw.core.models import (
    IngestionRecord,
    KeepaProductData,
    NormalizedProduct,
    PipelineResult,
    ProductState,
    RuleDecision,
    RuleEvaluation,
)

__all__ = [
    "IngestionRecord",
    "KeepaProductData",
    "NormalizedProduct",
    "PipelineResult",
    "ProductState",
    "RuleDecision",
    "RuleEvaluation",
]
