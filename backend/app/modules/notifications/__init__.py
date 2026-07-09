"""Console notification inbox + P notification agent.

The P-series upload pipeline (and other modules / n8n callbacks) emit events
here; they land as queryable, append-only ``p_notifications`` rows that the
console inbox surfaces. Real 数字人 / WeCom push is deferred -- this is the
persistence + inbox layer the plan calls for.
"""
