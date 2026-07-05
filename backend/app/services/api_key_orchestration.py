from __future__ import annotations

import base64
import hmac
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.key_registry import (
    infer_key_type_from_record,
    key_type_allows_module,
    key_type_definition,
    list_key_type_definitions,
    metadata_for_key_type,
    normalize_key_type,
)
from ..models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
from ..models.organization import OrganizationRecord
from ..schemas.api_key_orchestration import (
    ApiKeyBindingCreateRequest,
    ApiKeyBindingRead,
    ApiKeyCreateRequest,
    ApiKeyRead,
    ApiKeyUpdateRequest,
)
from .module_registry import get_module_manifest_for_db
from .module_control_cache_service import refresh_module_control_center_cache_async
from .api_key_usage_tracker import record_api_key_usage
from .provider_config_service import (
    ProviderConfigError,
    provider_key_alias,
    upsert_provider_config,
)


class ApiKeyOrchestrationError(ValueError):
    pass


class ApiKeyIsolationError(ApiKeyOrchestrationError):
    pass


@dataclass(frozen=True)
class ApiKeyInjectionContext:
    org_id: str
    module_id: str
    key_id: str
    key_alias: str
    name: str
    url: str
    header_name: str
    header_value: str
    key_type: str = "custom"
    provider: str = "custom"
    auth_type: str = "api_key"
    adapter: str | None = None
    validation_endpoint: str | None = None
    query_param_name: str | None = None
    query_param_value: str | None = None


ENVELOPE_VERSION = "akv1"
NONCE_BYTES = 16
MAC_BYTES = 32
K_SERIES_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"
K_SERIES_MODULE_ID = "k.product_knowledge"
K_SERIES_PROVIDER_ALIASES = ("serp", "chatgpt", "claude_opus", "deepseek")
R_WAREHOUSE_MODULE_ID = "r.warehouse"
KEEPA_KEY_TYPE = "keepa"
KEEPA_KEY_ALIAS = "keepa"
KEEPA_VALIDATION_TIMEOUT_SECONDS = 5.0
K_SERIES_PROVIDER_MARKERS = {
    "serp": ("serp", "serper"),
    "claude_opus": ("claude", "anthropic", "opus"),
    "deepseek": ("deepseek",),
    "chatgpt": ("chatgpt", "openai", "4sapi"),
}


class KeepaAdapter:
    key_type = KEEPA_KEY_TYPE
    adapter_name = "KeepaAdapter"
    validation_endpoint = "https://api.keepa.com/token?key={key}"

    @classmethod
    def validation_url(cls, key_value: str) -> str:
        return cls.validation_endpoint.replace("{key}", quote(key_value, safe=""))

    @classmethod
    def validate_key(
        cls,
        key_value: str,
        *,
        timeout_seconds: float = KEEPA_VALIDATION_TIMEOUT_SECONDS,
    ) -> dict[str, object]:
        if not key_value.strip():
            return {
                "valid": False,
                "adapter": cls.adapter_name,
                "reason": "empty_key",
            }
        try:
            with httpx.Client(timeout=timeout_seconds, trust_env=False) as client:
                response = client.get(cls.validation_url(key_value))
            return {
                "valid": response.status_code == 200,
                "adapter": cls.adapter_name,
                "status_code": response.status_code,
            }
        except httpx.HTTPError as exc:
            return {
                "valid": False,
                "adapter": cls.adapter_name,
                "reason": exc.__class__.__name__,
            }


def _settings_secret_material() -> str:
    settings = get_settings()
    explicit = getattr(settings, "api_key_encryption_secret", None)
    if explicit is not None:
        value = explicit.get_secret_value()
        if value:
            return value
    if settings.owner_password is not None:
        value = settings.owner_password.get_secret_value()
        if value:
            return value
    return settings.database_url


def _encryption_key() -> bytes:
    return sha256(
        f"barong-api-key-orchestration-v1:{_settings_secret_material()}".encode(
            "utf-8"
        )
    ).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < length:
        output.extend(
            hmac.new(
                key,
                nonce + counter.to_bytes(4, "big"),
                sha256,
            ).digest()
        )
        counter += 1
    return bytes(output[:length])


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right, strict=True))


