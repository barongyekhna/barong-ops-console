from typing import Any


# C14X-A is a routing-path registry only. The default registry intentionally
# grants no AI model binding and does not activate any runtime execution path.
AI_EXECUTION_BINDINGS_V1: tuple[dict[str, Any], ...] = ()
