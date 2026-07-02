"""DeepSeek batch provider for R-W."""

from __future__ import annotations

from r_system_v2.core.secret_manager import SecretManager
from r_system_v2.rw.ai.deepseek_screening import (
    DeepSeekBatchResult,
    DeepSeekScreeningSkill,
)
from r_system_v2.rw.core.models import NormalizedProduct


class DeepSeekProvider:
    """Batch-only DeepSeek adapter with no scheduling authority."""

    def __init__(
        self,
        *,
        org_id: str | None = None,
        secret_manager: SecretManager | None = None,
        skill: DeepSeekScreeningSkill | None = None,
    ) -> None:
        self.org_id = org_id
        self.secret_manager = secret_manager or SecretManager()
        self.skill = skill or DeepSeekScreeningSkill(
            org_id=org_id,
            secret_manager=self.secret_manager,
        )

    def reload_secret(self) -> str:
        return self.skill.reload_secret()

    def current_api_key(self) -> str:
        return self.skill.current_api_key()

    def evaluate_batch(self, products: list[NormalizedProduct]) -> DeepSeekBatchResult:
        return self.skill.evaluate_batch(products)

    def status(self) -> dict[str, object]:
        return {
            "mode": "batch_processor_only",
            "scheduling_authority": False,
            "api_key_configured": self.skill.api_key_configured(),
            "skill": self.skill.status.to_dict(),
        }
