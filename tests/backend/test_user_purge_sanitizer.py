"""用户管理 409 文案在生产环境不被消毒(范围卡死)。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_purge_conflict_message_survives_production_sanitizing() -> None:
    from types import SimpleNamespace

    from backend.app.main import _user_management_conflict_detail_for_production as f

    def req(path):
        return SimpleNamespace(url=SimpleNamespace(path=path))

    msg = "Disable the account first, then delete it."
    assert f(req("/api/app/users/131"), 409, msg) == msg
    assert f(req("/api/app/users/131"), 403, msg) is None
    assert f(req("/api/app/mfg/stock"), 409, msg) is None
    assert f(req("/api/app/users/131"), 409, {"x": 1}) is None
