from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.models.organization import OrganizationRecord
from backend.app.models.provider_config import ProviderConfigRecord
from backend.app.modules.k_series.product_knowledge.constants import (
    TARGET_ORGANIZATION_NAME,
)
from backend.app.services import ai_provider_router as router_module
from backend.app.services.ai_provider_router import (
    AIExecutionRouter,
    AIModelRouter,
    AIProviderExecutionError,
    AnthropicAdapter,
    DeepSeekAdapter,
    OpenAIAdapter,
    ProviderRequest,
    SerperAdapter,
)
from backend.app.services.module_execution_gate import (
    ModuleExecutionContext,
    ModuleExecutionKey,
)

pytestmark = pytest.mark.unit

ORG_ID = "org_11111111111111111111111111111111"
MODULE_ID = "k.product_knowledge"


@pytest.fixture(autouse=True)
def _no_ledger(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """台账与预算闸不碰数据库:预算默认未用完,写台账只记在列表里。"""
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(router_module, "claude_budget_exhausted", lambda: False)
    monkeypatch.setattr(router_module, "record_ai_usage", lambda **kwargs: rows.append(kwargs))
    return rows


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _add_org(db) -> None:
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


def _execution_key(
    *,
    step: str,
    alias: str,
    url: str,
) -> ModuleExecutionKey:
    return ModuleExecutionKey(
        step_name=step,
        key_alias=alias,
        key_id=f"key_{alias}",
        name=alias,
        url=url,
        header_name="Authorization",
        header_value=f"Bearer {alias}",
    )


def _context(keys: dict[str, ModuleExecutionKey]) -> ModuleExecutionContext:
    return ModuleExecutionContext(
        org_id=ORG_ID,
        requested_module_id=MODULE_ID,
        control_module_id=MODULE_ID,
        keys=keys,
    )


def test_model_router_and_adapters_define_required_mapping() -> None:
    assert AIModelRouter.resolve_model(provider="serp", task_type="search") is None
    assert (
        AIModelRouter.resolve_model(provider="deepseek", task_type="generate")
        == "deepseek-flash"
    )
    # 2026-10-21 换血:chatgpt 退出注册表,claude 指向官方 Opus 5.5。
    assert AIModelRouter.resolve_model(provider="chatgpt", task_type="chat") is None
    assert (
        AIModelRouter.resolve_model(provider="claude", task_type="chat")
        == "claude-opus-5-5"
    )

    adapter_cases = [
        (
            SerperAdapter,
            "https://serp.example",
            "search",
            None,
            "https://serp.example/search",
        ),
        (
            OpenAIAdapter,
            "https://4sapi.example",
            "generate",
            "gpt-5.6-luna",
            "https://4sapi.example/v1/chat/completions",
        ),
        (
            AnthropicAdapter,
            "https://api.anthropic.com",
            "chat",
            "claude-opus-5-5",
            "https://api.anthropic.com/v1/messages",
        ),
        (
            DeepSeekAdapter,
            "https://deepseek.example",
            "chat",
            "deepseek-flash",
            "https://deepseek.example/v1/chat/completions",
        ),
    ]
    for adapter_cls, base_url, task_type, model, expected_url in adapter_cases:
        adapter = adapter_cls(
            base_url=base_url,
            api_key="redacted",
            header_name="Authorization",
            key_alias="alias",
        )
        request = adapter.build_request(
            task_type=task_type,
            payload={"messages": [{"role": "user", "content": "hello"}]},
            model=model,
        )
        assert request.url == expected_url
        assert request.body["model"] == model
        if isinstance(adapter, (OpenAIAdapter, AnthropicAdapter)):
            # OpenAI-compatible and Anthropic bodies are cleaned: unknown fields such as
            # task_type are rejected by real providers and must stay out.
            assert "task_type" not in request.body
        else:
            assert request.body["task_type"] == task_type
        assert request.body["messages"] == [{"role": "user", "content": "hello"}]
        if isinstance(adapter, AnthropicAdapter):
            assert request.headers["x-api-key"] == "redacted"
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert "Authorization" not in request.headers


def test_execution_router_syncs_provider_config_and_injects_model(
    monkeypatch: pytest.MonkeyPatch,
    _no_ledger: list[dict[str, Any]],
) -> None:
    db = _session()
    _add_org(db)
    captured: list[ProviderRequest] = []
    events: list[dict[str, Any]] = []

    def fake_post_json(
        *,
        request: ProviderRequest,
        timeout_seconds: float,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        del timeout_seconds, deadline
        captured.append(request)
        return {
            "choices": [
                {"message": {"content": "{\"keywords\":[\"steel pump\"]}"}}
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        }

    monkeypatch.setattr(router_module, "_post_json", fake_post_json)
    monkeypatch.setattr(
        router_module,
        "emit_event",
        lambda **kwargs: events.append(kwargs),
    )

    result = AIExecutionRouter(db, max_attempts=1).execute(
        provider="bulk",
        task_type="generate",
        payload={"messages": [{"role": "user", "content": "filter keywords"}]},
        org=TARGET_ORGANIZATION_NAME,
        execution_context=_context(
            {
                "deepseek": _execution_key(
                    step="deepseek",
                    alias="deepseek",
                    url="https://deepseek.example",
                )
            }
        ),
    )

    assert result == {"keywords": ["steel pump"]}
    assert captured[0].url == "https://deepseek.example/v1/chat/completions"
    assert captured[0].body["model"] == "deepseek-flash"
    assert captured[0].body["thinking"] == {"type": "disabled"}
    # OpenAI-compatible bodies are cleaned; task_type must not leak upstream.
    assert "task_type" not in captured[0].body
    assert captured[0].headers["Authorization"] == "Bearer deepseek"
    provider_config = db.scalar(
        select(ProviderConfigRecord).where(
            ProviderConfigRecord.org_id == ORG_ID,
            ProviderConfigRecord.module_id == MODULE_ID,
            ProviderConfigRecord.provider == "deepseek",
        )
    )
    assert provider_config is not None
    assert provider_config.base_url == "https://deepseek.example"
    assert provider_config.source_key_id == "key_deepseek"
    assert events[0]["payload"]["provider_used"] == "deepseek"
    assert events[0]["payload"]["endpoint_called"] == "/v1/chat/completions"
    assert events[0]["payload"]["api_key_alias"] == "deepseek"
    assert events[0]["payload"]["success"] is True
    assert _no_ledger[0]["provider"] == "deepseek"
    assert _no_ledger[0]["usage"].input_tokens == 120
    assert _no_ledger[0]["usage"].output_tokens == 30


def test_execution_router_rejects_retired_chatgpt_text_calls() -> None:
    db = _session()
    _add_org(db)
    with pytest.raises(AIProviderExecutionError) as excinfo:
        AIExecutionRouter(db, max_attempts=1).execute(
            provider="chatgpt",
            task_type="generate",
            payload={"messages": [{"role": "user", "content": "x"}]},
            org=TARGET_ORGANIZATION_NAME,
            execution_context=_context(
                {"chatgpt": _execution_key(step="chatgpt", alias="chatgpt", url="https://4sapi.example")}
            ),
        )
    assert excinfo.value.code == "AI_PROVIDER_RETIRED"


def test_execution_router_has_no_default_cross_provider_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _session()
    _add_org(db)
    captured: list[ProviderRequest] = []

    def fake_post_json(
        *,
        request: ProviderRequest,
        timeout_seconds: float,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        del timeout_seconds, deadline
        captured.append(request)
        raise ValueError("temporary_provider_failure")

    monkeypatch.setattr(router_module, "_post_json", fake_post_json)
    monkeypatch.setattr(router_module, "emit_event", lambda **_kwargs: None)

    with pytest.raises(AIProviderExecutionError) as excinfo:
        AIExecutionRouter(db, max_attempts=1).execute(
            provider="claude",
            task_type="chat",
            payload={"messages": [{"role": "user", "content": "review"}]},
            org=TARGET_ORGANIZATION_NAME,
            execution_context=_context(
                {
                    "anthropic": _execution_key(
                        step="anthropic",
                        alias="anthropic",
                        url="https://api.anthropic.com",
                    ),
                    "deepseek": _execution_key(
                        step="deepseek",
                        alias="deepseek",
                        url="https://deepseek.example",
                    ),
                }
            ),
        )

    assert excinfo.value.code == "AI_PROVIDER_REQUEST_FAILED"
    # 换血前这里会悄悄转去 chatgpt;现在失败就是失败,只打了一次 Claude 官方口。
    assert len(captured) == 1
    assert captured[0].url == "https://api.anthropic.com/v1/messages"
    assert captured[0].body["model"] == "claude-opus-5-5"


def test_k_business_modules_do_not_directly_post_http() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    for relative_path in (
        "backend/app/modules/k_series/product_knowledge/router.py",
        "backend/app/modules/k_series/product_knowledge/workflow_engine.py",
    ):
        source = (repo_root / relative_path).read_text(encoding="utf-8")
        for forbidden in (
            "urlopen",
            "UrlRequest",
            "urllib.request",
            "urllib.error",
            "_post_provider_json",
            "post_provider_json",
        ):
            assert forbidden not in source
