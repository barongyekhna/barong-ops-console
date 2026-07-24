"""R-A 巡航开关(2026-07-23):默认暂停,标志位切换,读失败按暂停。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from r_system_v2.ra.runtime_flags import (
    ensure_flags_schema,
    is_cruise_paused,
    set_cruise_paused,
)

pytestmark = pytest.mark.unit


def _session():
    engine = create_engine("sqlite:///:memory:")
    return sessionmaker(bind=engine)()


def test_cruise_defaults_to_paused() -> None:
    db = _session()
    # 无记录时默认暂停(上线即停,主动权交用户)
    assert is_cruise_paused(db) is True


def test_cruise_toggle_roundtrip() -> None:
    db = _session()
    set_cruise_paused(db, False, actor="tester")
    assert is_cruise_paused(db) is False
    row = db.execute(
        text("SELECT updated_by FROM ra_runtime_flags WHERE flag='auto_cruise_paused'")
    ).scalar()
    assert row == "tester"
    set_cruise_paused(db, True, actor="tester")
    assert is_cruise_paused(db) is True
