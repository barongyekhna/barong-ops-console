"""K16-A SERP data model.

This package defines the SERP market data structure only. It does not implement
SERP provider calls, keyword analysis, AI filtering, SEO logic, ranking, routes,
or persistence behavior.
"""

from .models import (
    K16_A_MODE,
    K16_EXTERNAL_ACCESS,
    K16_RUNTIME,
    SERPItem,
    SERPResult,
)

__all__ = [
    "SERPResult",
    "SERPItem",
    "K16_A_MODE",
    "K16_RUNTIME",
    "K16_EXTERNAL_ACCESS",
]
