"""Keepa adapter with mandatory mock-mode safety."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from r_system_v2.rw.core.models import KeepaProductData


@dataclass(frozen=True)
class KeepaStatus:
    tokens_left: int
    refill_rate_per_min: int
    mock_mode: bool

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "tokens_left": self.tokens_left,
            "refill_rate_per_min": self.refill_rate_per_min,
            "mock_mode": self.mock_mode,
        }


class KeepaProvider:
    """Mock-first Keepa adapter.

    Real Keepa network calls are intentionally disabled for this activation.
    The adapter reports mock mode whenever no key is present, and also defaults
    to mock mode when a key exists unless explicit real-mode enablement is added
    in a future key-binding task.
    """

    def __init__(
        self,
        api_key: str | None = None,
        tokens_per_min: int | None = None,
        force_mock: bool = True,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("KEEPA_API_KEY", "")
        self.tokens_per_min = tokens_per_min or int(os.getenv("KEEPA_TOKENS_PER_MIN", "20"))
        self.mock_mode = force_mock or not self.api_key

    def status(self) -> KeepaStatus:
        if self.mock_mode:
            return KeepaStatus(
                tokens_left=self.tokens_per_min,
                refill_rate_per_min=self.tokens_per_min,
                mock_mode=True,
            )
        raise RuntimeError("real Keepa API is disabled; bind keys in a separate activation step")

    def fetch_product(self, asin: str, source_query: str | None = None) -> KeepaProductData:
        if self.mock_mode:
            return self._mock_product(asin=asin, source_query=source_query)
        raise RuntimeError("real Keepa API is disabled; bind keys in a separate activation step")

    def _mock_product(self, asin: str, source_query: str | None = None) -> KeepaProductData:
        query = (source_query or "warehouse product").strip()
        seed = int(hashlib.sha1(f"{asin}:{query}".encode("utf-8")).hexdigest()[:8], 16)

        if query.lower() == "portable door draft stopper":
            return KeepaProductData(
                asin=asin,
                price=34.99,
                bsr=8421,
                reviews=214,
                seller_count=7,
                category="Home & Kitchen",
                title="Portable Door Draft Stopper",
                brand="DraftGuard",
                landed_cost=12.50,
                brand_share=0.32,
                price_trend="stable",
                rating=4.4,
                mock_generated=True,
            )

        price = round(25.0 + (seed % 4_000) / 100, 2)
        landed_cost = round(price * 0.38, 2)
        bsr = 5_000 + seed % 25_000
        reviews = 80 + seed % 650
        seller_count = 4 + seed % 10
        brand_share = round(0.20 + ((seed // 10) % 25) / 100, 2)
        trend = ("stable", "slightly_up", "stable")[seed % 3]

        return KeepaProductData(
            asin=asin,
            price=price,
            bsr=bsr,
            reviews=reviews,
            seller_count=seller_count,
            category="Home & Kitchen",
            title=query.title(),
            brand=f"MockBrand{seed % 97}",
            landed_cost=landed_cost,
            brand_share=brand_share,
            price_trend=trend,
            rating=round(4.0 + (seed % 8) / 10, 1),
            mock_generated=True,
        )

