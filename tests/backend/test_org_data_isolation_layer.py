from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import Integer, String, delete, select, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.models.base_mixins import OrgScopedMixin
from backend.app.models.organization import OrganizationRecord
from backend.app.schemas.data_isolation import (
    get_org_data_isolation_api_enforcement_strategy,
    get_org_data_isolation_attack_prevention_model,
    get_org_data_isolation_completion_status,
    get_org_data_isolation_injection_logic,
    get_org_data_isolation_integration_model,
    get_org_data_isolation_layer_design,
    get_org_data_isolation_query_interception_system,
    get_org_data_isolation_universal_compatibility,
    get_org_data_isolation_write_protection_rules,
)
from backend.app.schemas.organization import generate_org_id
from backend.app.services.data_isolation import (
    OrgDataIsolationCrossOrgError,
    OrgDataIsolationLayer,
    OrgDataIsolationManualSqlError,
    OrgDataIsolationUserContext,
    current_org_data_isolation_context,
    get_org_scoped_model_names,
    org_data_isolation_context,
)


class C18GScopedRecord(OrgScopedMixin, Base):
    __tablename__ = "c18g_scoped_records"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    record_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    payload: Mapped[str] = mapped_column(String(255), nullable=False)


def _org_record(org_id: str) -> OrganizationRecord:
    return OrganizationRecord(
        org_id=org_id,
        org_name=f"Org {org_id[-6:]}",
        org_type="store",
        owner_user_id="1",
        status="active",
        metadata_json={},
    )


@pytest.fixture(autouse=True)
def c18g_state() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    with SessionLocal() as db:
        db.execute(delete(C18GScopedRecord))
        db.execute(delete(OrganizationRecord))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(C18GScopedRecord))
        db.execute(delete(OrganizationRecord))
        db.commit()


def _context(org_id: str, *, role: str = "operator") -> OrgDataIsolationUserContext:
    return OrgDataIsolationUserContext(
        org_id=org_id,
        user_id="101",
        role=role,
        source="test",
        strict=True,
    )


def test_c18g_design_outputs_define_data_isolation_contract() -> None:
    design = get_org_data_isolation_layer_design()
    injection = get_org_data_isolation_injection_logic()
    interception = get_org_data_isolation_query_interception_system()
    api = get_org_data_isolation_api_enforcement_strategy()
    writes = get_org_data_isolation_write_protection_rules()
    attacks = get_org_data_isolation_attack_prevention_model()
    integration = get_org_data_isolation_integration_model()
    compatibility = get_org_data_isolation_universal_compatibility()
    completion = get_org_data_isolation_completion_status()

    assert design.partition_key == "org_id"
    assert design.all_data_requires_org_id is True
    assert design.all_queries_org_scoped is True
    assert design.cross_org_access_allowed is False
    assert design.owner_read_scope_bypass_allowed is True
    assert design.migration_executed is False
    assert injection.if_query_missing_org_id == "auto_inject_current_org_id"
    assert injection.if_query_contains_other_org_id == "override_with_current_org_id"
    assert interception.intercepts_select is True
    assert interception.intercepts_raw_sql is True
    assert api.frontend_body_org_id_allowed is False
    assert api.backend_overwrites_org_id is True
    assert writes.inserts_attach_org_id_automatically is True
    assert writes.organization_must_exist is True
    assert attacks.org_a_can_read_org_b is False
    assert attacks.manual_sql_without_org_filter_allowed is False
    assert integration.flow == (
        "Request",
        "C18F Permission Check",
        "C18G Org Data Isolation Layer",
        "Repository Query with org filter",
        "Database",
    )
    assert compatibility.module_name_hardcoding_allowed is False
    assert compatibility.detection_rule == (
        "any mapped model with an org_id column is protected"
    )
    assert completion.completion_status == "complete"
    assert completion.migration_executed is False
    assert "C18GScopedRecord" in get_org_scoped_model_names()


def test_c18g_auto_injects_org_filter_and_overrides_manual_cross_org_filter() -> None:
    org_a = generate_org_id()
    org_b = generate_org_id()
    with SessionLocal() as db:
        db.add_all([_org_record(org_a), _org_record(org_b)])
        db.add_all(
            [
                C18GScopedRecord(
                    org_id=org_a,
                    record_key="a_" + uuid4().hex,
                    payload="org-a",
                ),
                C18GScopedRecord(
                    org_id=org_b,
                    record_key="b_" + uuid4().hex,
                    payload="org-b",
                ),
            ]
        )
        db.commit()

    with SessionLocal() as db, org_data_isolation_context(_context(org_a)):
        all_records = list(
            db.scalars(select(C18GScopedRecord).order_by(C18GScopedRecord.id))
        )
        attempted_cross_org = list(
            db.scalars(
                select(C18GScopedRecord).where(C18GScopedRecord.org_id == org_b)
            )
        )

    assert [record.payload for record in all_records] == ["org-a"]
    assert attempted_cross_org == []


def test_c18g_owner_read_bypass_keeps_query_unrestricted() -> None:
    org_a = generate_org_id()
    org_b = generate_org_id()
    owner_context = _context(org_a, role="owner")

    with SessionLocal() as db:
        db.add_all([_org_record(org_a), _org_record(org_b)])
        db.add_all(
            [
                C18GScopedRecord(
                    org_id=org_a,
                    record_key="a_" + uuid4().hex,
                    payload="org-a",
                ),
                C18GScopedRecord(
                    org_id=org_b,
                    record_key="b_" + uuid4().hex,
                    payload="org-b",
                ),
            ]
        )
        db.commit()

    statement = select(C18GScopedRecord).order_by(C18GScopedRecord.payload)
    assert OrgDataIsolationLayer.apply_scope(statement, owner_context) is statement

    with SessionLocal() as db, org_data_isolation_context(owner_context):
        records = list(db.scalars(statement))

    assert [record.payload for record in records] == ["org-a", "org-b"]


def test_c18g_write_protection_attaches_org_id_and_rejects_cross_org_insert() -> None:
    org_a = generate_org_id()
    org_b = generate_org_id()

    with SessionLocal() as db:
        db.add_all([_org_record(org_a), _org_record(org_b)])
        db.commit()

    with SessionLocal() as db, org_data_isolation_context(_context(org_a)):
        record = C18GScopedRecord(record_key="auto_" + uuid4().hex, payload="auto")
        db.add(record)
        db.commit()
        db.refresh(record)
        assert record.org_id == org_a

    with pytest.raises(OrgDataIsolationCrossOrgError):
        with SessionLocal() as db, org_data_isolation_context(_context(org_a)):
            db.add(
                C18GScopedRecord(
                    org_id=org_b,
                    record_key="bad_" + uuid4().hex,
                    payload="bad",
                )
            )
            db.commit()


def test_c18g_blocks_raw_sql_without_org_filter_in_scoped_context() -> None:
    org_id = generate_org_id()
    with SessionLocal() as db:
        db.add(_org_record(org_id))
        db.commit()

    with SessionLocal() as db, org_data_isolation_context(_context(org_id)):
        assert current_org_data_isolation_context() is not None
        with pytest.raises(OrgDataIsolationManualSqlError):
            db.execute(text("SELECT * FROM c18g_scoped_records"))

        db.execute(
            text("SELECT * FROM c18g_scoped_records WHERE org_id = :org_id"),
            {"org_id": org_id},
        )
