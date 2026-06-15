from typing import Any


# C14X-B is a static model lock registry only. The default registry is empty
# because C14X-A currently grants no AI execution binding or runtime route.
MODEL_LOCKS_V1: tuple[dict[str, Any], ...] = ()
