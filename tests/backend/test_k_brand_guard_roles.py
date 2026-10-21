"""品牌硬门换血(2026-10-21):四道 AI 审查按 ai_roles 分档,不再直连 4sapi 的 GPT。

文本审 → bulk(DeepSeek);识图/型态分类 → fast(Haiku);几何/物理把关 → judge(Opus)。
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from backend.app.modules.k_series.product_knowledge import brand_guard
from backend.app.services.ai_roles import ROLE_BULK, ROLE_FAST, ROLE_JUDGE

pytestmark = pytest.mark.unit

KEYS = brand_guard.AuditKeys(
    org_id="org_test",
    anthropic_key="sk-ant-test",
    deepseek_key="Bearer ds-test",
    deepseek_url="https://api.deepseek.com",
)


@pytest.fixture
def calls(monkeypatch):
    seen: list[dict] = []

    def fake_complete(role, **kwargs):
        seen.append({"role": role, **kwargs})
        return SimpleNamespace(
            text='{"violations": [], "flagged": false, "findings": []}',
            degraded=False,
            model="stub",
        )

    monkeypatch.setattr(brand_guard, "complete", fake_complete)
    return seen


def test_text_audit_uses_bulk_role(calls) -> None:
    assert brand_guard.ai_text_violations(KEYS, [("title", "Yoga mat")]) == []
    assert calls[0]["role"] == ROLE_BULK
    assert calls[0]["deepseek_key"] == "Bearer ds-test"
    assert calls[0]["json_only"] is True
    assert calls[0]["org_ref"] == "org_test"


def test_image_audit_uses_fast_role_and_sends_image_block(calls) -> None:
    assert brand_guard.ai_image_violation(KEYS, b"png-bytes", "image/png") == []
    assert calls[0]["role"] == ROLE_FAST
    content = calls[0]["messages"][0]["content"]
    assert any(block.get("type") == "image_url" for block in content)


def test_geometry_and_physics_use_judge_role(calls) -> None:
    brand_guard.ai_geometry_violation(KEYS, b"ref", "image/png", b"ren", "image/png")
    brand_guard.ai_physics_violation(
        KEYS,
        operating_model={"hard_constraints": ["pump must be submerged"]},
        rendered_bytes=b"ren",
        rendered_mime="image/png",
    )
    assert [call["role"] for call in calls] == [ROLE_JUDGE, ROLE_JUDGE]


def test_operating_model_uses_judge_role(calls) -> None:
    brand_guard.ai_operating_model(KEYS, product_facts={}, references=[(b"ref", "image/png")])
    assert calls[0]["role"] == ROLE_JUDGE


def test_legacy_key_object_is_rejected_not_silently_used(calls) -> None:
    legacy = SimpleNamespace(url="https://4sapi.com", header_name="Authorization", header_value="Bearer x")
    with pytest.raises(TypeError):
        brand_guard.ai_text_violations(legacy, [("title", "Yoga mat")])
    assert calls == []


def test_no_4sapi_or_gpt_left_in_brand_guard() -> None:
    src = inspect.getsource(brand_guard)
    for marker in ("gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.2-high", "/chat/completions", "import httpx", "httpx.Client"):
        assert marker not in src
