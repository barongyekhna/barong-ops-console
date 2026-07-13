"""R System secret adapter backed by the existing API key orchestration layer."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from threading import Lock
from typing import Any, Callable, Iterator

from r_system_v2.core.secret_event_bus import (
    SECRET_RELOAD_REQUESTED,
    publish_secret_updated,
    secret_event_bus,
)


SUPPORTED_SERVICES = frozenset(
    {
        "keepa",
        "deepseek",
        "openai",
        "serper",
        "alibaba1688",
        "rainforest",
        "google_ads",
        "track17",
    }
)
TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"

R_WAREHOUSE_MODULE_ID = "r.warehouse"
K_PRODUCT_KNOWLEDGE_MODULE_ID = "k.product_knowledge"
I_IMAGE_SYSTEM_MODULE_ID = "i.image_system"
R_ANALYSIS_MODULE_ID = "r.analysis"
W_SITE_OPS_MODULE_ID = "w.site_ops"

SERVICE_BINDING_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "keepa": (
        (R_ANALYSIS_MODULE_ID, "keepa"),
        (R_WAREHOUSE_MODULE_ID, "keepa"),
    ),
    "deepseek": (
        (R_ANALYSIS_MODULE_ID, "deepseek"),
        (R_WAREHOUSE_MODULE_ID, "deepseek"),
        (K_PRODUCT_KNOWLEDGE_MODULE_ID, "deepseek"),
    ),
    "openai": (
        (R_ANALYSIS_MODULE_ID, "4sapi"),
        (R_ANALYSIS_MODULE_ID, "chatgpt"),
        (R_ANALYSIS_MODULE_ID, "openai"),
        (I_IMAGE_SYSTEM_MODULE_ID, "openai"),
        (I_IMAGE_SYSTEM_MODULE_ID, "chatgpt"),
        (I_IMAGE_SYSTEM_MODULE_ID, "4sapi"),
        (K_PRODUCT_KNOWLEDGE_MODULE_ID, "chatgpt"),
        (K_PRODUCT_KNOWLEDGE_MODULE_ID, "ai_provider"),
    ),
    "serper": (
        (R_ANALYSIS_MODULE_ID, "serp"),
        (R_ANALYSIS_MODULE_ID, "serper"),
        (K_PRODUCT_KNOWLEDGE_MODULE_ID, "serp"),
        (K_PRODUCT_KNOWLEDGE_MODULE_ID, "serper"),
    ),
    "alibaba1688": (
        (R_ANALYSIS_MODULE_ID, "alibaba1688"),
        (R_ANALYSIS_MODULE_ID, "alibaba_1688"),
        (R_ANALYSIS_MODULE_ID, "1688"),
    ),
    "rainforest": (
        (R_ANALYSIS_MODULE_ID, "rainforest"),
        (R_ANALYSIS_MODULE_ID, "rainforestapi"),
    ),
    "google_ads": (
        (R_ANALYSIS_MODULE_ID, "google_ads"),
        (R_ANALYSIS_MODULE_ID, "googleads"),
        (R_ANALYSIS_MODULE_ID, "keyword_planner"),
    ),
    "track17": (
        (W_SITE_OPS_MODULE_ID, "track17"),
        (W_SITE_OPS_MODULE_ID, "17track"),
    ),
}

SERVICE_KEY_TYPE_REQUIREMENTS: dict[str, frozenset[str]] = {
    "track17": frozenset({"track17"}),
}


class SecretManagerError(ValueError):
    pass


class SecretNotFoundError(SecretManagerError):
    pass


class SecretIsolationError(SecretManagerError):
    pass


@dataclass(frozen=True)
class SecretStatus:
    service: str
    org_id: str
    configured: bool
    source: str
    encrypted: bool
    updated_at: str | None = None
    module_id: str | None = None
    key_alias: str | None = None
    key_id: str | None = None
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "org_id": self.org_id,
            "configured": self.configured,
            "source": self.source,
            "encrypted": self.encrypted,
            "updated_at": self.updated_at,
            "module_id": self.module_id,
            "key_alias": self.key_alias,
            "key_id": self.key_id,
            "url": self.url,
        }


@dataclass(frozen=True)
class _SecretCacheEntry:
    value: str
    updated_at: str
    module_id: str
    key_alias: str
    key_id: str
    url: str | None = None
    name: str | None = None
    key_type: str | None = None
    provider: str | None = None


class SecretManager:
    """Resolve R-system keys from the original backend module key bindings.

    This class intentionally does not own a separate R-system secret table and
    does not read frontend configuration. K/I keep using
    ``resolve_module_api_key_for_injection`` directly; R-W/R-A use this adapter
    to resolve the same ``api_key_records`` + ``api_key_module_bindings`` source.
    """

    _cache: dict[tuple[str, str], _SecretCacheEntry] = {}
    _db_watch_snapshot: dict[tuple[str, str], str] = {}

    def __init__(self, db_session: Any | None = None, database_url: str | None = None) -> None:
        self.db_session = db_session
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self._owned_engine: Any | None = None
        self._owned_session_factory: Callable[[], Any] | None = None
        self._session_factory_lock = Lock()

    def get_key(self, service: str, org_id: str) -> str:
        service = self._normalize_service(service)
        org_id = self._normalize_org_id(org_id)
        with self._session_scope() as db:
            if db is None:
                cached = self._cache.get((org_id, service))
                if cached is not None:
                    return cached.value
                raise SecretNotFoundError(
                    f"api_key_orchestration_unavailable:{org_id}:{service}"
                )

            entry = self._resolve_from_api_key_orchestration(
                db,
                service=service,
                org_id=org_id,
            )
        self._cache[(org_id, service)] = entry
        return entry.value

    def get_secret_config(self, service: str, org_id: str) -> dict[str, Any]:
        service = self._normalize_service(service)
        org_id = self._normalize_org_id(org_id)
        with self._session_scope() as db:
            if db is None:
                entry = self._cache.get((org_id, service))
                if entry is None:
                    raise SecretNotFoundError(
                        f"api_key_orchestration_unavailable:{org_id}:{service}"
                    )
            else:
                entry = self._resolve_from_api_key_orchestration(
                    db,
                    service=service,
                    org_id=org_id,
                )
                self._cache[(org_id, service)] = entry
        return {
            "service": service,
            "org_id": org_id,
            "value": entry.value,
            "key": entry.value,
            "url": entry.url,
            "name": entry.name,
            "key_type": entry.key_type,
            "provider": entry.provider,
            "module_id": entry.module_id,
            "key_alias": entry.key_alias,
            "key_id": entry.key_id,
            "updated_at": entry.updated_at,
        }

    def set_key(self, service: str, value: str, org_id: str) -> SecretStatus:
        del service, value, org_id
        raise SecretManagerError("secret_write_disabled_use_api_key_orchestration")

    def reload(self, *, propagate: bool = True) -> dict[str, Any]:
        removed = self.invalidate_cache()
        if propagate:
            secret_event_bus.publish(
                SECRET_RELOAD_REQUESTED,
                org_id="*",
                source="secret_manager.reload",
            )
        return {
            "reloaded": True,
            "cache_entries": len(self._cache),
            "cache_entries_cleared": removed,
            "loaded": [],
            "runtime_hot_reload": True,
            "source": "api_key_orchestration",
        }

    @classmethod
    def invalidate_cache(cls, *, org_id: str | None = None, service: str | None = None) -> int:
        normalized_service = None
        if service is not None:
            normalized_service = service.strip().lower().replace("-", "_")
            if normalized_service == "serp":
                normalized_service = "serper"
            if normalized_service == "foursapi":
                normalized_service = "openai"
            if normalized_service == "chatgpt":
                normalized_service = "openai"
            if normalized_service in {"1688", "alibaba_1688", "alibaba"}:
                normalized_service = "alibaba1688"
            if normalized_service in {"rainforestapi", "api.rainforestapi.com"}:
                normalized_service = "rainforest"
            if normalized_service in {"googleads", "google_ads_api", "keyword_planner"}:
                normalized_service = "google_ads"
            if normalized_service in {"17track", "17_track"}:
                normalized_service = "track17"

        keys = list(cls._cache)
        removed = 0
        for key_org_id, key_service in keys:
            if org_id is not None and key_org_id != org_id:
                continue
            if normalized_service is not None and key_service != normalized_service:
                continue
            cls._cache.pop((key_org_id, key_service), None)
            removed += 1
        return removed

    def poll_database_updates(self) -> list[dict[str, str]]:
        snapshot = self._database_watch_snapshot()
        changed: list[dict[str, str]] = []
        for key, signature in snapshot.items():
            previous = self._db_watch_snapshot.get(key)
            if previous is None:
                continue
            if previous != signature:
                org_id, service = key
                self.invalidate_cache(org_id=org_id, service=service)
                publish_secret_updated(org_id, service, source="secret_manager.api_key_watch")
                changed.append({"org_id": org_id, "service": service})
        self._db_watch_snapshot = snapshot
        return changed

    def watch_database(
        self,
        *,
        interval_sec: float = 2.0,
        stop_event: Any | None = None,
    ) -> None:
        import time

        self._db_watch_snapshot = self._database_watch_snapshot()
        while stop_event is None or not stop_event.is_set():
            self.poll_database_updates()
            time.sleep(max(0.1, interval_sec))

    def validate_keys(self, org_id: str) -> dict[str, Any]:
        org_id = self._normalize_org_id(org_id)
        services = [self.status(service, org_id).to_dict() for service in sorted(SUPPORTED_SERVICES)]
        return {
            "org_id": org_id,
            "organization": TARGET_ORGANIZATION_NAME,
            "supported_services": sorted(SUPPORTED_SERVICES),
            "services": services,
            "all_configured": all(item["configured"] for item in services),
            "org_isolation": "enabled",
            "fallback_chain": "api_key_orchestration_only",
        }

    def status(self, service: str, org_id: str) -> SecretStatus:
        service = self._normalize_service(service)
        org_id = self._normalize_org_id(org_id)
        try:
            with self._session_scope() as db:
                if db is None:
                    raise SecretNotFoundError("api_key_orchestration_unavailable")
                entry = self._resolve_from_api_key_orchestration(
                    db,
                    service=service,
                    org_id=org_id,
                )
        except SecretManagerError:
            return SecretStatus(
                service=service,
                org_id=org_id,
                configured=False,
                source="api_key_orchestration_missing",
                encrypted=True,
            )
        self._cache[(org_id, service)] = entry
        return SecretStatus(
            service=service,
            org_id=org_id,
            configured=True,
            source="api_key_orchestration",
            encrypted=True,
            updated_at=entry.updated_at,
            module_id=entry.module_id,
            key_alias=entry.key_alias,
            key_id=entry.key_id,
            url=entry.url,
        )

    def migrate_env_to_db(self, org_id: str) -> dict[str, Any]:
        org_id = self._normalize_org_id(org_id)
        return {
            "org_id": org_id,
            "migrated": [],
            "skipped": sorted(SUPPORTED_SERVICES),
            "source": "api_key_orchestration_only",
        }

    def _normalize_service(self, service: str) -> str:
        normalized = service.strip().lower().replace("-", "_")
        if normalized in {"chatgpt", "gpt", "gpt_image", "4sapi", "foursapi"}:
            normalized = "openai"
        if normalized == "serp":
            normalized = "serper"
        if normalized in {"1688", "alibaba_1688", "alibaba"}:
            normalized = "alibaba1688"
        if normalized in {"rainforestapi", "api.rainforestapi.com"}:
            normalized = "rainforest"
        if normalized in {"googleads", "google_ads_api", "keyword_planner"}:
            normalized = "google_ads"
        if normalized in {"17track", "17_track"}:
            normalized = "track17"
        if normalized not in SUPPORTED_SERVICES:
            raise SecretManagerError(f"unsupported_service:{service}")
        return normalized

    def _normalize_org_id(self, org_id: str) -> str:
        normalized = org_id.strip()
        if not normalized:
            raise SecretIsolationError("org_id_required")
        return normalized

    @contextmanager
    def _session_scope(self) -> Iterator[Any | None]:
        if self.db_session is not None:
            yield self.db_session
            return

        session_factory = self._owned_factory()
        if session_factory is None:
            yield None
            return

        db = session_factory()
        try:
            yield db
        finally:
            try:
                if db.in_transaction():
                    db.rollback()
            except Exception:
                try:
                    db.invalidate()
                except Exception:
                    pass
            finally:
                db.close()

    def _owned_factory(self) -> Callable[[], Any] | None:
        if self._owned_session_factory is not None:
            return self._owned_session_factory
        if not self.database_url:
            return None
        with self._session_factory_lock:
            if self._owned_session_factory is not None:
                return self._owned_session_factory
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                return None
            self._owned_engine = create_engine(self.database_url, pool_pre_ping=True)
            self._owned_session_factory = sessionmaker(
                bind=self._owned_engine,
                expire_on_commit=False,
            )
        return self._owned_session_factory

    def close(self) -> None:
        with self._session_factory_lock:
            engine = self._owned_engine
            self._owned_engine = None
            self._owned_session_factory = None
        if engine is not None:
            engine.dispose()

    def _resolve_from_api_key_orchestration(
        self,
        db: Any,
        *,
        service: str,
        org_id: str,
    ) -> _SecretCacheEntry:
        resolver, isolation_error, orchestration_error = _backend_resolver()
        errors: list[str] = []
        for module_id, key_alias in SERVICE_BINDING_CANDIDATES[service]:
            try:
                context = resolver(
                    db,
                    org_id=org_id,
                    module_id=module_id,
                    key_alias=key_alias,
                )
            except (isolation_error, orchestration_error) as exc:  # type: ignore[misc]
                errors.append(f"{module_id}:{key_alias}:{exc}")
                continue
            context_key_type = str(
                getattr(context, "key_type", "") or ""
            ).strip().lower()
            required_key_types = SERVICE_KEY_TYPE_REQUIREMENTS.get(service)
            if required_key_types and context_key_type not in required_key_types:
                errors.append(
                    f"{module_id}:{key_alias}:wrong_key_type:{context_key_type or 'unknown'}"
                )
                continue
            raw_key = _raw_key_from_injection_context(context)
            if not raw_key:
                errors.append(f"{module_id}:{key_alias}:empty_key")
                continue
            return _SecretCacheEntry(
                value=raw_key,
                updated_at=datetime.now(UTC).isoformat(),
                module_id=str(context.module_id),
                key_alias=str(context.key_alias),
                key_id=str(context.key_id),
                url=str(getattr(context, "url", "") or "").strip() or None,
                name=str(getattr(context, "name", "") or "").strip() or None,
                key_type=str(getattr(context, "key_type", "") or "").strip() or None,
                provider=str(getattr(context, "provider", "") or "").strip() or None,
            )
        raise SecretNotFoundError(
            f"api_key_binding_not_found:{org_id}:{service}:{'|'.join(errors)}"
        )

    def _database_watch_snapshot(self) -> dict[tuple[str, str], str]:
        with self._session_scope() as db:
            if db is None:
                return {}
            try:
                from sqlalchemy import text
            except ImportError:
                return {}
            try:
                result = db.execute(
                    text(
                        """
                        SELECT
                            b.org_id,
                            b.module_id,
                            b.key_alias,
                            b.key_id,
                            CAST(b.updated_at AS TEXT) AS binding_updated_at,
                            CAST(k.updated_at AS TEXT) AS key_updated_at
                        FROM api_key_module_bindings b
                        JOIN api_key_records k ON k.key_id = b.key_id
                        WHERE b.status = 'active'
                          AND k.status = 'active'
                          AND k.org_id = b.org_id
                        """
                    )
                )
            except Exception:
                return {}
            rows = list(result.mappings().all())
        snapshot: dict[tuple[str, str], str] = {}
        for row in rows:
            module_alias = (str(row["module_id"]), str(row["key_alias"]))
            for service, candidates in SERVICE_BINDING_CANDIDATES.items():
                if module_alias not in candidates:
                    continue
                key = (str(row["org_id"]), service)
                signature = ":".join(
                    [
                        str(row["key_id"]),
                        str(row["binding_updated_at"]),
                        str(row["key_updated_at"]),
                    ]
                )
                snapshot.setdefault(key, signature)
        return snapshot


def _backend_resolver() -> tuple[Callable[..., Any], type[Exception], type[Exception]]:
    try:
        from backend.app.services.api_key_orchestration import (
            ApiKeyIsolationError,
            ApiKeyOrchestrationError,
            resolve_module_api_key_for_injection,
        )
    except ImportError:
        from app.services.api_key_orchestration import (  # type: ignore[no-redef]
            ApiKeyIsolationError,
            ApiKeyOrchestrationError,
            resolve_module_api_key_for_injection,
        )
    return resolve_module_api_key_for_injection, ApiKeyIsolationError, ApiKeyOrchestrationError


def _raw_key_from_injection_context(context: Any) -> str:
    query_value = getattr(context, "query_param_value", None)
    if isinstance(query_value, str) and query_value.strip():
        return query_value.strip()
    header_value = str(getattr(context, "header_value", "") or "").strip()
    if header_value.lower().startswith("bearer "):
        return header_value[7:].strip()
    return header_value
