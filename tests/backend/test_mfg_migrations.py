"""M 系列迁移与清单契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "backend" / "alembic" / "versions"


def test_permission_migration_covers_keys_and_cleans_dependents() -> None:
    source = (VERSIONS / "20260821_02_mfg_permissions.py").read_text(encoding="utf-8")
    for key in ("mfg.inventory.read", "mfg.inventory.manage"):
        assert key in source
    for table in ("role_default_permissions", "user_permission_assignments"):
        assert table in source


def test_mfg_migrations_are_in_manifest_order() -> None:
    manifest = json.loads((ROOT / "migration_manifest.json").read_text(encoding="utf-8"))
    order = manifest["migration_order"]
    for revision in (
        "20260821_01_mfg_inventory_tables",
        "20260821_02_mfg_permissions",
        "20260821_03_factory_org_type",
    ):
        assert revision in order


def test_factory_org_type_migration_is_idempotent_by_org_id() -> None:
    source = (VERSIONS / "20260821_03_factory_org_type.py").read_text(encoding="utf-8")
    assert "org_d7497212d213498cbf0513d75e486c20" in source
    assert "org_type=\"factory\"" in source


def test_shortage_detail_survives_production_sanitizing() -> None:
    """「桌腿缺 4 条」本身就是产品——被消毒成 Request conflict. 就白做了。口径卡死。"""
    from types import SimpleNamespace

    from backend.app.main import _mfg_inventory_detail_for_production as f

    def req(path: str):
        return SimpleNamespace(url=SimpleNamespace(path=path))

    row = {
        "item_id": "x", "code": "LEG", "name": "桌腿", "unit": "条", "mode": "per_unit",
        "bom_qty": "4", "required": "804", "available": "800", "short": "4",
    }
    ok = {"message": "物料不足", "shortages": [row]}
    assert f(req("/api/app/mfg/documents/production"), 409, ok) == ok
    assert f(req("/api/app/mfg/items"), 422, "编码 X 已存在") == "编码 X 已存在"
    assert f(req("/api/app/mfg/items/x"), 404, "物料/成品不存在") == "物料/成品不存在"
    # 别的路径蹭不到
    assert f(req("/api/app/k/products"), 409, ok) is None
    # 别的状态码照常消毒
    assert f(req("/api/app/mfg/stock"), 403, "x") is None
    assert f(req("/api/app/mfg/stock"), 503, "x") is None
    # 形状不对/夹带别的键不外泄
    assert f(req("/api/app/mfg/documents/production"), 409, {"message": "m", "shortages": [{"secret": "x"}]}) is None
    assert f(req("/api/app/mfg/documents/production"), 409, {"message": "m", "shortages": [row], "extra": 1}) is None
    assert f(req("/api/app/mfg/documents/production"), 409, {"message": "m", "shortages": [{**row, "short": 4}]}) is None
