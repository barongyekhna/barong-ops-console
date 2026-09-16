"""把 DeepSeek 钥匙绑到四家广州公司 × amz.ops(幂等、可逆)。

    python -m backend.app.modules.amz_series.bind_deepseek            # 演习:只打印计划
    python -m backend.app.modules.amz_series.bind_deepseek --execute  # 真绑
    python -m backend.app.modules.amz_series.bind_deepseek --undo --execute  # 撤掉本工具建的绑定与钥匙副本

为什么要复制钥匙记录:api_key_records 一把钥匙只属于一个组织(注入时 key.org_id 必须等于绑定的 org_id),
而 A 系列的密钥按四家广州组织各自绑(家规)。所以每家一条记录,密文原样复制(同一把加密主钥),
metadata 打上 ``source=amz_bind_deepseek`` 与 ``copied_from`` 以便撤销时只动本工具建的东西。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.session import SessionLocal
from ...models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
from ...schemas.api_key_orchestration import ApiKeyBindingCreateRequest
from ...services.api_key_orchestration import _new_key_id, create_api_key_binding, delete_api_key_binding
from ...services.data_isolation import without_org_data_isolation
from ...services.provider_config_service import provider_key_alias
from .catalog import COMPANIES, OWNER_USER_ID
from .constants import MODULE_KEY

SOURCE_MARK = "amz_bind_deepseek"
SOURCE_MODULE = "k.product_knowledge"
DEEPSEEK_ALIAS = provider_key_alias("deepseek")


def find_source_key(db: Session, *, key_id: str | None) -> ApiKeyRecord:
    if key_id:
        record = db.scalar(select(ApiKeyRecord).where(ApiKeyRecord.key_id == key_id, ApiKeyRecord.status == "active"))
        if record is None:
            raise SystemExit(f"源钥匙 {key_id} 不存在或不是 active")
        return record
    binding = db.scalar(
        select(ApiKeyModuleBindingRecord)
        .where(
            ApiKeyModuleBindingRecord.module_id == SOURCE_MODULE,
            ApiKeyModuleBindingRecord.key_alias == DEEPSEEK_ALIAS,
            ApiKeyModuleBindingRecord.status == "active",
        )
        .order_by(ApiKeyModuleBindingRecord.created_at)
    )
    if binding is None:
        raise SystemExit(f"找不到 {SOURCE_MODULE} 的 DeepSeek 绑定,用 --source-key-id 指定")
    record = db.scalar(select(ApiKeyRecord).where(ApiKeyRecord.key_id == binding.key_id))
    if record is None or record.status != "active":
        raise SystemExit("源 DeepSeek 钥匙不是 active")
    return record


def existing_binding(db: Session, *, org_id: str) -> ApiKeyModuleBindingRecord | None:
    return db.scalar(
        select(ApiKeyModuleBindingRecord).where(
            ApiKeyModuleBindingRecord.org_id == org_id,
            ApiKeyModuleBindingRecord.module_id == MODULE_KEY,
            ApiKeyModuleBindingRecord.key_alias == DEEPSEEK_ALIAS,
            ApiKeyModuleBindingRecord.status == "active",
        )
    )


def copy_key_into_org(db: Session, *, source: ApiKeyRecord, org_id: str) -> ApiKeyRecord:
    existing = db.scalar(
        select(ApiKeyRecord).where(
            ApiKeyRecord.org_id == org_id,
            ApiKeyRecord.key_fingerprint == source.key_fingerprint,
            ApiKeyRecord.status == "active",
        )
    )
    if existing is not None:
        return existing
    metadata = dict(source.metadata_json or {})
    metadata.update({"source": SOURCE_MARK, "copied_from": source.key_id})
    record = ApiKeyRecord(
        key_id=_new_key_id(),
        org_id=org_id,
        name=source.name,
        url=source.url,
        encrypted_key_value=source.encrypted_key_value,
        key_fingerprint=source.key_fingerprint,
        key_hash_prefix=source.key_hash_prefix,
        status="active",
        created_by_user_id=str(OWNER_USER_ID),
        updated_by_user_id=str(OWNER_USER_ID),
        metadata_json=metadata,
    )
    db.add(record)
    db.flush()
    return record


def plan(db: Session, *, source_key_id: str | None) -> list[dict[str, Any]]:
    source = find_source_key(db, key_id=source_key_id)
    rows: list[dict[str, Any]] = []
    for company in COMPANIES:
        binding = existing_binding(db, org_id=company.org_id)
        rows.append(
            {
                "company": company.short_name,
                "org_id": company.org_id,
                "source_key_id": source.key_id,
                "action": "skip(已绑)" if binding is not None else "copy_key+bind",
                "binding_id": binding.binding_id if binding is not None else None,
            }
        )
    return rows


def apply(db: Session, *, source_key_id: str | None) -> list[dict[str, Any]]:
    source = find_source_key(db, key_id=source_key_id)
    out: list[dict[str, Any]] = []
    for company in COMPANIES:
        if existing_binding(db, org_id=company.org_id) is not None:
            out.append({"company": company.short_name, "outcome": "skipped"})
            continue
        key = copy_key_into_org(db, source=source, org_id=company.org_id)
        binding = create_api_key_binding(
            db,
            org_id=company.org_id,
            payload=ApiKeyBindingCreateRequest(module_id=MODULE_KEY, key_id=key.key_id, key_alias=DEEPSEEK_ALIAS),
            actor_user_id=str(OWNER_USER_ID),
        )
        out.append({"company": company.short_name, "outcome": "bound", "key_id": key.key_id, "binding_id": binding.binding_id})
    return out


def undo(db: Session) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for company in COMPANIES:
        binding = existing_binding(db, org_id=company.org_id)
        if binding is not None:
            delete_api_key_binding(db, binding_id=binding.binding_id, actor_user_id=str(OWNER_USER_ID))
        copies = list(
            db.scalars(
                select(ApiKeyRecord).where(ApiKeyRecord.org_id == company.org_id, ApiKeyRecord.status == "active")
            )
        )
        removed = 0
        for record in copies:
            if (record.metadata_json or {}).get("source") == SOURCE_MARK:
                record.status = "deleted"
                db.add(record)
                removed += 1
        db.flush()
        out.append({"company": company.short_name, "binding_disabled": binding is not None, "keys_deleted": removed})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true", help="真的写库;默认只打印计划")
    parser.add_argument("--undo", action="store_true", help="撤掉本工具建的绑定与钥匙副本")
    parser.add_argument("--source-key-id", default=None)
    args = parser.parse_args(argv)
    with without_org_data_isolation(), SessionLocal() as db:
        if args.undo:
            if not args.execute:
                print(json.dumps({"undo": "dry-run", "would_touch": [c.short_name for c in COMPANIES]}, ensure_ascii=False))
                return 0
            result = undo(db)
            db.commit()
            print(json.dumps({"undo": result}, ensure_ascii=False))
            return 0
        if not args.execute:
            print(json.dumps({"plan": plan(db, source_key_id=args.source_key_id)}, ensure_ascii=False))
            return 0
        result = apply(db, source_key_id=args.source_key_id)
        db.commit()
        print(json.dumps({"applied": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
