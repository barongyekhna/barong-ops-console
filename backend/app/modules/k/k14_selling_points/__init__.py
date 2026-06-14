"""K14-A product selling points data model.

This package defines the normalized product selling points structure only. It
does not implement AI generation, normalization logic, persistence, routes, or
UI integration.
"""

from .models import (
    BulletCategory,
    BulletPoint,
    ProductSellingPoints,
    SellingPointSource,
)

__all__ = [
    "ProductSellingPoints",
    "BulletPoint",
    "BulletCategory",
    "SellingPointSource",
]
