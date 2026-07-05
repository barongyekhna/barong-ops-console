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
    deepseek: str
    foursapi: str
    serper: str

    def configured(self) -> dict[str, bool]:
        foursapi_configured = bool(self.foursapi)
        return {
            "deepseek": bool(self.deepseek),
            "gpt": foursapi_configured,
            "opus": foursapi_configured,
            "foursapi": foursapi_configured,
            "serper": bool(self.serper),
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
        return self.foursapi_key()

    def opus_key(self) -> str:
        return self.foursapi_key()

    def serper_key(self) -> str:
        return self.secret_manager.get_key("serper", self.org_id)

    def all_keys(self) -> RAnalysisProviderKeys:
        return RAnalysisProviderKeys(
            deepseek=self.deepseek_key(),
            foursapi=self.foursapi_key(),
            serper=self.serper_key(),
        )

    def status(self) -> dict[str, Any]:
        return {
            "roles": [item.to_dict() for item in self.role_statuses()],
            "routing": {
                "deepseek": "deepseek",
                "gpt": "4sapi",
                "opus": "4sapi",
                "serper": "serper",
                "crawler_1688": "playwright",
            },
            "external_calls_enabled": False,
        }

    def role_statuses(self) -> list[RAnalysisProviderStatus]:
        deepseek = self._secret_status("deepseek")
        foursapi = self._secret_status("4sapi")
        serper = self._secret_status("serper")
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
                configured=foursapi["configured"],
                source=foursapi["source"],
                model_env="RA_GPT_MODEL",
                model_name=os.getenv("RA_GPT_MODEL", ""),
                base_url_env="FOURSAPI_BASE_URL",
                base_url_configured=bool(os.getenv("FOURSAPI_BASE_URL", "").strip()),
            ),
            RAnalysisProviderStatus(
                role="opus",
                service="4sapi",
                label="Opus 第三层最终决策",
                configured=foursapi["configured"],
                source=foursapi["source"],
                model_env="RA_OPUS_MODEL",
                model_name=os.getenv("RA_OPUS_MODEL", ""),
                base_url_env="FOURSAPI_BASE_URL",
                base_url_configured=bool(os.getenv("FOURSAPI_BASE_URL", "").strip()),
            ),
            RAnalysisProviderStatus(
                role="serper",
                service="serper",
                label="Serper 手动搜索与 1688 发现",
                configured=serper["configured"],
                source=serper["source"],
            ),
            RAnalysisProviderStatus(
                role="crawler_1688",
                service="playwright",
                label="1688 Playwright 页面抓取",
                configured=bool(os.getenv("RA_1688_COOKIE_PROFILE", "").strip()),
                source="runtime_profile",
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
        }
