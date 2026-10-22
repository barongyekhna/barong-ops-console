"""苏青禾办公室:纯函数(状态判定、夜班边界、指纹、记忆线索)。"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.app.modules.agent_series.suqinghe import cards, memory, office

pytestmark = pytest.mark.unit

LA = ZoneInfo("America/Los_Angeles")
ALIVE = {"stale": False, "last_success_at": "x", "silent_seconds": 10}


def _la(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=LA).astimezone(UTC)


NOON = _la(2026, 10, 22, 12)


def test_offline_when_no_heartbeat_or_stale_beats_everything() -> None:
    assert office.compute_state(beat=None, activity="thinking", activity_updated_at=NOON, pending=3, now=NOON) == "offline"
    stale = {**ALIVE, "stale": True}
    assert office.compute_state(beat=stale, activity="working", activity_updated_at=NOON, pending=0, now=_la(2026, 10, 22, 23)) == "offline"


def test_night_beats_thinking_and_raised() -> None:
    late = _la(2026, 10, 22, 23)
    assert office.compute_state(beat=ALIVE, activity="thinking", activity_updated_at=late, pending=2, now=late) == "night"


def test_thinking_only_when_fresh() -> None:
    fresh = NOON - timedelta(seconds=120)
    assert office.compute_state(beat=ALIVE, activity="thinking", activity_updated_at=fresh, pending=2, now=NOON) == "thinking"
    old = NOON - timedelta(seconds=121)
    assert office.compute_state(beat=ALIVE, activity="thinking", activity_updated_at=old, pending=2, now=NOON) == "raised"
    assert office.compute_state(beat=ALIVE, activity="thinking", activity_updated_at=None, pending=0, now=NOON) == "working"


def test_raised_then_working() -> None:
    assert office.compute_state(beat=ALIVE, activity="working", activity_updated_at=NOON, pending=1, now=NOON) == "raised"
    assert office.compute_state(beat=ALIVE, activity="working", activity_updated_at=NOON, pending=0, now=NOON) == "working"


@pytest.mark.parametrize(
    ("when", "night"),
    [
        (_la(2026, 10, 22, 21, 59), False),
        (_la(2026, 10, 22, 22, 0), True),
        (_la(2026, 10, 23, 7, 59), True),
        (_la(2026, 10, 23, 8, 0), False),
        # 夏令时(PDT,UTC-7)与冬令时(PST,UTC-8)都按洛杉矶本地钟点算。
        (datetime(2026, 7, 1, 5, 0, tzinfo=UTC), True),  # 6-30 22:00 PDT
        (datetime(2026, 7, 1, 4, 59, tzinfo=UTC), False),  # 21:59 PDT
        (datetime(2026, 12, 1, 6, 0, tzinfo=UTC), True),  # 11-30 22:00 PST
        (datetime(2026, 12, 1, 5, 59, tzinfo=UTC), False),  # 21:59 PST
    ],
)
def test_is_night_boundaries(when, night) -> None:
    assert office.is_night(when) is night


def test_fingerprint_is_stable_and_order_independent() -> None:
    a = cards.fingerprint({"b": 2, "a": [1, "x"]})
    assert a == cards.fingerprint({"a": [1, "x"], "b": 2})
    assert len(a) == 32
    assert a != cards.fingerprint({"a": [1, "x"], "b": 3})


def test_clues_extract_sku_woo_and_chinese() -> None:
    found = memory.clues("PSPE-001 的主图怎么样?woo 3445 还卡在草稿,潜水泵价格")
    assert "PSPE-001" in found
    assert "3445" in found
    assert "潜水" in found
    assert len(found) <= 12
    assert memory.clues("") == []
