"""Provider role bindings for the R-A analysis framework.

R-A uses model roles in the product-selection funnel. GPT and Opus are roles,
not direct OpenAI/Anthropic SDK bindings; both are expected to route through the
4sapi proxy key configured in the existing API-key orchestration layer.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError


@dataclass(frozen=True)
class RAnalysisProviderKeys:
    deepseek: str = ""
    foursapi: str = ""
    serper: str = ""
    alibaba1688: str = ""
    rainforest: str = ""

    def configured(self) -> dict[str, bool]:
        foursapi_configured = bool(self.foursapi)
        return {
            "deepseek": bool(self.deepseek),
            "gpt": foursapi_configured,
            "opus": foursapi_configured,
            "foursapi": foursapi_configured,
            "serper": bool(self.serper),
            "alibaba1688": bool(self.alibaba1688),
            "rainforest": bool(self.rainforest),
        }


@dataclass(frozen=True)
class RAnalysisProviderStatus:
    role: str
    service: str
    label: str
    configured: bool
    source: str
    model_env: str | None = None
    model_name: str | None = None
    base_url_env: str | None = None
    base_url_configured: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "service": self.service,
            "label": self.label,
            "configured": self.configured,
            "source": self.source,
            "model_env": self.model_env,
            "model_name": self.model_name,
            "base_url_env": self.base_url_env,
            "base_url_configured": self.base_url_configured,
        }


class RAnalysisProviderBinding:
    """Resolve R-A provider credentials through the unified SecretManager."""

    def __init__(
        self,
        *,
        org_id: str,
        secret_manager: SecretManager | None = None,
    ) -> None:
        self.org_id = org_id
        self.secret_manager = secret_manager or SecretManager()

    def reload(self) -> dict[str, object]:
        return self.secret_manager.reload()

    def deepseek_key(self) -> str:
        return self.secret_manager.get_key("deepseek", self.org_id)

    def foursapi_key(self) -> str:
        return self.secret_manager.get_key("4sapi", self.org_id)

    def gpt_key(self) -> str:
        return str(self.gpt_config().get("value") or "")

    def opus_key(self) -> str:
        return str(self.opus_config().get("value") or "")

    def serper_key(self) -> str:
        return self.secret_manager.get_key("serper", self.org_id)

    def alibaba1688_key(self) -> str:
        return self.secret_manager.get_key("alibaba1688", self.org_id)

    def rainforest_key(self) -> str:
        return self.secret_manager.get_key("rainforest", self.org_id)

    def deepseek_config(self) -> dict[str, Any]:
        return self.secret_manager.get_secret_config("deepseek", self.org_id)

    def foursapi_config(self) -> dict[str, Any]:
        return self.secret_manager.get_secret_config("4sapi", self.org_id)

    def gpt_config(self) -> dict[str, Any]:
        return self._foursapi_role_config(
            role="gpt",
            markers=("chatgpt", "chat gpt", "gpt", "openai"),
        )

    def opus_config(self) -> dict[str, Any]:
        return self._foursapi_role_config(
            role="opus",
            markers=("opus", "claude", "anthropic", "claude_opus"),
        )

    def rainforest_config(self) -> dict[str, Any]:
        return self.secret_manager.get_secret_config("rainforest", self.org_id)

    def all_keys(self) -> RAnalysisProviderKeys:
        return RAnalysisProviderKeys(
            deepseek=self.deepseek_key(),
            foursapi=self.foursapi_key(),
            serper=self.serper_key(),
            alibaba1688=self.alibaba1688_key(),
            rainforest=self.rainforest_key(),
        )

    def status(self) -> dict[str, Any]:
        role_statuses = self.role_statuses()
        serper_ready = any(
            item.role == "serper" and item.configured for item in role_statuses
        )
        alibaba_ready = any(
            item.role == "alibaba1688" and item.configured for item in role_statuses
        )
        rainforest_ready = any(
            item.role == "rainforest" and item.configured for item in role_statuses
        )
        supplier_source_mode = os.getenv(
            "RA_SUPPLIER_SOURCE_MODE",
            "auto_1688_api",
        ).strip() or "auto_1688_api"
        return {
            "roles": [item.to_dict() for item in role_statuses],
            "routing": {
                "deepseek": "deepseek",
                "gpt": "4sapi",
                "opus": "4sapi",
                "serper": "serper",
                "alibaba1688": supplier_source_mode,
                "rainforest": "rainforest",
            },
            "supplier_source_mode": supplier_source_mode,
            "official_1688_configured": alibaba_ready,
            "supplier_cost_provider_ready": supplier_source_mode in {
                "mock_1688_api",
                "auto_1688_api",
            }
            or alibaba_ready,
            "competition_provider_ready": rainforest_ready,
            "external_calls_enabled": serper_ready or alibaba_ready or rainforest_ready,
        }

    def role_statuses(self) -> list[RAnalysisProviderStatus]:
        deepseek = self._secret_status("deepseek")
        gpt = self._role_secret_status("gpt")
        opus = self._role_secret_status("opus")
        serper = self._secret_status("serper")
        alibaba1688 = self._secret_status("alibaba1688")
        rainforest = self._secret_status("rainforest")
        return [
            RAnalysisProviderStatus(
                role="deepseek",
                service="deepseek",
                label="DeepSeek 第一层量化分析",
                configured=deepseek["configured"],
                source=deepseek["source"],
                model_env="DEEPSEEK_MODEL",
                model_name=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                base_url_env="DEEPSEEK_BASE_URL",
                base_url_configured=bool(os.getenv("DEEPSEEK_BASE_URL", "").strip()),
            ),
            RAnalysisProviderStatus(
                role="gpt",
                service="4sapi",
                label="GPT 第二层上下文验证",
                configured=gpt["configured"],
                source=gpt["source"],
                model_env="RA_GPT_MODEL",
                model_name=os.getenv("RA_GPT_MODEL", "gpt-5.5"),
                base_url_env="FOURSAPI_BASE_URL",
                base_url_configured=bool(os.getenv("FOURSAPI_BASE_URL", "").strip())
                or bool(gpt.get("url")),
            ),
            RAnalysisProviderStatus(
                role="opus",
                service="4sapi",
                label="Opus 第三层最终决策",
                configured=opus["configured"],
                source=opus["source"],
                model_env="RA_OPUS_MODEL",
                model_name=os.getenv("RA_OPUS_MODEL", "claude-opus-4-8-thinking"),
                base_url_env="FOURSAPI_BASE_URL",
                base_url_configured=bool(os.getenv("FOURSAPI_BASE_URL", "").strip())
                or bool(opus.get("url")),
            ),
            RAnalysisProviderStatus(
                role="serper",
                service="serper",
                label="Serper 手动 SEO / Google SERP 分析",
                configured=serper["configured"],
                source=serper["source"],
            ),
            RAnalysisProviderStatus(
                role="alibaba1688",
                service="alibaba1688",
                label="1688 官方 API 供应商与成本",
                configured=alibaba1688["configured"],
                source=alibaba1688["source"],
                base_url_env="RA_1688_OPEN_API_BASE_URL",
                base_url_configured=bool(os.getenv("RA_1688_OPEN_API_BASE_URL", "").strip()),
            ),
            RAnalysisProviderStatus(
                role="rainforest",
                service="rainforest",
                label="Rainforest 亚马逊竞争页一数据",
                configured=rainforest["configured"],
                source=rainforest["source"],
                base_url_env="RAINFOREST_BASE_URL",
                base_url_configured=bool(os.getenv("RAINFOREST_BASE_URL", "").strip())
                or bool(rainforest.get("url")),
            ),
            RAnalysisProviderStatus(
                role="mock_1688_api",
                service="mock_1688_api",
                label="1688 官方 API Mock",
                configured=True,
                source="local_mock_until_official_api_ready",
            ),
        ]

    def _secret_status(self, service: str) -> dict[str, Any]:
        try:
            status = self.secret_manager.status(service, self.org_id).to_dict()
        except SecretManagerError:
            return {
                "service": service,
                "configured": False,
                "source": "api_key_orchestration_missing",
            }
        return {
            "service": service,
            "configured": bool(status.get("configured")),
            "source": str(status.get("source") or "api_key_orchestration"),
            "url": status.get("url"),
        }

    def _role_secret_status(self, role: str) -> dict[str, Any]:
        try:
            config = self.gpt_config() if role == "gpt" else self.opus_config()
        except SecretManagerError:
            return {
                "service": "4sapi",
                "configured": False,
                "source": "api_key_orchestration_missing",
            }
        return {
            "service": "4sapi",
            "configured": bool(config.get("value")),
            "source": "api_key_orchestration_role_match",
            "url": config.get("url"),
        }

    def _foursapi_role_config(
        self,
        *,
        role: str,
        markers: tuple[str, ...],
    ) -> dict[str, Any]:
        db = getattr(self.secret_manager, "db_session", None)
        if db is None:
            return self.foursapi_config()
        try:
            candidates = _resolve_r_analysis_key_candidates(db, self.org_id)
        except Exception:
            return self.foursapi_config()
        fallback: dict[str, Any] | None = None
        for candidate in candidates:
            marker_text = " ".join(
                str(candidate.get(name) or "").lower()
                for name in ("name", "key_alias", "key_type", "provider")
            )
            if fallback is None:
                fallback = candidate
            if any(marker in marker_text for marker in markers):
                return {**candidate, "role": role}
        if fallback is not None:
            return {**fallback, "role": role}
        return self.foursapi_config()


def _resolve_r_analysis_key_candidates(db: Any, org_id: str) -> list[dict[str, Any]]:
    try:
        from backend.app.services.api_key_orchestration import (
            ApiKeyIsolationError,
            ApiKeyOrchestrationError,
            resolve_module_api_key_candidates_for_injection,
        )
    except ImportError:
        from app.services.api_key_orchestration import (  # type: ignore[no-redef]
            ApiKeyIsolationError,
            ApiKeyOrchestrationError,
            resolve_module_api_key_candidates_for_injection,
        )
    try:
        contexts = resolve_module_api_key_candidates_for_injection(
            db,
            org_id=org_id,
            module_id="r.analysis",
            key_aliases=("4sapi", "chatgpt", "claude_opus", "openai"),
        )
    except (ApiKeyIsolationError, ApiKeyOrchestrationError) as exc:
        raise SecretManagerError(str(exc)) from exc
    output: list[dict[str, Any]] = []
    for context in contexts:
        raw_key = _raw_key_from_context(context)
        if not raw_key:
            continue
        output.append(
            {
                "service": "openai",
                "value": raw_key,
                "key": raw_key,
                "url": str(getattr(context, "url", "") or "").strip() or None,
                "name": str(getattr(context, "name", "") or "").strip() or None,
                "key_type": str(getattr(context, "key_type", "") or "").strip() or None,
                "provider": str(getattr(context, "provider", "") or "").strip() or None,
                "module_id": str(getattr(context, "module_id", "") or "").strip(),
                "key_alias": str(getattr(context, "key_alias", "") or "").strip(),
                "key_id": str(getattr(context, "key_id", "") or "").strip(),
            }
        )
    return output


def _raw_key_from_context(context: Any) -> str:
    query_value = getattr(context, "query_param_value", None)
    if isinstance(query_value, str) and query_value.strip():
        return query_value.strip()
    header_value = str(getattr(context, "header_value", "") or "").strip()
    if header_value.lower().startswith("bearer "):
        return header_value[7:].strip()
    return header_value
