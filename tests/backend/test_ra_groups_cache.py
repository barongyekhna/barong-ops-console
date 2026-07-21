"""分组池短缓存(文件级共享):读写命中 + 写操作清空。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_groups_cache_roundtrip_and_bust() -> None:
    from backend.app.api.routes import ra

    ra._groups_cache_bust()
    assert ra._groups_cache_get("k1") is None
    ra._groups_cache_put("k1", {"groups": {}, "counts": {"n": 1}})
    assert ra._groups_cache_get("k1") == {"groups": {}, "counts": {"n": 1}}
    ra._groups_cache_bust()
    assert ra._groups_cache_get("k1") is None


def test_groups_cache_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from backend.app.api.routes import ra

    ra._groups_cache_bust()
    ra._groups_cache_put("k2", {"groups": {}, "counts": {}})
    stale = ra._GROUPS_CACHE_TTL_SECONDS + 5
    path = ra._groups_cache_path("k2")
    old = os.path.getmtime(path) - stale
    os.utime(path, (old, old))
    assert ra._groups_cache_get("k2") is None


def test_mutations_bust_the_cache() -> None:
    import inspect

    from backend.app.api.routes import ra

    for fn in (ra.ra_report_approve, ra.ra_report_reject):
        assert "_groups_cache_bust" in inspect.getsource(fn)
    assert "_groups_cache_put" in inspect.getsource(ra.ra_groups)


def test_rereviewed_rejects_can_resurface() -> None:
    """复核章产品:路由 review 进待滑堆;无深挖证据也不被 continue 吞掉。"""
    import inspect

    from backend.app.api.routes import ra

    source = inspect.getsource(ra.ra_groups)
    assert "rereviewed" in source
    assert 'payload.get("has_deep_enrichment") and not rereviewed' in source
    # review 路由 → 待滑堆通道存在
    assert 'groups["review"].append({**item, "rereviewed": True})' in source
