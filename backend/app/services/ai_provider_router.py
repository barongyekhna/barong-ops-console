from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.organization import OrganizationRecord
from ..models.user import User
from .event_collector import emit_event
from .module_execution_gate import (
    ModuleExecutionContext,
    ModuleExecutionGateError,
    ModuleExecutionKey,
    require_module_execution_ready,
)
from .provider_config_service import (
    ProviderConfigError,
    get_provider_config,
    normalize_provider,
    provider_key_alias,
    provider_registry_mapping,
    upsert_provider_config,
)

AIProvider = Literal["serp", "chatgpt", "claude", "deepseek"]
AITaskType = Literal["search", "chat", "generate", "selling_points"]

MODEL_REGISTRY: dict[str, dict[str, str | None]] = {
    "serp": {
        "default": None,
        "search": None,
    },
    "deepseek": {
        "default": "deepseek-v4-pro",
        "chat": "deepseek-v4-pro",
        "generate": "deepseek-v4-pro",
        "selling_points": "deepseek-v4-pro",
    },
    "chatgpt": {
        "default": "gpt-5.6-luna",
        "chat": "gpt-5.6-luna",
        "generate": "gpt-5.6-luna",
    },
    "claude": {
        "default": "claude-opus-4-8-thinking",
        "chat": "claude-opus-4-8-thinking",
        "generate": "claude-opus-4-8-thinking",
    },
}

DEFAULT_FALLBACK_PROVIDERS = {
    "deepseek": "chatgpt",
    "claude": "chatgpt",
    # 2026-07-22 用户拍板:GPT 全系(含降级序列)都打不通时,试 Opus 4.8。
    # 4sapi 上同一把钥匙可请求任意模型,通不通取决于钥匙分组的通道。
    "chatgpt": "claude",
}
# 2026-07-22 实况:4sapi 的「OpenAI优质」分组会整组掉线(5.5/5.6 全家 503
# "No available channel"),低档通道仍活着。同 provider 内按序降级,
# 通道恢复后首选模型自动回归——不用人工切配置。
MODEL_FALLBACKS: dict[str, list[str]] = {
    "chatgpt": ["gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.2-high"],
}
# 240s:降级到低档模型(如 5.2-high)生成整页文案实测会超过 150s;
# 生成类任务全部走异步 job,放宽超时不影响交互体验(2026-07-22)。
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 240.0
DEFAULT_PROVIDER_MAX_ATTEMPTS = 1


class AIProviderExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        provider: str,
        task_type: str,
        status_code: int = 502,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.provider = provider
        self.task_type = task_type
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

    def structured_error(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "provider": self.provider,
            "task_type": self.task_type,
            "details": self.details,
        }


class AIModelRouter:
    @classmethod
    def resolve_model(cls, *, provider: str, task_type: str) -> str | None:
        canonical = normalize_provider(provider)
        provider_models = MODEL_REGISTRY.get(canonical, {})
        if task_type in provider_models:
            return provider_models[task_type]
        return provider_models.get("default")

    @classmethod
    def registry(cls) -> dict[str, dict[str, str | None]]:
        return {
            provider: dict(models)
            for provider, models in MODEL_REGISTRY.items()
        }


@dataclass(frozen=True)
class ProviderRequest:
    url: str
    headers: dict[str, str]
    body: dict[str, Any]


