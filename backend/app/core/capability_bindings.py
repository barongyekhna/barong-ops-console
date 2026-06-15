from typing import Any


# C14X-C is a static capability binding engine only. The default registries are
# empty because C14X-A and C14X-B currently declare no AI execution binding or
# model lock.
CAPABILITY_BINDINGS_V1: tuple[dict[str, Any], ...] = ()
MODULE_CAPABILITY_BINDINGS_V1: tuple[dict[str, Any], ...] = ()
