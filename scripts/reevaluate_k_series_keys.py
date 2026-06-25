#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("BARONG_REPO_ROOT", Path.cwd())).resolve()
if not (REPO_ROOT / "backend").exists():
    REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select

from backend.app.db.session import managed_session
from backend.app.models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.services import api_key_orchestration
from backend.app.services.data_isolation import without_org_data_isolation
from backend.app.services.provider_config_service import upsert_provider_config

K_SERIES_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"
K_SERIES_MODULE_ID = "k.product_knowledge"
K_SERIES_PROVIDER_ALIASES = ("serp", "chatgpt", "claude_opus", "deepseek")
K_SERIES_PROVIDER_MARKERS = {
    "serp": ("serp", "serper"),
    "claude_opus": ("claude", "anthropic", "opus"),
    "deepseek": ("deepseek",),
    "chatgpt": ("chatgpt", "openai", "4sapi"),
}


def _new_binding_id() -> str:
    return f"akb_{secrets.token_hex(16)}"


def _infer_key_alias(key: ApiKeyRecord) -> str | None:
    metadata = key.metadata_json or {}
    haystack = " ".join(
        [
            key.name,
            key.url,
            str(metadata.get("provider") or ""),
            str(metadata.get("key_alias") or ""),
        ]
    ).lower()
    for alias, markers in K_SERIES_PROVIDER_MARKERS.items():
        if any(marker in haystack for marker in markers):
            return alias
    return None


def _fallback_reevaluate_k_series_api_keys(db) -> dict[str, object]:
    organization = db.scalar(
        select(OrganizationRecord).where(
            OrganizationRecord.org_name == K_SERIES_ORGANIZATION_NAME,
            OrganizationRecord.status != "deleted",
        )
    )
    if organization is None:
        raise RuntimeError("organization_not_found")

    keys = list(
        db.scalars(
            select(ApiKeyRecord)
            .where(ApiKeyRecord.status != "deleted")
            .order_by(ApiKeyRecord.key_id)
        )
    )
    activated: list[dict[str, str]] = []
    alias_counts = {alias: 0 for alias in K_SERIES_PROVIDER_ALIASES}
    for key in keys:
        alias = _infer_key_alias(key)
        if alias is None:
            continue
        key.org_id = organization.org_id
        key.status = "active"
        key.updated_by_user_id = "k_series_key_lifecycle_fix"
        key.metadata_json = {
            **(key.metadata_json or {}),
            "k_series_module_id": K_SERIES_MODULE_ID,
            "key_alias": alias,
            "runtime_state": "enabled",
        }
        db.add(key)

        binding = db.scalar(
            select(ApiKeyModuleBindingRecord).where(
                ApiKeyModuleBindingRecord.org_id == organization.org_id,
                ApiKeyModuleBindingRecord.module_id == K_SERIES_MODULE_ID,
                ApiKeyModuleBindingRecord.key_id == key.key_id,
            )
        )
        if binding is None:
            binding = ApiKeyModuleBindingRecord(
                binding_id=_new_binding_id(),
                org_id=organization.org_id,
                module_id=K_SERIES_MODULE_ID,
                key_id=key.key_id,
                key_alias=alias,
                status="active",
                created_by_user_id="k_series_key_lifecycle_fix",
                updated_by_user_id="k_series_key_lifecycle_fix",
            )
        else:
            binding.key_alias = alias
            binding.status = "active"
            binding.updated_by_user_id = "k_series_key_lifecycle_fix"
        db.add(binding)
        db.flush()
        upsert_provider_config(
            db,
            org_id=binding.org_id,
            module_id=binding.module_id,
            provider=alias,
            base_url=key.url,
            source_key_id=key.key_id,
            metadata={
                "source": "k_series_key_reevaluation",
                "key_name": key.name,
            },
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
    return {
        "activated": activated,
        "alias_counts": alias_counts,
        "module_id": K_SERIES_MODULE_ID,
        "org_id": organization.org_id,
        "organization": organization.org_name,
        "required_aliases_available": {
            alias: alias_counts.get(alias, 0) > 0
            for alias in K_SERIES_PROVIDER_ALIASES
        },
    }


def _reevaluate(db) -> dict[str, object]:
    service_func = getattr(
        api_key_orchestration,
        "reevaluate_k_series_api_keys",
        None,
    )
    if service_func is not None:
        return service_func(db, actor_user_id="k_series_key_lifecycle_fix")
    return _fallback_reevaluate_k_series_api_keys(db)


def main() -> None:
    with managed_session() as db:
        with without_org_data_isolation():
            result = _reevaluate(db)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