class BaseProviderAdapter:
    endpoint_map: dict[str, str] = {}

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        header_name: str,
        key_alias: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.header_name = header_name
        self.key_alias = key_alias

    def endpoint_for(self, task_type: str) -> str:
        endpoint = self.endpoint_map.get(task_type) or self.endpoint_map["default"]
        return endpoint if endpoint.startswith("/") else f"/{endpoint}"

    def build_request(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> ProviderRequest:
        endpoint = self.endpoint_for(task_type)
        return ProviderRequest(
            url=f"{self.base_url}{endpoint}",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                self.header_name: self.api_key,
            },
            body=self.request_builder(
                task_type=task_type,
                payload=payload,
                model=model,
            ),
        )

    def request_builder(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> dict[str, Any]:
        messages = _messages_from_payload(payload)
        return {
            **payload,
            "model": model,
            "messages": messages,
            "task_type": task_type,
        }

    def response_parser(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = _parse_provider_content(response)
        return parsed if parsed is not None else response


class SerperAdapter(BaseProviderAdapter):
    endpoint_map = {
        "default": "/search",
        "search": "/search",
    }

    def build_request(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> ProviderRequest:
        request = super().build_request(
            task_type=task_type,
            payload=payload,
            model=model,
        )
        headers = dict(request.headers)
        headers["X-API-KEY"] = self.api_key.removeprefix("Bearer ").strip()
        headers.pop("Authorization", None)
        return ProviderRequest(
            url=request.url,
            headers=headers,
            body=self.request_builder(
                task_type=task_type,
                payload=payload,
                model=model,
            ),
        )

    def request_builder(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> dict[str, Any]:
        query = payload.get("query") or payload.get("main_keyword")
        market = str(payload.get("target_market") or payload.get("market") or "US").strip()
        body: dict[str, Any] = {
            **payload,
            "model": model,
            "messages": _messages_from_payload(payload),
            "task_type": task_type,
            "q": str(query or "").strip(),
            "gl": market.lower()[:2] or "us",
            "num": 10,
        }
        if payload.get("target_language"):
            body["hl"] = str(payload["target_language"]).split("-")[0].lower()
        return body


class OpenAIAdapter(BaseProviderAdapter):
    endpoint_map = {
        "default": "/v1/chat/completions",
        "chat": "/v1/chat/completions",
        "generate": "/v1/chat/completions",
        "selling_points": "/v1/chat/completions",
    }

    # OpenAI-compatible chat APIs (incl. 4sapi) reject unknown top-level params
    # (e.g. HTTP 400 "Unknown parameter: 'instruction'"), so send a clean body
    # instead of spreading the whole payload. All caller context is preserved
    # inside `messages` via _messages_from_payload.
    _PASSTHROUGH_PARAMS = (
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "response_format",
        "stop",
        "seed",
        "stream",
    )

    def request_builder(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> dict[str, Any]:
        del task_type
        body: dict[str, Any] = {
            "model": model,
            "messages": _messages_from_payload(payload),
        }
        for key in self._PASSTHROUGH_PARAMS:
            if payload.get(key) is not None:
                body[key] = payload[key]
        return body


class ClaudeAdapter(BaseProviderAdapter):
    endpoint_map = {
        "default": "/v1/messages",
        "chat": "/v1/messages",
        "generate": "/v1/messages",
    }


class DeepSeekAdapter(OpenAIAdapter):
    endpoint_map = {
        "default": "/v1/chat/completions",
        "chat": "/v1/chat/completions",
        "generate": "/v1/chat/completions",
        "selling_points": "/v1/chat/completions",
    }


ADAPTERS = {
    "serp": SerperAdapter,
    "chatgpt": OpenAIAdapter,
    "claude": ClaudeAdapter,
    "deepseek": DeepSeekAdapter,
}


def _messages_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    messages = payload.get("messages")
    if isinstance(messages, list) and all(isinstance(item, dict) for item in messages):
        normalized = []
        for item in messages:
            role = str(item.get("role") or "user")
            content = item.get("content")
            normalized.append(
                {
                    "role": role,
                    "content": (
                        content
                        if isinstance(content, str)
                        else json.dumps(content, ensure_ascii=False, default=str)
                    ),
                }
            )
        return normalized
    prompt = payload.get("prompt") or payload.get("query")
    if not isinstance(prompt, str):
        prompt = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    return [{"role": "user", "content": prompt}]


def _parse_json_text(value: str) -> dict[str, Any] | None:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _parse_provider_content(response: dict[str, Any]) -> dict[str, Any] | None:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return _parse_json_text(content) or {"content": content}
    content = response.get("content")
    if isinstance(content, list) and content:
        texts = [
            item.get("text")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        joined = "\n".join(texts).strip()
        if joined:
            return _parse_json_text(joined) or {"content": joined}
    if isinstance(content, str):
        return _parse_json_text(content) or {"content": content}
    return None


def _post_json(
    *,
    request: ProviderRequest,
    timeout_seconds: float,
) -> dict[str, Any]:
    data = json.dumps(request.body).encode("utf-8")
    url_request = UrlRequest(
        request.url,
        data=data,
        headers=request.headers,
        method="POST",
    )
    with urlopen(url_request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("provider_response_not_object")
    return parsed


class AIExecutionRouter:
    def __init__(
        self,
        db: Session,
        *,
        timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_PROVIDER_MAX_ATTEMPTS,
    ) -> None:
        self.db = db
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)

    def execute(
        self,
        *,
        provider: str,
        task_type: AITaskType,
        payload: dict[str, Any],
        org: str,
        module_id: str = "k.product_knowledge",
        user: User | None = None,
        request: Request | None = None,
        execution_context: ModuleExecutionContext | None = None,
        fallback_provider: str | None = None,
    ) -> dict[str, Any]:
        canonical_provider = normalize_provider(provider)
        org_record = self._resolve_org(org)
        context = execution_context or require_module_execution_ready(
            self.db,
            module_id=module_id,
            user=user,
            request=request,
            explicit_org_id=org_record.org_id,
            key_requirements={
                canonical_provider: provider_key_alias(canonical_provider)
            },
        )
        self._validate_context_org(context=context, org_record=org_record)
        key = self._key_for_provider(context, canonical_provider)
        return self._execute_with_key(
            provider=canonical_provider,
            task_type=task_type,
            payload=payload,
            org_record=org_record,
            module_id=context.control_module_id,
            key=key,
            execution_context=context,
            fallback_provider=fallback_provider,
            fallback_allowed=True,
        )

    def _execute_with_key(
        self,
        *,
        provider: str,
        task_type: AITaskType,
        payload: dict[str, Any],
        org_record: OrganizationRecord,
        module_id: str,
        key: ModuleExecutionKey,
        execution_context: ModuleExecutionContext,
        fallback_provider: str | None,
        fallback_allowed: bool,
    ) -> dict[str, Any]:
        model = AIModelRouter.resolve_model(provider=provider, task_type=task_type)
        config = upsert_provider_config(
            self.db,
            org_id=org_record.org_id,
            module_id=module_id,
            provider=provider,
            base_url=key.url,
            source_key_id=key.key_id,
            metadata={
                "source": "ai_execution_router",
                "key_alias": key.key_alias,
            },
        )
        config = (
            get_provider_config(
                self.db,
                org_id=org_record.org_id,
                module_id=module_id,
                provider=provider,
            )
            or config
        )
        adapter = ADAPTERS[provider](
            base_url=config.base_url,
            api_key=key.header_value,
            header_name=key.header_name,
            key_alias=key.key_alias,
        )
        base_url = config.base_url
        endpoint_called = adapter.endpoint_for(task_type)
        self._release_db_transaction()
        # 首选模型 + 同 provider 内的降级序列;仅通道级 503 才向下换模型
        model_candidates = [model] + [
            candidate
            for candidate in MODEL_FALLBACKS.get(provider, [])
            if candidate and candidate != model
        ]
        last_error: AIProviderExecutionError | None = None
        for active_model in model_candidates:
            provider_request = adapter.build_request(
                task_type=task_type,
                payload=payload,
                model=active_model,
            )
            channel_down = False
            for attempt in range(1, self.max_attempts + 1):
                started = perf_counter()
                try:
                    raw_response = _post_json(
                        request=provider_request,
                        timeout_seconds=self.timeout_seconds,
                    )
                    parsed = adapter.response_parser(raw_response)
                    latency_ms = (perf_counter() - started) * 1000
                    self._emit_execution_event(
                        provider=provider,
                        task_type=task_type,
                        org_id=org_record.org_id,
                        status="success",
                        latency_ms=latency_ms,
                        base_url=base_url,
                        endpoint_called=endpoint_called,
                        key_alias=key.key_alias,
                        model=active_model,
                        attempt=attempt,
                    )
                    self._release_db_transaction()
                    return parsed
                except HTTPError as exc:
                    channel_down = exc.code == 503
                    last_error = AIProviderExecutionError(
                        "AI_PROVIDER_HTTP_ERROR",
                        f"AI provider '{provider}' returned HTTP {exc.code}.",
                        provider=provider,
                        task_type=task_type,
                        status_code=502,
                        details={
                            "http_status": exc.code,
                            "attempt": attempt,
                            "model": active_model,
                        },
                    )
                except TimeoutError as exc:
                    last_error = AIProviderExecutionError(
                        "AI_PROVIDER_TIMEOUT",
                        f"AI provider '{provider}' request timed out.",
                        provider=provider,
                        task_type=task_type,
                        status_code=504,
                        details={"attempt": attempt, "model": active_model},
                    )
                except (URLError, json.JSONDecodeError, ValueError) as exc:
                    last_error = AIProviderExecutionError(
                        "AI_PROVIDER_REQUEST_FAILED",
                        f"AI provider '{provider}' request failed.",
                        provider=provider,
                        task_type=task_type,
                        status_code=502,
                        details={
                            "attempt": attempt,
                            "error_class": exc.__class__.__name__,
                            "model": active_model,
                        },
                    )
                latency_ms = (perf_counter() - started) * 1000
                self._emit_execution_event(
                    provider=provider,
                    task_type=task_type,
                    org_id=org_record.org_id,
                    status="failed",
                    latency_ms=latency_ms,
                    base_url=base_url,
                    endpoint_called=endpoint_called,
                    key_alias=key.key_alias,
                    model=active_model,
                    attempt=attempt,
                    error=last_error.structured_error() if last_error else None,
                )
                self._release_db_transaction()
            if not channel_down:
                break

        resolved_fallback = fallback_provider or DEFAULT_FALLBACK_PROVIDERS.get(provider)
        if fallback_allowed and resolved_fallback:
            try:
                fallback = normalize_provider(resolved_fallback)
                fallback_key = self._key_for_provider(execution_context, fallback)
                return self._execute_with_key(
                    provider=fallback,
                    task_type=task_type,
                    payload=payload,
                    org_record=org_record,
                    module_id=module_id,
                    key=fallback_key,
                    execution_context=execution_context,
                    fallback_provider=None,
                    fallback_allowed=False,
                )
            except (ProviderConfigError, AIProviderExecutionError):
                pass

        raise last_error or AIProviderExecutionError(
            "AI_PROVIDER_REQUEST_FAILED",
            f"AI provider '{provider}' request failed.",
            provider=provider,
            task_type=task_type,
        )

    def _release_db_transaction(self) -> None:
        if not self.db.in_transaction():
            return
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _resolve_org(self, org: str) -> OrganizationRecord:
        candidate = org.strip()
        if not candidate:
            raise AIProviderExecutionError(
                "AI_PROVIDER_ORG_REQUIRED",
                "AI execution requires an organization.",
                provider="unknown",
                task_type="chat",
                status_code=403,
            )
        if candidate.startswith("org_"):
            record = self.db.get(OrganizationRecord, candidate)
        else:
            record = self.db.scalar(
                select(OrganizationRecord).where(
                    OrganizationRecord.org_name == candidate,
                    OrganizationRecord.status != "deleted",
                )
            )
        if record is None:
            raise AIProviderExecutionError(
                "AI_PROVIDER_ORG_NOT_FOUND",
                "AI execution organization was not found.",
                provider="unknown",
                task_type="chat",
                status_code=404,
                details={"org": candidate},
            )
        return record

    def _validate_context_org(
        self,
        *,
        context: ModuleExecutionContext,
        org_record: OrganizationRecord,
    ) -> None:
        if context.org_id != org_record.org_id:
            raise AIProviderExecutionError(
                "AI_PROVIDER_ORG_MISMATCH",
                "AI execution organization does not match execution gate context.",
                provider="unknown",
                task_type="chat",
                status_code=403,
                details={
                    "context_org_id": context.org_id,
                    "requested_org_id": org_record.org_id,
                },
            )

    def _key_for_provider(
        self,
        context: ModuleExecutionContext,
        provider: str,
    ) -> ModuleExecutionKey:
        expected_alias = provider_key_alias(provider)
        accepted_aliases = {provider, expected_alias}
        if provider == "chatgpt":
            accepted_aliases.add("ai_provider")
        for step, key in context.keys.items():
            if step in accepted_aliases or key.key_alias in accepted_aliases:
                return key
            try:
                if normalize_provider(key.key_alias) == provider:
                    return key
            except ProviderConfigError:
                continue
        if len(context.keys) == 1:
            return next(iter(context.keys.values()))
        raise AIProviderExecutionError(
            "AI_PROVIDER_KEY_MISSING",
            f"Resolved execution context does not include provider '{provider}'.",
            provider=provider,
            task_type="chat",
            status_code=403,
            details={"available_steps": sorted(context.keys)},
        )

    def _emit_execution_event(
        self,
        *,
        provider: str,
        task_type: str,
        org_id: str,
        status: Literal["success", "failed"],
        latency_ms: float,
        base_url: str,
        endpoint_called: str,
        key_alias: str,
        model: str | None,
        attempt: int,
        error: dict[str, Any] | None = None,
    ) -> None:
        emit_event(
            event_type="ai_provider.execute",
            module="system",
            action="ai_provider.execute",
            source="backend",
            status=status,
            org_id=org_id,
            latency_ms=latency_ms,
            payload={
                "provider_used": provider,
                "base_url_used": base_url,
                "endpoint_called": endpoint_called,
                "api_key_alias": key_alias,
                "task_type": task_type,
                "model": model,
                "attempt": attempt,
                "success": status == "success",
                "error": error,
            },
        )


def provider_execution_report_static_mapping() -> dict[str, Any]:
    return {
        "model_registry": AIModelRouter.registry(),
        "provider_registry_mapping": provider_registry_mapping(),
        "execution_flow": [
            "resolve provider",
            "resolve model",
            "resolve endpoint",
            "inject api key",
            "execute request",
        ],
    }
