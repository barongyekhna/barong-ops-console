"""Runtime secret reload listener for R-W and R-A workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from r_system_v2.core.secret_event_bus import (
    SECRET_RELOAD_REQUESTED,
    SECRET_UPDATED,
    SecretEvent,
    SecretEventBus,
    secret_event_bus,
)
from r_system_v2.core.secret_manager import SecretManager


@dataclass
class SecretWatchStatus:
    subscribed: bool
    reload_count: int = 0
    last_event_type: str | None = None
    last_org_id: str | None = None
    last_service: str | None = None
    reloaded_targets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "subscribed": self.subscribed,
            "reload_count": self.reload_count,
            "last_event_type": self.last_event_type,
            "last_org_id": self.last_org_id,
            "last_service": self.last_service,
            "reloaded_targets": self.reloaded_targets,
        }


class SecretWatchDaemon:
    """Subscribe local worker objects to secret update events."""

    def __init__(
        self,
        *,
        org_id: str,
        secret_manager: SecretManager,
        keepa_provider: Any | None = None,
        deepseek_skill: Any | None = None,
        r_analysis_binding: Any | None = None,
        event_bus: SecretEventBus = secret_event_bus,
    ) -> None:
        self.org_id = org_id
        self.secret_manager = secret_manager
        self.keepa_provider = keepa_provider
        self.deepseek_skill = deepseek_skill
        self.r_analysis_binding = r_analysis_binding
        self.event_bus = event_bus
        self._subscription_token: str | None = None
        self.status = SecretWatchStatus(subscribed=False)

    def start(self) -> SecretWatchStatus:
        if self._subscription_token is None:
            self._subscription_token = self.event_bus.subscribe(self.handle_event)
            self.status.subscribed = True
        return self.status

    def stop(self) -> None:
        if self._subscription_token is not None:
            self.event_bus.unsubscribe(self._subscription_token)
            self._subscription_token = None
        self.status.subscribed = False

    def handle_event(self, event: SecretEvent) -> None:
        if event.event_type not in {SECRET_UPDATED, SECRET_RELOAD_REQUESTED}:
            return
        if event.org_id not in {self.org_id, "*"}:
            return

        service = event.service
        if service is not None:
            self.secret_manager.invalidate_cache(org_id=self.org_id, service=service)
        else:
            self.secret_manager.invalidate_cache(org_id=self.org_id)

        reloaded = self._reload_targets(service)
        self.status.reload_count += 1
        self.status.last_event_type = event.event_type
        self.status.last_org_id = event.org_id
        self.status.last_service = service
        self.status.reloaded_targets = reloaded

    def _reload_targets(self, service: str | None) -> list[str]:
        reloaded: list[str] = []
        if service in {None, "keepa"} and self.keepa_provider is not None:
            self.keepa_provider.reload_secret()
            reloaded.append("rw.keepa")
        if service in {None, "deepseek"} and self.deepseek_skill is not None:
            self.deepseek_skill.reload_secret()
            reloaded.append("rw.deepseek")
        if self.r_analysis_binding is not None and service in {
            None,
            "deepseek",
            "openai",
            "serper",
        }:
            self.r_analysis_binding.reload()
            reloaded.append("ra.providers")
        return reloaded


def start_secret_watch_daemon(**kwargs: Any) -> SecretWatchDaemon:
    daemon = SecretWatchDaemon(**kwargs)
    daemon.start()
    return daemon
