"""Deterministic cleanup for buyer-visible product naming fields."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


# Supplier titles frequently prefix a private model code such as ``DS-101`` or
# ``DS308``.  Keep this deliberately narrower than a general alphanumeric
# cleaner: digit-led specifications (7-Piece, 1.5L, 2-3) are product facts and
# must survive unchanged.
# Use explicit ASCII boundaries so a code touching CJK text is still isolated;
# Python's Unicode ``\b`` treats both CJK and Latin letters as word characters.
# A small allowlist protects model-shaped buyer specifications from removal.
_ISOLATED_SUPPLIER_MODEL_CODE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?!(?:(?:IP|UPF)\d{2,3}|UV\d{3}|(?:AC|DC)\d{2,3})(?![A-Za-z0-9]))"
    r"[A-Z]{2,}[- ]?\d{2,}"
    r"(?![A-Za-z0-9])"
)
_EMPTY_PUNCTUATION_GROUP = re.compile(r"\(\s*\)|\[\s*\]|\{\s*\}")
_ADJACENT_LIST_SEPARATOR = re.compile(
    r"\s*([,;:/|\u00b7])(?:\s*[,;:/|\u00b7])+\s*"
)
_ADJACENT_DASH_SEPARATOR = re.compile(
    r"\s*([-\u2013\u2014])(?:\s*[-\u2013\u2014])+\s*"
)


def strip_supplier_model_codes(value: str) -> str:
    """Remove isolated supplier model codes without touching numeric specs.

    Punctuation normalization only runs when a model code was actually
    removed, keeping already-clean names byte-for-byte stable apart from outer
    whitespace.
    """

    original = value.strip()
    cleaned, removed = _ISOLATED_SUPPLIER_MODEL_CODE.subn("", original)
    if not removed:
        return original

    cleaned = _EMPTY_PUNCTUATION_GROUP.sub(" ", cleaned)
    cleaned = _ADJACENT_LIST_SEPARATOR.sub(r"\1 ", cleaned)
    cleaned = _ADJACENT_DASH_SEPARATOR.sub(r" \1 ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,;:.!?])", r"\1", cleaned)
    return cleaned.strip(" \t\r\n,;:/|\u00b7-\u2013\u2014()[]{}")


def sanitize_product_naming_output(
    provider_output: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a copy with only the generated buyer-visible name sanitized."""

    sanitized = dict(provider_output)
    generated_name = sanitized.get("product_name_en")
    if isinstance(generated_name, str):
        sanitized["product_name_en"] = strip_supplier_model_codes(generated_name)
    return sanitized