def _encrypt_key_value(value: str) -> str:
    plaintext = value.encode("utf-8")
    key = _encryption_key()
    nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = _xor(plaintext, _keystream(key, nonce, len(plaintext)))
    mac = hmac.new(key, b"mac" + nonce + ciphertext, sha256).digest()
    envelope = base64.urlsafe_b64encode(nonce + mac + ciphertext).decode("ascii")
    return f"{ENVELOPE_VERSION}.{envelope}"


def _decrypt_key_value(envelope: str) -> str:
    prefix, separator, payload = envelope.partition(".")
    if prefix != ENVELOPE_VERSION or separator != ".":
        raise ApiKeyIsolationError("api_key_envelope_invalid")
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ApiKeyIsolationError("api_key_envelope_invalid") from exc
    if len(decoded) <= NONCE_BYTES + MAC_BYTES:
        raise ApiKeyIsolationError("api_key_envelope_invalid")
    nonce = decoded[:NONCE_BYTES]
    mac = decoded[NONCE_BYTES : NONCE_BYTES + MAC_BYTES]
    ciphertext = decoded[NONCE_BYTES + MAC_BYTES :]
    key = _encryption_key()
    expected_mac = hmac.new(key, b"mac" + nonce + ciphertext, sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        raise ApiKeyIsolationError("api_key_envelope_tampered")
    plaintext = _xor(ciphertext, _keystream(key, nonce, len(ciphertext)))
    return plaintext.decode("utf-8")


def _fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _new_key_id() -> str:
    return f"key_{secrets.token_hex(16)}"


def _new_binding_id() -> str:
    return f"akb_{secrets.token_hex(16)}"


def _active_bindings_for_keys(
    db: Session,
    key_ids: list[str],
) -> dict[str, list[ApiKeyModuleBindingRecord]]:
    if not key_ids:
        return {}
    rows = list(
        db.scalars(
            select(ApiKeyModuleBindingRecord).where(
                ApiKeyModuleBindingRecord.key_id.in_(key_ids),
                ApiKeyModuleBindingRecord.status == "active",
            )
        )
    )
    grouped: dict[str, list[ApiKeyModuleBindingRecord]] = {}
    for row in rows:
        grouped.setdefault(row.key_id, []).append(row)
    return grouped


def _key_type_for_record(record: ApiKeyRecord) -> str:
    return infer_key_type_from_record(
        name=record.name,
        url=record.url,
        metadata=record.metadata_json,
    )


def _key_type_payload(record: ApiKeyRecord) -> dict[str, object]:
    definition = key_type_definition(_key_type_for_record(record))
    return {
        "key_type": definition["type"],
        "provider": definition["provider"],
        "auth_type": definition["auth_type"],
        "scope": list(definition["scope"]),
        "validation_endpoint": definition["validation_endpoint"],
        "adapter": definition["adapter"],
    }


def _normalize_payload_key_type(value: object) -> str:
    raw_value = getattr(value, "value", value)
    try:
        return normalize_key_type(str(raw_value) if raw_value is not None else None)
    except ValueError as exc:
        raise ApiKeyOrchestrationError(str(exc)) from exc


def _metadata_with_key_type(
    metadata: dict[str, object] | None,
    key_type: str,
) -> dict[str, object]:
    return {
        **(metadata or {}),
        **metadata_for_key_type(key_type),
    }


def _read_key(
    record: ApiKeyRecord,
    bindings: list[ApiKeyModuleBindingRecord] | None = None,
) -> ApiKeyRead:
    metadata = record.metadata_json or {}
    key_type_payload = _key_type_payload(record)
    runtime_state = "enabled" if metadata.get("runtime_state") == "enabled" else "disabled"
    return ApiKeyRead(
        key_id=record.key_id,
        org_id=record.org_id,
        name=record.name,
        url=record.url,
        key_type=key_type_payload["key_type"],  # type: ignore[arg-type]
        provider=str(key_type_payload["provider"]),
        auth_type=str(key_type_payload["auth_type"]),
        scope=list(key_type_payload["scope"]),  # type: ignore[arg-type]
        validation_endpoint=key_type_payload["validation_endpoint"],  # type: ignore[arg-type]
        key_hash_prefix=record.key_hash_prefix,
        status=record.status,  # type: ignore[arg-type]
        runtime_state=runtime_state,  # type: ignore[arg-type]
        assigned_module_ids=sorted(
            {binding.module_id for binding in bindings or [] if binding.status == "active"}
        ),
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_used_at=record.last_used_at,
    )


def _read_binding(
    binding: ApiKeyModuleBindingRecord,
    key: ApiKeyRecord,
) -> ApiKeyBindingRead:
    key_type_payload = _key_type_payload(key)
    return ApiKeyBindingRead(
        binding_id=binding.binding_id,
        org_id=binding.org_id,
        module_id=binding.module_id,
        key_id=binding.key_id,
        key_alias=binding.key_alias,
        key_name=key.name,
        key_url=key.url,
        key_type=key_type_payload["key_type"],  # type: ignore[arg-type]
        provider=str(key_type_payload["provider"]),
        status=binding.status,  # type: ignore[arg-type]
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


def _enable_key_runtime(
    key: ApiKeyRecord,
    *,
    actor_user_id: str,
) -> None:
    key.status = "active"
    key.updated_by_user_id = actor_user_id
    key.metadata_json = {
        **(key.metadata_json or {}),
        "runtime_state": "enabled",
    }


def _disable_key_runtime(
    key: ApiKeyRecord,
    *,
    actor_user_id: str,
) -> None:
    key.updated_by_user_id = actor_user_id
    key.metadata_json = {
        **(key.metadata_json or {}),
        "runtime_state": "disabled",
    }


def _get_active_organization(db: Session, org_id: str) -> OrganizationRecord:
    organization = db.get(OrganizationRecord, org_id)
    if organization is None or organization.status == "deleted":
        raise ApiKeyOrchestrationError("organization_not_found")
    return organization


def _sync_provider_config_for_binding(
    db: Session,
    *,
    binding: ApiKeyModuleBindingRecord,
    key: ApiKeyRecord,
    source: str,
) -> None:
    key_type_payload = _key_type_payload(key)
    try:
        upsert_provider_config(
            db,
            org_id=binding.org_id,
            module_id=binding.module_id,
            provider=binding.key_alias,
            base_url=key.url,
            source_key_id=key.key_id,
            metadata={
                "source": source,
                "key_name": key.name,
                "key_type": key_type_payload["key_type"],
                "provider": key_type_payload["provider"],
                "adapter": key_type_payload["adapter"],
            },
        )
    except ProviderConfigError:
        return


def _find_k_series_organization(db: Session) -> OrganizationRecord:
    organization = db.scalar(
        select(OrganizationRecord).where(
            OrganizationRecord.org_name == K_SERIES_ORGANIZATION_NAME,
            OrganizationRecord.status != "deleted",
        )
    )
    if organization is None:
        raise ApiKeyOrchestrationError("organization_not_found")
    return organization


def _infer_k_series_key_alias(key: ApiKeyRecord) -> str | None:
    haystack = " ".join(
        [
            key.name,
            key.url,
            str((key.metadata_json or {}).get("provider") or ""),
            str((key.metadata_json or {}).get("key_alias") or ""),
        ]
    ).lower()
    for alias, markers in K_SERIES_PROVIDER_MARKERS.items():
        if any(marker in haystack for marker in markers):
            return alias
    return None


def _active_binding_for_key_alias(
    db: Session,
    *,
    org_id: str,
    module_id: str,
    key_id: str,
) -> ApiKeyModuleBindingRecord | None:
    return db.scalar(
        select(ApiKeyModuleBindingRecord).where(
            ApiKeyModuleBindingRecord.org_id == org_id,
            ApiKeyModuleBindingRecord.module_id == module_id,
            ApiKeyModuleBindingRecord.key_id == key_id,
        )
    )


def reevaluate_k_series_api_keys(
    db: Session,
    *,
    actor_user_id: str = "system",
) -> dict[str, object]:
    organization = _find_k_series_organization(db)
    if get_module_manifest_for_db(db, K_SERIES_MODULE_ID) is None:
        raise ApiKeyOrchestrationError("module_not_registered")

    keys = list(
        db.scalars(
            select(ApiKeyRecord)
            .where(ApiKeyRecord.status != "deleted")
            .order_by(ApiKeyRecord.key_id)
        )
    )
    activated: list[dict[str, str]] = []
    alias_counts: dict[str, int] = {alias: 0 for alias in K_SERIES_PROVIDER_ALIASES}

    for key in keys:
        alias = _infer_k_series_key_alias(key)
        if alias is None:
            continue
        key.org_id = organization.org_id
        _enable_key_runtime(key, actor_user_id=actor_user_id)
        key.metadata_json = {
            **(key.metadata_json or {}),
            "k_series_module_id": K_SERIES_MODULE_ID,
            "key_alias": alias,
            "provider": provider_key_alias(alias),
            "runtime_state": "enabled",
        }
        db.add(key)

        binding = _active_binding_for_key_alias(
            db,
            org_id=organization.org_id,
            module_id=K_SERIES_MODULE_ID,
            key_id=key.key_id,
        )
        if binding is None:
            binding = ApiKeyModuleBindingRecord(
                binding_id=_new_binding_id(),
                org_id=organization.org_id,
                module_id=K_SERIES_MODULE_ID,
                key_id=key.key_id,
                key_alias=alias,
                status="active",
                created_by_user_id=actor_user_id,
                updated_by_user_id=actor_user_id,
            )
        else:
            binding.key_alias = alias
            binding.status = "active"
            binding.updated_by_user_id = actor_user_id
        db.add(binding)
        db.flush()
        _sync_provider_config_for_binding(
            db,
            binding=binding,
            key=key,
            source="k_series_key_reevaluation",
        )
        alias_counts[alias] += 1
        activated.append(
            {
                "key_alias": alias,
                "key_id": key.key_id,
                "org_id": organization.org_id,
                "module_id": K_SERIES_MODULE_ID,
                "status": key.status,
                "runtime_state": str(key.metadata_json.get("runtime_state")),
            }
        )

    refresh_module_control_center_cache_async(force=True)
    return {
        "organization": organization.org_name,
        "org_id": organization.org_id,
        "module_id": K_SERIES_MODULE_ID,
        "activated": activated,
        "alias_counts": alias_counts,
        "required_aliases_available": {
            alias: alias_counts.get(alias, 0) > 0
            for alias in K_SERIES_PROVIDER_ALIASES
        },
    }


def list_api_key_types() -> list[dict[str, object]]:
    return list_key_type_definitions()


def list_api_keys(db: Session) -> list[ApiKeyRead]:
    records = list(
        db.scalars(
            select(ApiKeyRecord)
            .where(ApiKeyRecord.status != "deleted")
            .order_by(ApiKeyRecord.org_id, ApiKeyRecord.name, ApiKeyRecord.key_id)
        )
    )
    bindings = _active_bindings_for_keys(db, [record.key_id for record in records])
    return [_read_key(record, bindings.get(record.key_id, [])) for record in records]


def create_api_key(
    db: Session,
    *,
    org_id: str,
    payload: ApiKeyCreateRequest,
    actor_user_id: str,
) -> ApiKeyRead:
    _get_active_organization(db, org_id)
    key_type = _normalize_payload_key_type(payload.key_type)
    key_value = payload.key_value.get_secret_value()
    fingerprint = _fingerprint(key_value)
    record = ApiKeyRecord(
        key_id=_new_key_id(),
        org_id=org_id,
        name=payload.name,
        url=payload.url,
        encrypted_key_value=_encrypt_key_value(key_value),
        key_fingerprint=fingerprint,
        key_hash_prefix=fingerprint[:12],
        status="active",
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
        metadata_json=_metadata_with_key_type(
            {
                "runtime_state": "enabled",
                "storage": "backend_envelope",
            },
            key_type,
        ),
    )
    db.add(record)
    db.flush()
    refresh_module_control_center_cache_async(force=True)
    return _read_key(record, [])


def get_api_key_record(db: Session, key_id: str) -> ApiKeyRecord | None:
    return db.scalar(select(ApiKeyRecord).where(ApiKeyRecord.key_id == key_id))


def update_api_key(
    db: Session,
    *,
    key_id: str,
    payload: ApiKeyUpdateRequest,
    actor_user_id: str,
) -> ApiKeyRead:
    record = get_api_key_record(db, key_id)
    if record is None or record.status == "deleted":
        raise ApiKeyOrchestrationError("api_key_not_found")
    if payload.name is not None:
        record.name = payload.name
    if payload.url is not None:
        record.url = payload.url
    if payload.key_type is not None:
        key_type = _normalize_payload_key_type(payload.key_type)
        record.metadata_json = _metadata_with_key_type(record.metadata_json, key_type)
    if payload.key_value is not None:
        key_value = payload.key_value.get_secret_value()
        fingerprint = _fingerprint(key_value)
        record.encrypted_key_value = _encrypt_key_value(key_value)
        record.key_fingerprint = fingerprint
        record.key_hash_prefix = fingerprint[:12]
    if payload.status is not None:
        if payload.status == "deleted":
            return delete_api_key(db, key_id=key_id, actor_user_id=actor_user_id)
        record.status = payload.status
        if payload.status == "active":
            _enable_key_runtime(record, actor_user_id=actor_user_id)
        else:
            _disable_key_runtime(record, actor_user_id=actor_user_id)
    record.updated_by_user_id = actor_user_id
    db.add(record)
    db.flush()
    bindings = _active_bindings_for_keys(db, [record.key_id]).get(record.key_id, [])
    for binding in bindings:
        _sync_provider_config_for_binding(
            db,
            binding=binding,
            key=record,
            source="api_key_update",
        )
    refresh_module_control_center_cache_async(force=True)
    return _read_key(record, bindings)


def delete_api_key(
    db: Session,
    *,
    key_id: str,
    actor_user_id: str,
) -> ApiKeyRead:
    record = get_api_key_record(db, key_id)
    if record is None or record.status == "deleted":
        raise ApiKeyOrchestrationError("api_key_not_found")
    now = datetime.now(UTC)
    record.status = "deleted"
    record.deleted_at = now
    record.updated_by_user_id = actor_user_id
    _disable_key_runtime(record, actor_user_id=actor_user_id)
    bindings = list(
        db.scalars(
            select(ApiKeyModuleBindingRecord).where(
                ApiKeyModuleBindingRecord.key_id == key_id,
                ApiKeyModuleBindingRecord.status == "active",
            )
        )
    )
    for binding in bindings:
        binding.status = "disabled"
        binding.updated_by_user_id = actor_user_id
        db.add(binding)
    db.add(record)
    db.flush()
    refresh_module_control_center_cache_async(force=True)
    return _read_key(record, [])


def list_api_key_bindings(db: Session) -> list[ApiKeyBindingRead]:
    rows = list(
        db.scalars(
            select(ApiKeyModuleBindingRecord)
            .where(ApiKeyModuleBindingRecord.status == "active")
            .order_by(
                ApiKeyModuleBindingRecord.org_id,
                ApiKeyModuleBindingRecord.module_id,
                ApiKeyModuleBindingRecord.key_alias,
            )
        )
    )
    key_lookup = {
        key.key_id: key
        for key in db.scalars(
            select(ApiKeyRecord).where(
                ApiKeyRecord.key_id.in_([row.key_id for row in rows])
            )
        )
    }
    return [
        _read_binding(row, key_lookup[row.key_id])
        for row in rows
        if row.key_id in key_lookup and key_lookup[row.key_id].status == "active"
    ]


def create_api_key_binding(
    db: Session,
    *,
    org_id: str,
    payload: ApiKeyBindingCreateRequest,
    actor_user_id: str,
) -> ApiKeyBindingRead:
    _get_active_organization(db, org_id)
    if get_module_manifest_for_db(db, payload.module_id) is None:
        raise ApiKeyOrchestrationError("module_not_registered")
    key = get_api_key_record(db, payload.key_id)
    if key is None or key.status == "deleted":
        raise ApiKeyOrchestrationError("api_key_not_found")
    if key.org_id != org_id:
        raise ApiKeyIsolationError("api_key_org_mismatch")
    key_type = _key_type_for_record(key)
    if not key_type_allows_module(key_type, payload.module_id):
        raise ApiKeyOrchestrationError("api_key_scope_mismatch")
    binding_alias = payload.key_alias
    if key_type == KEEPA_KEY_TYPE and payload.module_id == R_WAREHOUSE_MODULE_ID:
        if binding_alias in {"default", KEEPA_KEY_ALIAS}:
            binding_alias = KEEPA_KEY_ALIAS
        else:
            raise ApiKeyOrchestrationError("keepa_key_alias_required")
    _enable_key_runtime(key, actor_user_id=actor_user_id)
    db.add(key)

    existing = db.scalar(
        select(ApiKeyModuleBindingRecord).where(
            ApiKeyModuleBindingRecord.org_id == org_id,
            ApiKeyModuleBindingRecord.module_id == payload.module_id,
            ApiKeyModuleBindingRecord.key_id == payload.key_id,
        )
    )
    if existing is not None:
        existing.status = "active"
        existing.key_alias = binding_alias
        existing.updated_by_user_id = actor_user_id
        db.add(existing)
        db.flush()
        _sync_provider_config_for_binding(
            db,
            binding=existing,
            key=key,
            source="api_key_binding_update",
        )
        refresh_module_control_center_cache_async(force=True)
        return _read_binding(existing, key)

    binding = ApiKeyModuleBindingRecord(
        binding_id=_new_binding_id(),
        org_id=org_id,
        module_id=payload.module_id,
        key_id=payload.key_id,
        key_alias=binding_alias,
        status="active",
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
    )
    db.add(binding)
    db.flush()
    _sync_provider_config_for_binding(
        db,
        binding=binding,
        key=key,
        source="api_key_binding_create",
    )
    refresh_module_control_center_cache_async(force=True)
    return _read_binding(binding, key)


def delete_api_key_binding(
    db: Session,
    *,
    binding_id: str,
    actor_user_id: str,
) -> str:
    binding = db.scalar(
        select(ApiKeyModuleBindingRecord).where(
            ApiKeyModuleBindingRecord.binding_id == binding_id
        )
    )
    if binding is None or binding.status == "disabled":
        raise ApiKeyOrchestrationError("api_key_binding_not_found")
    binding.status = "disabled"
    binding.updated_by_user_id = actor_user_id
    db.add(binding)
    db.flush()
    refresh_module_control_center_cache_async(force=True)
    return binding.binding_id


def resolve_module_api_key_for_injection(
    db: Session,
    *,
    org_id: str,
    module_id: str,
    key_alias: str = "default",
) -> ApiKeyInjectionContext:
    normalized_alias = key_alias.strip().lower().replace(" ", "_") or "default"
    binding = db.scalar(
        select(ApiKeyModuleBindingRecord).where(
            ApiKeyModuleBindingRecord.org_id == org_id,
            ApiKeyModuleBindingRecord.module_id == module_id,
            ApiKeyModuleBindingRecord.key_alias == normalized_alias,
            ApiKeyModuleBindingRecord.status == "active",
        )
    )
    if binding is None:
        raise ApiKeyIsolationError("api_key_not_bound_to_module")
    key = get_api_key_record(db, binding.key_id)
    if key is None or key.status != "active":
        raise ApiKeyIsolationError("api_key_not_active")
    if key.org_id != org_id:
        raise ApiKeyIsolationError("api_key_org_mismatch")
    return _injection_context_from_binding(
        binding=binding,
        key=key,
        record_usage=True,
    )


def _injection_context_from_binding(
    *,
    binding: ApiKeyModuleBindingRecord,
    key: ApiKeyRecord,
    record_usage: bool,
) -> ApiKeyInjectionContext:
    secret_value = _decrypt_key_value(key.encrypted_key_value)
    if record_usage:
        record_api_key_usage(key.key_id)
    key_type_payload = _key_type_payload(key)
    key_type = str(key_type_payload["key_type"])
    if key_type == KEEPA_KEY_TYPE:
        header_name = "X-Keepa-Key"
        header_value = secret_value
        query_param_name = "key"
        query_param_value = secret_value
    else:
        header_name = "Authorization"
        header_value = f"Bearer {secret_value}"
        query_param_name = None
        query_param_value = None
    return ApiKeyInjectionContext(
        org_id=binding.org_id,
        module_id=binding.module_id,
        key_id=key.key_id,
        key_alias=binding.key_alias,
        name=key.name,
        url=key.url,
        header_name=header_name,
        header_value=header_value,
        key_type=key_type,
        provider=str(key_type_payload["provider"]),
        auth_type=str(key_type_payload["auth_type"]),
        adapter=key_type_payload["adapter"],  # type: ignore[arg-type]
        validation_endpoint=key_type_payload["validation_endpoint"],  # type: ignore[arg-type]
        query_param_name=query_param_name,
        query_param_value=query_param_value,
    )


def resolve_module_api_key_candidates_for_injection(
    db: Session,
    *,
    org_id: str,
    module_id: str,
    key_aliases: Sequence[str],
) -> list[ApiKeyInjectionContext]:
    normalized_aliases = [
        alias.strip().lower().replace(" ", "_") or "default"
        for alias in key_aliases
    ]
    alias_rank = {
        alias: index
        for index, alias in enumerate(dict.fromkeys(normalized_aliases))
    }
    if not alias_rank:
        raise ApiKeyIsolationError("api_key_not_bound_to_module")

    bindings = list(
        db.scalars(
            select(ApiKeyModuleBindingRecord).where(
                ApiKeyModuleBindingRecord.org_id == org_id,
                ApiKeyModuleBindingRecord.module_id == module_id,
                ApiKeyModuleBindingRecord.key_alias.in_(alias_rank.keys()),
                ApiKeyModuleBindingRecord.status == "active",
            )
        )
    )
    bindings.sort(
        key=lambda binding: (
            binding.created_at,
            alias_rank.get(binding.key_alias, len(alias_rank)),
            binding.binding_id,
        )
    )
    if not bindings:
        raise ApiKeyIsolationError("api_key_not_bound_to_module")

    keys = {
        key.key_id: key
        for key in db.scalars(
            select(ApiKeyRecord).where(
                ApiKeyRecord.key_id.in_([binding.key_id for binding in bindings])
            )
        )
    }
    contexts: list[ApiKeyInjectionContext] = []
    for binding in bindings:
        key = keys.get(binding.key_id)
        if key is None or key.status != "active":
            continue
        if key.org_id != org_id:
            raise ApiKeyIsolationError("api_key_org_mismatch")
        contexts.append(
            _injection_context_from_binding(
                binding=binding,
                key=key,
                record_usage=False,
            )
        )
    if not contexts:
        raise ApiKeyIsolationError("api_key_not_active")
    return contexts


def validate_api_key_value(
    *,
    key_type: str,
    key_value: str,
) -> dict[str, object]:
    normalized_key_type = normalize_key_type(key_type)
    if normalized_key_type == KEEPA_KEY_TYPE:
        return KeepaAdapter.validate_key(key_value)
    return {
        "valid": bool(key_value.strip()),
        "adapter": key_type_definition(normalized_key_type).get("adapter"),
        "reason": "local_non_empty_check",
    }


def validate_stored_api_key(
    db: Session,
    *,
    key_id: str,
    actor_user_id: str,
) -> dict[str, object]:
    key = get_api_key_record(db, key_id)
    if key is None or key.status == "deleted":
        raise ApiKeyOrchestrationError("api_key_not_found")
    key_type = _key_type_for_record(key)
    key_value = _decrypt_key_value(key.encrypted_key_value)
    result = validate_api_key_value(key_type=key_type, key_value=key_value)
    key.metadata_json = {
        **(key.metadata_json or {}),
        "validation_state": "valid" if result.get("valid") is True else "invalid",
        "validation_adapter": result.get("adapter"),
        "validation_checked_at": datetime.now(UTC).isoformat(),
    }
    key.updated_by_user_id = actor_user_id
    db.add(key)
    db.flush()
    return {
        "key_id": key.key_id,
        "key_type": key_type,
        **result,
    }
