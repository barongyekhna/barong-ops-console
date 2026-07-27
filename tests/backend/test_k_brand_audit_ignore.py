"""品牌审查:通用词白名单(USB-C 不再误判)+ 忽略/人工放行机制。"""
from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_generic_terms_are_not_brands() -> None:
    from backend.app.modules.k_series.product_knowledge import brand_guard as bg

    for term in ["USB-C", "usb c", "USB", "Type-C", "IPX8", "IP67", "LED",
                 "Bluetooth", "Li-ion", "mAh", "  usb-c  "]:
        assert bg._is_generic_non_brand(term) is True, term
    # 真品牌 / 站牌
    for term in ["Ivation", "NEMO", "Kakadu", "Gruper"]:
        assert bg._is_generic_non_brand(term) is False, term
    for term in ["Barong Yekhna", "barong"]:
        assert bg._is_generic_non_brand(term) is True, term


def test_ai_text_violations_filters_generic() -> None:
    from backend.app.modules.k_series.product_knowledge import brand_guard as bg

    src = inspect.getsource(bg.ai_text_violations)
    assert "_is_generic_non_brand(term)" in src


def test_text_audit_instruction_excludes_connectors() -> None:
    from backend.app.modules.k_series.product_knowledge import brand_guard as bg

    instr = bg._TEXT_AUDIT_INSTRUCTION
    assert "USB-C" in instr and "not brands" in instr.lower()


def test_finding_fingerprint_stable() -> None:
    from backend.app.modules.k_series.product_knowledge import brand_guard as bg

    a = bg.brand_finding_fingerprint(
        "text", {"surface": "[copy.k[1]]", "term": "USB-C"})
    b = bg.brand_finding_fingerprint(
        "text", {"surface": "[copy.k[1]]", "term": "usb-c"})
    assert a == b == "text::[copy.k[1]]::usb-c"
    img = bg.brand_finding_fingerprint(
        "image", {"position": 4, "category": "geometry"})
    assert img == "image::4::geometry"


def test_run_brand_audit_carries_and_applies_ignores() -> None:
    from backend.app.modules.k_series.product_knowledge import brand_guard as bg

    src = inspect.getsource(bg.run_brand_audit)
    # 结转上一轮忽略清单
    assert "ignored_findings" in src
    assert "prev_audit" in src
    # clean 基于"排除忽略后仍未解决"的发现,而不是全部
    assert "unresolved" in src
    assert '"clean": not unresolved and not errors' in src


def test_gate_blockers_respect_ignores() -> None:
    from backend.app.modules.k_series.product_knowledge import brand_guard as bg

    src = inspect.getsource(bg.audit_gate_blockers)
    assert "ignored_findings" in src
    assert "brand_finding_fingerprint" in src
    # errors 永不可忽略
    assert 'errors = audit.get("errors")' in src


def test_set_ignored_recomputes_clean() -> None:
    from backend.app.modules.k_series.product_knowledge import brand_guard as bg

    src = inspect.getsource(bg.set_brand_finding_ignored)
    assert 'audit["clean"] = not unresolved' in src
    assert "ignore_set.add(fingerprint)" in src
    assert "ignore_set.discard(fingerprint)" in src


def test_ignore_endpoint_wired() -> None:
    from backend.app.modules.k_series.product_knowledge import router

    src = inspect.getsource(router)
    assert "/brand-audit/ignore" in src
    assert "set_brand_finding_ignored" in src
    assert "brand_finding_fingerprint" in src
