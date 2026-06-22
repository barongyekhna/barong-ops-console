from __future__ import annotations

import base64
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
from ..models.organization import OrganizationRecord
from ..schemas.api_key_orchestration import (
    ApiKeyBindingCreateRequest,
    ApiKeyBindingRead,
    ApiKeyCreateRequest,
    ApiKeyRead,
    ApiKeyUpdateRequest,
)
from .module_registry import get_module_manifest


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


ENVELOPE_VERSION = "akv1"
NONCE_BYTES = 16
MAC_BYTES = 32


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


def _read_key(
    record: ApiKeyRecord,
    bindings: list[ApiKeyModuleBindingRecord] | None = None,
) -> ApiKeyRead:
    return ApiKeyRead(
        key_id=record.key_id,
        org_id=record.org_id,
        name=record.name,
        url=record.url,
        key_hash_prefix=record.key_hash_prefix,
        status=record.status,  # type: ignore[arg-type]
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
    return ApiKeyBindingRead(
        binding_id=binding.binding_id,
        org_id=binding.org_id,
        module_id=binding.module_id,
        key_id=binding.key_id,
        key_alias=binding.key_alias,
        key_name=key.name,
        key_url=key.url,
        status=binding.status,  # type: ignore[arg-type]
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


def _get_active_organization(db: Session, org_id: str) -> OrganizationRecord:
    organization = db.get(OrganizationRecord, org_id)
    if organization is None or organization.status == "deleted":
        raise ApiKeyOrchestrationError("organization_not_found")
    return organization


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
        metadata_json={"storage": "backend_envelope"},
    )
    db.add(record)
    db.flush()
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
    record.updated_by_user_id = actor_user_id
    db.add(record)
    db.flush()
    bindings = _active_bindings_for_keys(db, [record.key_id]).get(record.key_id, [])
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
    if get_module_manifest(payload.module_id) is None:
        raise ApiKeyOrchestrationError("module_not_registered")
    key = get_api_key_record(db, payload.key_id)
    if key is None or key.status != "active":
        raise ApiKeyOrchestrationError("api_key_not_active")
    if key.org_id != org_id:
        raise ApiKeyIsolationError("api_key_org_mismatch")

    existing = db.scalar(
        select(ApiKeyModuleBindingRecord).where(
            ApiKeyModuleBindingRecord.org_id == org_id,
            ApiKeyModuleBindingRecord.module_id == payload.module_id,
            ApiKeyModuleBindingRecord.key_id == payload.key_id,
        )
    )
    if existing is not None:
        existing.status = "active"
        existing.key_alias = payload.key_alias
        existing.updated_by_user_id = actor_user_id
        db.add(existing)
        db.flush()
        return _read_binding(existing, key)

    binding = ApiKeyModuleBindingRecord(
        binding_id=_new_binding_id(),
        org_id=org_id,
        module_id=payload.module_id,
        key_id=payload.key_id,
        key_alias=payload.key_alias,
        status="active",
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
    )
    db.add(binding)
    db.flush()
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
    secret_value = _decrypt_key_value(key.encrypted_key_value)
    key.last_used_at = datetime.now(UTC)
    db.add(key)
    db.flush()
    return ApiKeyInjectionContext(
        org_id=org_id,
        module_id=module_id,
        key_id=key.key_id,
        key_alias=binding.key_alias,
        name=key.name,
        url=key.url,
        header_name="Authorization",
        header_value=f"Bearer {secret_value}",
    )
