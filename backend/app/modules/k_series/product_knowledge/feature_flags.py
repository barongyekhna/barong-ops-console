"""Disabled-by-default feature flag for the dormant K module.

This module deliberately does not read production/staging env files and does
not depend on core config. The hard-coded ``False`` is the current safety
default. Future C13 module-switch integration should replace this local
implementation after owner approval.
"""


def is_k_product_knowledge_enabled() -> bool:
    return False
