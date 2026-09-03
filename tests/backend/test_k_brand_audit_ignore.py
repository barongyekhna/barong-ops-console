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
    # 图片指纹必须含 asset_id(2026-08-31)。以前只有 (位号, 类别),
    # 而 K 的出图按位号覆盖——忽略一次之后,同一位号重渲出的**任何**新图
    # 都会继承那次放行,静默通过品牌门。线上 PSPE-002 的第 2、5 张图就卡在这个状态。
    img = bg.brand_finding_fingerprint(
        "image", {"asset_id": "AAA-111", "position": 4, "category": "geometry"})
    assert img == "image::aaa-111::4::geometry"

    # 同位号同类别、但换了一张图 ⇒ 指纹必须不同,否则旧放行会被继承。
    other = bg.brand_finding_fingerprint(
        "image", {"asset_id": "BBB-222", "position": 4, "category": "geometry"})
    assert other != img, "换了图片却拿到同一个指纹——放行会被错误继承"


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


def test_operator_override_beats_every_gate() -> None:
    """死规矩：人工放行高于一切 fail-closed 规则。

    2026-08-11 用户拍板。起因是审查器把花洒手柄上的 "STOP"（一键止水的功能
    标识）判成品牌字样、把 "panda pump"（产品描述）判成商标——它是 AI，不真正
    了解这个产品。运营者看过图做出决定后，这个控制台里不允许任何一道程序再拦他。

    override 打开时无条件放行：不看违规、不看 errors、也不看指纹是否过期。
    """
    from types import SimpleNamespace

    from backend.app.modules.k_series.product_knowledge.brand_guard import (
        audit_gate_blockers,
        operator_override,
    )

    worst_case = {
        "clean": False,
        "fingerprint": "stale-and-wrong",
        "text_violations": [{"surface": "copy", "term": "SomeBrand"}],
        "image_violations": [{"position": 2, "category": "geometry", "finding": "x"}],
        "errors": ["image_audit[3]: boom"],          # errors 本来永不可忽略
        "operator_override": {"enabled": True, "by": "barongyekhna"},
    }
    product = SimpleNamespace(brand_audit_json=worst_case)
    # db 传 None：override 分支必须在任何数据库访问之前就短路返回
    assert audit_gate_blockers(None, product) == []
    assert operator_override(worst_case)

    # 关掉之后照常按结论把关
    off = dict(worst_case)
    off.pop("operator_override")
    assert operator_override(off) == {}
    assert audit_gate_blockers(None, SimpleNamespace(brand_audit_json=None))


def test_override_is_attributable() -> None:
    """放行要留痕：谁、何时、为何。出了事查得到是谁拍的板。"""
    import inspect

    from backend.app.modules.k_series.product_knowledge import brand_guard

    src = inspect.getsource(brand_guard.set_operator_override)
    for field in ('"by"', '"at"', '"reason"'):
        assert field in src, f"override 缺少留痕字段: {field}"
