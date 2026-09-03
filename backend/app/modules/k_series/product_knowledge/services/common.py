"""K 接口层的跨域小工具。

从 router 剥出来的第 2 桶（2026-09-03）。这几个不属于任何一个业务域 ——
卖点、图片、规格、关键词都在用。放进任何一个域模块都会造出错误的依赖方向
（图片模块去 import 卖点模块只为了拿一个 hash 函数）。

**行为一字未改**，原样搬运。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _strict_json_messages(
    *,
    instruction: str,
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True),
        },
    ]


def _source_text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_payload_digest(value: Any) -> str:
    return _source_text_hash(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    )


def _product_ai_warnings(product: KProductKnowledgeProduct) -> dict[str, Any]:
    return (
        dict(product.ai_warnings_json)
        if isinstance(product.ai_warnings_json, dict)
        else {}
    )
