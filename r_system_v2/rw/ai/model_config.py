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
