"""Provider key bindings for R-A analysis workers."""

from __future__ import annotations

from dataclasses import dataclass

from r_system_v2.core.secret_manager import SecretManager


@dataclass(frozen=True)
class RAnalysisProviderKeys:
    deepseek: str
    openai: str
    opus: str
    serper: str

    def configured(self) -> dict[str, bool]:
        return {
            "deepseek": bool(self.deepseek),
            "openai": bool(self.openai),
            "opus": bool(self.opus),
            "serper": bool(self.serper),
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

    def gpt_key(self) -> str:
        return self.secret_manager.get_key("openai", self.org_id)

    def opus_key(self) -> str:
        return self.secret_manager.get_key("openai", self.org_id)

    def serper_key(self) -> str:
        return self.secret_manager.get_key("serper", self.org_id)

    def all_keys(self) -> RAnalysisProviderKeys:
        return RAnalysisProviderKeys(
            deepseek=self.deepseek_key(),
            openai=self.gpt_key(),
            opus=self.opus_key(),
            serper=self.serper_key(),
        )
