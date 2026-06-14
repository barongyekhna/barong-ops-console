from typing import Any


# C14D intentionally ships with no built-in service/provider allowlist.
# Dynamic registration data must be supplied by a controlled registry source.
EXTERNAL_SERVICE_REGISTRY_V1: tuple[dict[str, Any], ...] = ()
EXTERNAL_DEPENDENCY_POLICIES_V1: tuple[dict[str, Any], ...] = ()
