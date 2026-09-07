"""DeepSeek model configuration for R-W."""

from __future__ import annotations

import os


DEFAULT_RW_DEEPSEEK_MODEL = "deepseek-v4-pro"


def rw_deepseek_model() -> str:
    return (
        os.getenv("RW_DEEPSEEK_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or DEFAULT_RW_DEEPSEEK_MODEL
    )


def deepseek_thinking_extras(model: str | None = None) -> dict[str, object]:
    """DeepSeek V4 系列默认开「思考」：2026-09-07 实测一次 R-A 抽词吐 9375 个推理
    token、69 秒；关掉后 203 个 token、1.5 秒——同一份 JSON。选品链路全是结构化
    抽取，不需要它想；不关等于每次调用贵 40 倍、慢 40 倍（这就是余额两天充两次
    还是 402 的根子）。DEEPSEEK_THINKING=enabled 可整体打开。"""
    del model  # 目前官方口 v4 全系接受该参数；保留形参给将来按模型区分。
    if os.getenv("DEEPSEEK_THINKING", "").strip().lower() in {"1", "true", "enabled", "on"}:
        return {}
    return {"thinking": {"type": "disabled"}}
