from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..schemas.execution_provider import ExecutionProviderContractV1
from ..schemas.execution_router import ExecutionProviderSelection, ExecutionRuntimeMode
from .execution_provider_registry import list_execution_provider_contracts


ProviderResolutionStatus = Literal["selected", "missing"]


class ProviderResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderResolution:
    status: ProviderResolutionStatus
    requested_mode: ExecutionRuntimeMode
    selected_mode: ExecutionRuntimeMode | None
    provider: ExecutionProviderContractV1 | None
    selection: ExecutionProviderSelection | None
    reason: str


class ProviderResolver:
    """Runtime provider resolver.

    The static C09 registry remains metadata only. This resolver performs
    request-time selection for ExecutionRouter and never invokes a provider.
    """

    def __init__(
        self,
        providers: list[ExecutionProviderContractV1] | None = None,
    ) -> None:
        self._providers = providers

    def resolve(
        self,
        *,
        module_id: str,
        action: str,
        requested_mode: ExecutionRuntimeMode = "mock",
    ) -> ProviderResolution:
        candidates = [
            provider
            for provider in self._list_providers()
            if provider.module_key == module_id and provider.action_key == action
        ]
        if not candidates:
            return ProviderResolution(
                status="missing",
                requested_mode=requested_mode,
                selected_mode=None,
                provider=None,
                selection=None,
                reason="No provider metadata is registered for module/action.",
            )

        ranked_modes = self._mode_preferences(requested_mode)
        for selected_mode in ranked_modes:
            provider = self._first_ready_provider(candidates, selected_mode)
            if provider is None:
                continue
            return ProviderResolution(
                status="selected",
                requested_mode=requested_mode,
                selected_mode=selected_mode,
                provider=provider,
                selection=ExecutionProviderSelection(
                    provider_key=provider.provider_key,
                    provider_type=provider.provider_type,
                    provider_readiness=provider.provider_readiness,
                    selected_mode=selected_mode,
                    selection_reason=(
                        "ProviderResolver selected metadata for "
                        f"{selected_mode} mode; execution remains gated by "
                        "ExecutionRouter."
                    ),
                ),
                reason="Provider metadata selected by runtime resolver.",
            )

        return ProviderResolution(
            status="missing",
            requested_mode=requested_mode,
            selected_mode=None,
            provider=None,
            selection=None,
            reason=(
                "Registered provider metadata exists, but no provider readiness "
                f"matches requested mode {requested_mode}."
            ),
        )

    def _list_providers(self) -> list[ExecutionProviderContractV1]:
        return self._providers if self._providers is not None else list_execution_provider_contracts()

    def _mode_preferences(
        self,
        requested_mode: ExecutionRuntimeMode,
    ) -> tuple[ExecutionRuntimeMode, ...]:
        if requested_mode == "live":
            return ("live",)
        if requested_mode == "staging":
            return ("staging", "mock")
        return ("mock",)

    def _first_ready_provider(
        self,
        candidates: list[ExecutionProviderContractV1],
        selected_mode: ExecutionRuntimeMode,
    ) -> ExecutionProviderContractV1 | None:
        readiness = {
            "mock": "mock",
            "staging": "staging_ready",
            "live": "live_ready",
        }[selected_mode]
        matches = [
            provider
            for provider in candidates
            if provider.provider_readiness == readiness
            and selected_mode in self._supported_modes(provider, selected_mode)
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda provider: provider.provider_key)[0]

    def _supported_modes(
        self,
        provider: ExecutionProviderContractV1,
        selected_mode: ExecutionRuntimeMode,
    ) -> set[str]:
        supported = set(provider.supported_execution_modes)
        if provider.provider_readiness == "mock":
            supported.add("mock")
        if provider.provider_readiness == "staging_ready":
            supported.add("staging")
        if provider.provider_readiness == "live_ready":
            supported.add("live")
        return supported
