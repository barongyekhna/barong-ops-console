"""AI 换血(2026-10-21):角色分层、Claude 官方协议、看图不压扁、无暗门、额度降级、台账。"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.models.organization import OrganizationRecord
from backend.app.modules.k_series.product_knowledge.constants import (
    TARGET_ORGANIZATION_NAME,
)
from backend.app.services import ai_provider_router as router_module
from backend.app.services import ai_roles
from backend.app.services.ai_provider_router import (
    AIExecutionRouter,
    AIProviderExecutionError,
    AnthropicAdapter,
    ProviderRequest,
    _messages_from_payload,
)
from backend.app.services.ai_usage_ledger import (
    AIUsage,
    estimate_cost_usd,
    usage_from_response,
)
from backend.app.services.module_execution_gate import (
    ModuleExecutionContext,
    ModuleExecutionKey,
)

pytestmark = pytest.mark.unit

ORG_ID = "org_11111111111111111111111111111111"
MODULE_ID = "k.product_knowledge"
PNG_DATA_URL = "data:image/png;base64,iVBORw0KGgo="


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(
        OrganizationRecord(
            org_id=ORG_ID,
            org_name=TARGET_ORGANIZATION_NAME,
            org_type="store",
            owner_user_id="1",
            status="active",
            metadata_json={},
        )
    )
    db.commit()
    return db


def _key(alias: str, url: str, *, header_name: str = "Authorization", header_value: str | None = None) -> ModuleExecutionKey:
    return ModuleExecutionKey(
        step_name=alias,
        key_alias=alias,
        key_id=f"key_{alias}",
        name=alias,
        url=url,
        header_name=header_name,
        header_value=header_value if header_value is not None else f"Bearer {alias}-secret",
    )


ANTHROPIC_KEY = _key("anthropic", "https://api.anthropic.com", header_name="x-api-key", header_value="sk-ant-secret")
DEEPSEEK_KEY = _key("deepseek", "https://api.deepseek.com")


def _context(*keys: ModuleExecutionKey) -> ModuleExecutionContext:
    return ModuleExecutionContext(
        org_id=ORG_ID,
        requested_module_id=MODULE_ID,
        control_module_id=MODULE_ID,
        keys={key.step_name: key for key in keys},
    )


ANTHROPIC_OK = {
    "content": [
        {"type": "thinking", "thinking": ""},
        {"type": "text", "text": '{"verdict":"pass"}'},
    ],
    "stop_reason": "end_turn",
    "usage": {
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_input_tokens": 50,
        "cache_creation_input_tokens": 10,
    },
}
DEEPSEEK_OK = {
    "choices": [{"message": {"content": '{"verdict":"pass"}'}}],
    "usage": {"prompt_tokens": 300, "completion_tokens": 40, "prompt_cache_hit_tokens": 100},
}


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "requests": [],
        "ledger": [],
        "events": [],
        "budget_exhausted": False,
        "responses": [],
        "gate_calls": [],
    }

    def fake_post_json(*, request: ProviderRequest, timeout_seconds: float, deadline: float | None = None) -> dict[str, Any]:
        del timeout_seconds, deadline
        state["requests"].append(request)
        response = state["responses"].pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(router_module, "_post_json", fake_post_json)
    monkeypatch.setattr(router_module, "emit_event", lambda **kwargs: state["events"].append(kwargs))
    monkeypatch.setattr(router_module, "claude_budget_exhausted", lambda: state["budget_exhausted"])
    monkeypatch.setattr(router_module, "record_ai_usage", lambda **kwargs: state["ledger"].append(kwargs))
    monkeypatch.setattr(ai_roles, "claude_budget_exhausted", lambda: state["budget_exhausted"])
    monkeypatch.setattr(ai_roles, "record_ai_usage", lambda **kwargs: state["ledger"].append(kwargs))

    def fake_gate(db, **kwargs):
        del db
        state["gate_calls"].append(kwargs)
        return _context(DEEPSEEK_KEY)

    monkeypatch.setattr(router_module, "require_module_execution_ready", fake_gate)
    return state


def _vision_payload() -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": "You are an image gate."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What colour is this?"},
                    {"type": "image_url", "image_url": {"url": PNG_DATA_URL}},
                ],
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 300,
    }


# (a) 看图不再被压扁 ------------------------------------------------------------


def test_image_blocks_survive_messages_from_payload() -> None:
    messages = _messages_from_payload(_vision_payload())
    content = messages[1]["content"]
    assert isinstance(content, list)
    assert content[1] == {"type": "image_url", "image_url": {"url": PNG_DATA_URL}}


def test_anthropic_adapter_converts_data_url_into_base64_image_block() -> None:
    adapter = AnthropicAdapter(base_url="https://api.anthropic.com", api_key="sk-ant-secret", header_name="x-api-key", key_alias="anthropic")
    adapter.effort = "medium"
    request = adapter.build_request(task_type="chat", payload=_vision_payload(), model="claude-opus-5-5")
    user = request.body["messages"][0]
    assert user["role"] == "user"
    assert user["content"][0] == {"type": "text", "text": "What colour is this?"}
    assert user["content"][1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="},
    }


# (b) Anthropic 协议 ------------------------------------------------------------


def test_anthropic_request_headers_system_effort_and_floor() -> None:
    adapter = AnthropicAdapter(base_url="https://api.anthropic.com", api_key="Bearer sk-ant-secret", header_name="x-api-key", key_alias="anthropic")
    adapter.effort = "low"
    request = adapter.build_request(task_type="chat", payload=_vision_payload(), model="claude-haiku-5-5")
    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-ant-secret"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in request.headers
    body = request.body
    assert body["system"].startswith("You are an image gate.")
    assert "JSON" in body["system"]
    assert all(message["role"] != "system" for message in body["messages"])
    # 调用方给的 300 会被思考吃光,抬到下限。
    assert body["max_tokens"] >= 8000
    assert body["output_config"] == {"effort": "low"}
    for dropped in ("temperature", "response_format", "task_type", "thinking"):
        assert dropped not in body


def test_opus_requests_refusal_fallback_and_haiku_does_not() -> None:
    adapter = AnthropicAdapter(base_url="https://api.anthropic.com", api_key="k", header_name="x-api-key", key_alias="anthropic")
    opus = adapter.build_request(task_type="chat", payload={"prompt": "hi"}, model="claude-opus-5-5")
    haiku = adapter.build_request(task_type="chat", payload={"prompt": "hi"}, model="claude-haiku-5-5")
    assert opus.body.get("fallbacks") == "default"
    assert opus.headers.get("anthropic-beta") == "server-side-fallback-2026-07-01"
    assert "fallbacks" not in haiku.body
    assert "anthropic-beta" not in haiku.headers


# (c) 无暗门 --------------------------------------------------------------------


def test_failing_deepseek_never_calls_another_provider(harness: dict[str, Any]) -> None:
    harness["responses"] = [ValueError("boom")]
    with pytest.raises(AIProviderExecutionError):
        AIExecutionRouter(_session(), max_attempts=1).execute(
            provider="bulk",
            task_type="chat",
            payload={"prompt": "x"},
            org=TARGET_ORGANIZATION_NAME,
            execution_context=_context(DEEPSEEK_KEY, ANTHROPIC_KEY),
        )
    assert [request.url for request in harness["requests"]] == ["https://api.deepseek.com/v1/chat/completions"]
    assert harness["ledger"][-1]["success"] is False


def test_claude_role_with_only_deepseek_key_is_missing_not_silently_rerouted(harness: dict[str, Any]) -> None:
    with pytest.raises(AIProviderExecutionError) as excinfo:
        AIExecutionRouter(_session(), max_attempts=1).execute(
            provider="judge",
            task_type="chat",
            payload={"prompt": "x"},
            org=TARGET_ORGANIZATION_NAME,
            execution_context=_context(DEEPSEEK_KEY),
        )
    assert excinfo.value.code == "AI_PROVIDER_KEY_MISSING"
    assert harness["requests"] == []


# (d) 额度降级 ------------------------------------------------------------------


def test_budget_exhausted_judge_runs_on_deepseek_and_is_marked(harness: dict[str, Any]) -> None:
    harness["budget_exhausted"] = True
    harness["responses"] = [DEEPSEEK_OK]
    result = AIExecutionRouter(_session(), max_attempts=1).execute(
        provider="judge",
        task_type="chat",
        payload={"prompt": "x"},
        org=TARGET_ORGANIZATION_NAME,
        execution_context=_context(DEEPSEEK_KEY, ANTHROPIC_KEY),
    )
    assert result["_ai_degraded"] is True
    assert result["verdict"] == "pass"
    request = harness["requests"][0]
    assert request.url == "https://api.deepseek.com/v1/chat/completions"
    assert request.body["model"] == "deepseek-flash"
    assert request.body["thinking"] == {"type": "disabled"}
    assert request.headers["Authorization"] == "Bearer deepseek-secret"
    assert any(event["event_type"] == "ai_provider.degraded" for event in harness["events"])
    assert harness["ledger"][0]["degraded"] is True
    assert harness["ledger"][0]["provider"] == "deepseek"
    assert harness["gate_calls"] == []


def test_degraded_with_anthropic_only_context_fetches_fresh_deepseek_key(harness: dict[str, Any]) -> None:
    harness["budget_exhausted"] = True
    harness["responses"] = [DEEPSEEK_OK]
    result = AIExecutionRouter(_session(), max_attempts=1).execute(
        provider="judge",
        task_type="chat",
        payload={"prompt": "x"},
        org=TARGET_ORGANIZATION_NAME,
        execution_context=_context(ANTHROPIC_KEY),
    )
    assert result["_ai_degraded"] is True
    assert len(harness["gate_calls"]) == 1
    assert harness["gate_calls"][0]["key_requirements"] == {"deepseek": "deepseek"}
    request = harness["requests"][0]
    assert request.url.startswith("https://api.deepseek.com")
    # Claude 钥匙绝不能被发去 DeepSeek。
    assert "sk-ant-secret" not in str(request.headers)
    assert request.headers["Authorization"] == "Bearer deepseek-secret"


# (e) 台账 ----------------------------------------------------------------------


def test_router_ledger_records_anthropic_usage(harness: dict[str, Any]) -> None:
    harness["responses"] = [ANTHROPIC_OK]
    result = AIExecutionRouter(_session(), max_attempts=1).execute(
        provider="fast",
        task_type="chat",
        payload={"prompt": "x"},
        org=TARGET_ORGANIZATION_NAME,
        execution_context=_context(ANTHROPIC_KEY, DEEPSEEK_KEY),
    )
    assert result == {"verdict": "pass"}
    assert "_ai_degraded" not in result
    row = harness["ledger"][0]
    assert row["provider"] == "claude"
    assert row["model"] == "claude-haiku-5-5"
    assert row["module"] == MODULE_ID
    assert row["degraded"] is False
    assert row["usage"] == AIUsage(input_tokens=1000, output_tokens=200, cache_read_tokens=50, cache_write_tokens=10)
    request = harness["requests"][0]
    assert request.body["output_config"] == {"effort": "low"}


def test_usage_parsing_and_cost_math() -> None:
    anthropic_usage = usage_from_response(ANTHROPIC_OK)
    assert anthropic_usage == AIUsage(1000, 200, 50, 10)
    deepseek_usage = usage_from_response(DEEPSEEK_OK)
    assert deepseek_usage == AIUsage(input_tokens=200, output_tokens=40, cache_read_tokens=100)
    assert usage_from_response({}) == AIUsage()

    # Opus 5.5: 1000×4 + 200×20 + 50×0.20 + 10×5.00 = 8060 → $0.00806
    assert estimate_cost_usd("claude-opus-5-5", anthropic_usage) == pytest.approx(0.00806)
    # Haiku 5.5: 1000×0.10 + 200×0.50 + 50×0.01 + 10×0.125 = 201.75 → $0.00020175
    assert estimate_cost_usd("claude-haiku-5-5", anthropic_usage) == pytest.approx(0.00020175)
    # deepseek-flash: 200×0.30 + 40×1.20 + 100×0.03 = 111 → $0.000111
    assert estimate_cost_usd("deepseek-flash", deepseek_usage) == pytest.approx(0.000111)
    assert estimate_cost_usd("unknown-model", deepseek_usage) is None


def test_price_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PRICE_CLAUDE_HAIKU_5_5", "1,2")
    assert estimate_cost_usd("claude-haiku-5-5", AIUsage(input_tokens=1_000_000, output_tokens=1_000_000)) == pytest.approx(3.0)


# (f) 拒答 ----------------------------------------------------------------------


def test_refusal_stop_reason_becomes_provider_refusal(harness: dict[str, Any]) -> None:
    harness["responses"] = [
        {"content": [], "stop_reason": "refusal", "stop_details": {"type": "refusal", "category": "cyber"}, "usage": {"input_tokens": 5, "output_tokens": 0}}
    ]
    with pytest.raises(AIProviderExecutionError) as excinfo:
        AIExecutionRouter(_session(), max_attempts=1).execute(
            provider="judge",
            task_type="chat",
            payload={"prompt": "x"},
            org=TARGET_ORGANIZATION_NAME,
            execution_context=_context(ANTHROPIC_KEY),
        )
    assert excinfo.value.code == "AI_PROVIDER_REFUSAL"
    assert excinfo.value.details["category"] == "cyber"
    assert len(harness["requests"]) == 1


# (g) 4sapi 钥匙不能被拿去打 Claude ----------------------------------------------


def test_anthropic_adapter_refuses_relay_url(harness: dict[str, Any]) -> None:
    relay = _key("anthropic", "https://4sapi.com")
    with pytest.raises(AIProviderExecutionError) as excinfo:
        AIExecutionRouter(_session(), max_attempts=1).execute(
            provider="judge",
            task_type="chat",
            payload={"prompt": "x"},
            org=TARGET_ORGANIZATION_NAME,
            execution_context=_context(relay),
        )
    assert excinfo.value.code == "AI_PROVIDER_MISCONFIGURED"
    assert harness["requests"] == []


# (h) 直连调用方的 complete() 与环境变量覆盖 ------------------------------------


def test_complete_degrades_to_deepseek_when_budget_exhausted(harness: dict[str, Any]) -> None:
    harness["budget_exhausted"] = True
    harness["responses"] = [DEEPSEEK_OK]
    result = ai_roles.complete(
        "judge",
        messages=[{"role": "user", "content": "x"}],
        module="r.analysis",
        task="opus_layer",
        anthropic_key="sk-ant-secret",
        deepseek_key="Bearer ds-secret",
        json_only=True,
    )
    assert result.degraded is True
    assert result.provider == "deepseek"
    assert result.model == "deepseek-flash"
    request = harness["requests"][0]
    assert request.url == "https://api.deepseek.com/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer ds-secret"
    assert request.body["thinking"] == {"type": "disabled"}
    assert request.body["response_format"] == {"type": "json_object"}
    assert harness["ledger"][0]["degraded"] is True
    assert ai_roles.parse_json_object(result.text) == {"verdict": "pass"}


def test_complete_claude_path_records_usage(harness: dict[str, Any]) -> None:
    harness["responses"] = [ANTHROPIC_OK]
    result = ai_roles.complete(
        "fast",
        messages=[{"role": "user", "content": "x"}],
        module="k.product_knowledge",
        task="brand_logo",
        anthropic_key="sk-ant-secret",
        deepseek_key=None,
    )
    assert result.provider == "claude"
    assert result.model == "claude-haiku-5-5"
    assert result.degraded is False
    assert result.text == '{"verdict":"pass"}'
    request = harness["requests"][0]
    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-ant-secret"
    assert harness["ledger"][0]["usage"].output_tokens == 200


def test_complete_failure_is_recorded_and_raised(harness: dict[str, Any]) -> None:
    harness["responses"] = [ValueError("boom")]
    with pytest.raises(ai_roles.DirectCompletionError):
        ai_roles.complete(
            "bulk",
            messages=[{"role": "user", "content": "x"}],
            module="r.analysis",
            task="prescreen",
            anthropic_key=None,
            deepseek_key="ds",
        )
    assert harness["ledger"][0]["success"] is False
    assert len(harness["requests"]) == 1


def test_role_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_ROLE_WRITER_PROVIDER", "deepseek")
    monkeypatch.setenv("AI_ROLE_WRITER_MODEL", "deepseek-flash")
    target = ai_roles.resolve_role("writer")
    assert (target.provider, target.model, target.effort) == ("deepseek", "deepseek-flash", None)
    monkeypatch.delenv("AI_ROLE_WRITER_PROVIDER")
    monkeypatch.setenv("AI_ROLE_WRITER_MODEL", "claude-sonnet-5-5")
    target = ai_roles.resolve_role("writer")
    assert (target.provider, target.model, target.effort) == ("claude", "claude-sonnet-5-5", "medium")
    with pytest.raises(ValueError):
        ai_roles.resolve_role("chatgpt")
