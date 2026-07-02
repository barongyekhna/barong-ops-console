"""Feature extraction for normalized Warehouse products."""

from __future__ import annotations

from r_system_v2.rw.core.models import KeepaProductData, NormalizedProduct, ProductState


def _category_id(category: str) -> str:
    normalized = category.strip().lower().replace("&", "and")
    return "-".join(part for part in normalized.replace(",", " ").split() if part)


def extract_product_features(source_query: str, keepa_data: KeepaProductData) -> NormalizedProduct:
    """Convert Keepa provider output into the normalized product schema.

    The mock layer stores derived features only, not raw Keepa payloads. Fee and
    unit estimates are intentionally conservative placeholders for mock tests.
    """

    estimated_fees = keepa_data.price * 0.15
    est_net_margin = round(
        (keepa_data.price - keepa_data.landed_cost - estimated_fees) / keepa_data.price,
        4,
    )
    demand_bucket = "high" if keepa_data.bsr <= 10_000 else "medium" if keepa_data.bsr <= 50_000 else "low"

    return NormalizedProduct(
        asin=keepa_data.asin,
        source_query=source_query,
        marketplace=keepa_data.marketplace,
        title=keepa_data.title,
        brand=keepa_data.brand,
        category=keepa_data.category,
        price=keepa_data.price,
        bsr=keepa_data.bsr,
        reviews=keepa_data.reviews,
        seller_count=keepa_data.seller_count,
        landed_cost=keepa_data.landed_cost,
        est_net_margin=est_net_margin,
        brand_share=keepa_data.brand_share,
        price_trend=keepa_data.price_trend,
        rating=keepa_data.rating,
        image_url=keepa_data.image_url,
        category_id=_category_id(keepa_data.category),
        category_path=[keepa_data.category],
        state=ProductState.ENRICHED,
        features={
            "demand_bucket": demand_bucket,
            "estimated_fees": round(estimated_fees, 2),
            "feature_source": "keepa_v1",
        },
    )
