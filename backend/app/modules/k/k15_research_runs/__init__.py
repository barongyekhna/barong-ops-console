"""K15-A research run data model.

This package defines the standardized research run schema only. It does not
implement API routes, UI triggers, AI processing, SEO logic, ranking, or
persistence behavior.
"""

from .models import (
    K15_A_MODE,
    K15_EXTERNAL_ACCESS,
    K15_RUNTIME,
    RESEARCH_RUN_LIFECYCLE,
    RESEARCH_RUN_QUERY_TYPE,
    ResearchRun,
    ResearchRunSource,
    ResearchRunStatus,
)

__all__ = [
    "ResearchRun",
    "ResearchRunStatus",
    "ResearchRunSource",
    "RESEARCH_RUN_QUERY_TYPE",
    "RESEARCH_RUN_LIFECYCLE",
    "K15_A_MODE",
    "K15_RUNTIME",
    "K15_EXTERNAL_ACCESS",
]
