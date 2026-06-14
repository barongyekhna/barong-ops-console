"""K14-C API exposure layer for product selling points.

This module exposes the K14-B transformation capability through a FastAPI
router. It is mock-only, in-memory only, and does not register itself with the
application, access persistence, call external providers, or activate C14.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.app.modules.k.k13_ai_bridge.ai_bridge import AIAnalysisBridge as K13Bridge

from .consolidator import K14SuggestionConsolidator
from .models import ProductSellingPoints

K14_C_MODE = "api_exposure_layer"
K14_RUNTIME = "mock_only"
K14_EXTERNAL_ACCESS = False

SELLING_POINTS_CACHE: dict[str, ProductSellingPoints] = {}

selling_points_router = APIRouter(prefix="/k/selling-points", tags=["k-selling-points"])


class GenerateSellingPointsRequest(BaseModel):
    """Request payload for mock selling point generation."""

    product: dict[str, Any] = Field(min_length=1)
    mode: Literal["mock"] = "mock"


class _PrecomputedK13BridgeResult:
    """K13-compatible adapter that returns an already computed bridge result."""

    def __init__(self, k13_result: Mapping[str, Any]):
        self.k13_result = k13_result

    def analyze(self, product: Mapping[str, Any]) -> Mapping[str, Any]:
        del product
        return self.k13_result


class K14SellingPointsAPIService:
    """Service facade for exposing K14-B through the K14-C API layer."""

    def __init__(
        self,
        cache: dict[str, ProductSellingPoints] | None = None,
    ) -> None:
        self.cache = SELLING_POINTS_CACHE if cache is None else cache

    def generate(self, product: dict[str, Any]) -> ProductSellingPoints:
        k13_result = K13Bridge.analyze(product)
        structured = self._consolidate_bridge_result(product, k13_result)
        self.cache[structured.product_id] = structured
        return structured

    def get(self, product_id: str) -> ProductSellingPoints | None:
        return self.cache.get(product_id)

    @staticmethod
    def _consolidate_bridge_result(
        product: dict[str, Any],
        k13_result: Mapping[str, Any],
    ) -> ProductSellingPoints:
        bridge_result_engine = _PrecomputedK13BridgeResult(k13_result)
        consolidator = K14SuggestionConsolidator(
            k13_engine=bridge_result_engine,
            k14_schema=ProductSellingPoints,
        )
        return consolidator.convert(product)


selling_points_service = K14SellingPointsAPIService()


@selling_points_router.post(
    "/generate",
    response_model=ProductSellingPoints,
    status_code=status.HTTP_201_CREATED,
)
def generate_selling_points(
    payload: GenerateSellingPointsRequest,
) -> ProductSellingPoints:
    return selling_points_service.generate(payload.product)


@selling_points_router.get(
    "/{product_id}",
    response_model=ProductSellingPoints,
)
def get_selling_points(product_id: str) -> ProductSellingPoints:
    cached = selling_points_service.get(product_id)
    if cached is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Selling points for product '{product_id}' were not generated.",
        )
    return cached
