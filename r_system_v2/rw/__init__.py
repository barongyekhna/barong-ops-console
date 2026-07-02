"""R System v2 Warehouse runtime module.

This package is scoped to R-W only. Production runtime uses the real Keepa
adapter, the persistent category queue, the DeepSeek cron, and the batch writer.
"""

from __future__ import annotations

RW_MODULE_VERSION = "2.1.0-realtime"
