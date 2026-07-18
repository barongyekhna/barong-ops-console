"""Manual K creation SKU iron rule: category required, SKU always allocator-issued."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_create_route_rejects_missing_category() -> None:
    """The manual-create route must 422 without a category selection."""
    import inspect

    from backend.app.modules.k_series.product_knowledge import router

    source = inspect.getsource(router.product_knowledge_create)
    assert "CATEGORY_REQUIRED_FOR_SKU" in source
    # The guard must run before idempotency claiming so invalid requests
    # never reserve a create slot.
    assert source.index("CATEGORY_REQUIRED_FOR_SKU") < source.index(
        "_product_create_fingerprint"
    )


def test_create_service_ignores_client_sku_and_allocates() -> None:
    """create_product must issue the SKU via the allocator, ignoring payload SKUs."""
    import inspect

    from backend.app.modules.k_series.product_knowledge import service

    source = inspect.getsource(service.create_product)
    assert "ensure_product_sku" in source
    assert "force_allocate=True" in source
    # No path may copy a payload-provided sku onto the product.
    assert "payload.sku" not in source
    assert "payload.parent_sku" not in source


def test_allocator_prefix_matches_leaf_rule() -> None:
    """SKU prefix derives from the leaf category name (叶子类目简写)."""
    from backend.app.modules.k_series.product_knowledge.sku_allocator import (
        derive_category_prefix,
    )

    assert derive_category_prefix("In-Ground Lights") == "IGL"
    assert derive_category_prefix("Camping Cookware & Dinnerware") == "CCD"
