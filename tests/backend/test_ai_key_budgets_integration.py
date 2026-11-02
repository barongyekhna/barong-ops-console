"""两把钥匙动态配额(11-02):真库上——迁移建了表和列;台账记 key_id;额度状态按表算;同模块绑第二把同类钥匙=替换旧绑定。integration。"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from backend.app.db.session import SessionLocal
from backend.app.models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.schemas.api_key_orchestration import ApiKeyBindingCreateRequest
from backend.app.services import ai_usage_ledger as ledger
from backend.app.services.api_key_orchestration import (
    _encrypt_key_value,
    _fingerprint,
    claude_keys_for_org,
    create_api_key_binding,
    resolve_module_api_key_for_injection,
)
from backend.app.services.data_isolation import without_org_data_isolation

pytestmark = pytest.mark.integration

MODULE = "k.product_knowledge"


def _org(db, org_id: str) -> None:
    db.add(OrganizationRecord(org_id=org_id, org_name=f"配额测试 {org_id[-6:]}", org_type="store", owner_user_id="1", status="active", metadata_json={}))


def _key(db, org_id: str, key_id: str, name: str) -> ApiKeyRecord:
    secret = f"sk-ant-test-{key_id[-8:]}"
    rec = ApiKeyRecord(
        key_id=key_id, org_id=org_id, name=name, url="https://api.anthropic.com",
        encrypted_key_value=_encrypt_key_value(secret), key_fingerprint=_fingerprint(secret), key_hash_prefix=secret[:8],
        status="active", created_by_user_id="1", updated_by_user_id="1", metadata_json={"key_type": "anthropic"},
    )
    db.add(rec)
    return rec


@pytest.fixture()
def world():
    org_id = f"org_{uuid4().hex}"
    k_old, k_new = f"key_{uuid4().hex}", f"key_{uuid4().hex}"
    with without_org_data_isolation(), SessionLocal() as db:
        _org(db, org_id)
        _key(db, org_id, k_old, "老钥匙(测试)")
        _key(db, org_id, k_new, "新钥匙(测试)")
        db.flush()
        db.execute(text("INSERT INTO ai_key_budgets (key_id, provider, monthly_usd, reset_day, reserve_pct, is_default, note) VALUES (:a, 'claude', 200, 18, 10, false, 't'), (:b, 'claude', 100, 11, 10, false, 't')"), {"a": k_old, "b": k_new})
        db.commit()
    yield {"org": org_id, "old": k_old, "new": k_new}
    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(text("DELETE FROM ai_usage_ledger WHERE key_id IN (:a, :b) OR module = 'budget_test'"), {"a": k_old, "b": k_new})
        db.execute(text("DELETE FROM ai_key_budgets WHERE key_id IN (:a, :b)"), {"a": k_old, "b": k_new})
        db.execute(text("DELETE FROM api_key_module_bindings WHERE org_id = :o"), {"o": org_id})
        db.execute(text("DELETE FROM api_key_records WHERE org_id = :o"), {"o": org_id})
        db.execute(text("DELETE FROM organizations WHERE org_id = :o"), {"o": org_id})
        db.commit()
    ledger.invalidate_budget_cache()


def test_migration_added_column_table_and_seed_rows():
    with SessionLocal() as db:
        cols = {r[0] for r in db.execute(text("select column_name from information_schema.columns where table_name='ai_usage_ledger'"))}
        assert "key_id" in cols
        seeded = db.execute(text("select key_id, monthly_usd, reset_day, is_default from ai_key_budgets where key_id like 'key_ed01de5e%' or key_id like 'key_aa93f82e%' order by monthly_usd desc")).all()
        assert [(float(r[1]), r[2], r[3]) for r in seeded] == [(200.0, 18, True), (100.0, 11, False)]


def test_ledger_records_key_and_overview_paces_each_key(world):
    ledger.record_ai_usage(provider="claude", model="claude-opus-5-5", module="budget_test", task="t", usage=ledger.AIUsage(input_tokens=1_000_000), key_id=world["new"])  # $4
    ledger.record_ai_usage(provider="claude", model="claude-haiku-5-5", module="budget_test", task="t", usage=ledger.AIUsage(input_tokens=1_000_000), key_id=world["old"])  # $0.10
    with SessionLocal() as db:
        rows = db.execute(text("select key_id, cost_usd from ai_usage_ledger where module='budget_test' order by cost_usd desc")).all()
    assert [(r[0], float(r[1])) for r in rows] == [(world["new"], 4.0), (world["old"], 0.1)]

    today = datetime.now(UTC).date()
    with without_org_data_isolation(), SessionLocal() as db:
        ov = ledger.claude_budget_overview(today=today, db=db, use_cache=False)
    assert ov is not None and ov["mode"] == "dynamic"
    by = {s["key_id"]: s for s in ov["keys"]}
    assert set(by) >= {world["old"], world["new"]}
    new, old = by[world["new"]], by[world["old"]]
    assert new["spent_today_usd"] == pytest.approx(4.0) and old["spent_today_usd"] == pytest.approx(0.1)
    start, end = ledger.cycle_bounds(11, today)
    assert new["cycle_start"] == start.isoformat() and new["cycle_end"] == end.isoformat() and new["days_left"] == (end - today).days
    # 当天可花 = (100×0.9 − 今天之前花的 0) ÷ 剩余天数;今天已花 4 → 余额少 4
    assert new["allowance_today_usd"] == pytest.approx(90 / new["days_left"], abs=1e-3)
    assert new["headroom_today_usd"] == pytest.approx(new["allowance_today_usd"] - 4.0, abs=1e-3)
    assert ov["total_spent_today_usd"] >= 4.1 and ov["exhausted"] is False
    assert ledger.pick_key([new, old], preferred=world["new"]) in (world["old"], world["new"])


def test_binding_second_claude_key_replaces_the_old_one_and_alternates_are_listed(world):
    org, k_old, k_new = world["org"], world["old"], world["new"]
    with without_org_data_isolation(), SessionLocal() as db:
        create_api_key_binding(db, org_id=org, payload=ApiKeyBindingCreateRequest(module_id=MODULE, key_id=k_old, key_alias="anthropic"), actor_user_id="test")
        db.commit()
        assert resolve_module_api_key_for_injection(db, org_id=org, module_id=MODULE, key_alias="anthropic").key_id == k_old
        # 绑第二把 → 老绑定自动停用,同一(组织,模块,别名)只剩一条生效,取到的是新钥匙
        create_api_key_binding(db, org_id=org, payload=ApiKeyBindingCreateRequest(module_id=MODULE, key_id=k_new, key_alias="anthropic"), actor_user_id="test")
        db.commit()
        rows = db.scalars(select(ApiKeyModuleBindingRecord).where(ApiKeyModuleBindingRecord.org_id == org, ApiKeyModuleBindingRecord.module_id == MODULE)).all()
        assert sorted((r.key_id, r.status) for r in rows) == sorted([(k_old, "disabled"), (k_new, "active")])
        assert resolve_module_api_key_for_injection(db, org_id=org, module_id=MODULE, key_alias="anthropic").key_id == k_new
        # 备选钥匙:这个组织里绑过模块的 Claude 钥匙——老的绑定已停用,所以只剩新的
        alts = claude_keys_for_org(db, org_id=org)
        assert [a.key_id for a in alts] == [k_new] and alts[0].header_name == "x-api-key" and alts[0].header_value.startswith("sk-ant-test-")
        # 把老钥匙再绑到另一个模块,它就回到备选里
        create_api_key_binding(db, org_id=org, payload=ApiKeyBindingCreateRequest(module_id="r.analysis", key_id=k_old, key_alias="anthropic"), actor_user_id="test")
        db.commit()
        assert sorted(a.key_id for a in claude_keys_for_org(db, org_id=org)) == sorted([k_old, k_new])
