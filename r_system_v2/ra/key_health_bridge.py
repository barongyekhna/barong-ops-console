"""R-A worker → key-health 的运行时回报桥。

key-health 的定时探针都是零消耗的：DeepSeek 只看模型列表、1688 只看网关可达，
「余额没了」「套餐额度用完」它们看不见，所以 2026-09-05 那次 DeepSeek 402 和
1688 NoUsageLeft 刷了三天日志，健康页一直绿。这里让业务调用把真实遭遇回报
进 key_health_states：出事就红，同一 provider 随后一次成功再清绿。

设计原则：
- 绝不影响主链。backend 模块导入失败、DB 写失败一律吞掉打日志。
- 进程内节流：同一 (key_type, reason) 一小时最多上报一次，成功清绿也一小时一次。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

REASON_CREDITS_EXHAUSTED = "provider_credits_exhausted"
REASON_QUOTA_EXHAUSTED = "provider_quota_exhausted"

_THROTTLE_SECONDS = 3600.0
_last_reported: dict[tuple[str, str], float] = {}
_lock = threading.Lock()


def _throttled(key: tuple[str, str]) -> bool:
    now = time.monotonic()
    with _lock:
        last = _last_reported.get(key)
        if last is not None and now - last < _THROTTLE_SECONDS:
            return True
        _last_reported[key] = now
    return False


def reset_throttle() -> None:
    with _lock:
        _last_reported.clear()


def _load_service_function(name: str) -> Callable[..., Any] | None:
    for module_path in (
        "backend.app.modules.key_health.service",
        "app.modules.key_health.service",
    ):
        try:
            module = __import__(module_path, fromlist=[name])
        except Exception:
            continue
        function = getattr(module, name, None)
        if callable(function):
            return function
    return None


def report_incident(
    *,
    key_type: str,
    reason_code: str,
    message: str,
    source: str = "r-a-worker",
) -> bool:
    """把一次「供应商级」失败回报到 key-health。返回是否真的写了。"""
    if _throttled((key_type, reason_code)):
        return False
    function = _load_service_function("report_runtime_incident")
    if function is None:
        logger.warning("key-health bridge unavailable; incident dropped key_type=%s", key_type)
        return False
    try:
        function(
            key_type=key_type,
            reason_code=reason_code,
            message=str(message)[:500],
            source=source,
        )
        return True
    except Exception:
        logger.exception("key-health incident report failed key_type=%s", key_type)
        return False


def report_recovered(*, key_type: str, source: str = "r-a-worker") -> bool:
    """同 provider 一次成功调用：清掉运行时事故标记。"""
    if _throttled((key_type, "__recovered__")):
        return False
    function = _load_service_function("report_runtime_recovered")
    if function is None:
        return False
    try:
        function(key_type=key_type, source=source)
        return True
    except Exception:
        logger.exception("key-health recovery report failed key_type=%s", key_type)
        return False
