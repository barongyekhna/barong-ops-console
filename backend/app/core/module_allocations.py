from typing import Any


# C14X-D is a static module allocation registry only. The default registry is
# empty because C14X-A/B/C currently declare no active AI execution route.
MODULE_ALLOCATIONS_V1: tuple[dict[str, Any], ...] = ()
