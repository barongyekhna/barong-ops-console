"""分组池短缓存:TTL 命中/过期 + 写操作清空。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_groups_cache_roundtrip_and_bust(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.api.routes import ra

    ra._GROUPS_CACHE.clear()
    ra._groups_cache_put("k1", {"groups": {}, "counts": {"n": 1}})
    assert ra._groups_cache_get("k1") == {"groups": {}, "counts": {"n": 1}}

    # TTL 过期
    import time

    real = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real() + ra._GROUPS_CACHE_TTL_SECONDS + 1)
    assert ra._groups_cache_get("k1") is None
    monkeypatch.undo()

    ra._groups_cache_put("k2", {"groups": {}, "counts": {}})
    ra._groups_cache_bust()
    assert ra._groups_cache_get("k2") is None


def test_mutations_bust_the_cache() -> None:
    import inspect

    from backend.app.api.routes import ra

    for fn in (ra.ra_report_approve, ra.ra_report_reject):
        assert "_groups_cache_bust" in inspect.getsource(fn)
    assert "_groups_cache_put" in inspect.getsource(ra.ra_groups)
