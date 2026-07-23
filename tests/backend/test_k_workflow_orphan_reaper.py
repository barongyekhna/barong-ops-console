from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.modules.k_series.product_knowledge import workflow_engine
from backend.app.modules.k_series.product_knowledge.workflow_engine import (
    reap_orphan_running_execution,
)


class _FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True


class _FakeExecution:
    def __init__(self, *, status: str, updated_at: datetime | None) -> None:
        self.id = uuid4()
        self.status = status
        self.current_step = "ai_filter_claude_opus"
        self.updated_at = updated_at
        self.trace_json = [
            {"step": "ai_filter_claude_opus", "status": "running", "error": None}
        ]


def _boot_time(monkeypatch, when: datetime) -> None:
    monkeypatch.setattr(workflow_engine, "_process_tree_start_time", lambda: when)


def test_reaps_running_execution_last_touched_before_boot(monkeypatch) -> None:
    boot = datetime.now(UTC)
    _boot_time(monkeypatch, boot)
    execution = _FakeExecution(
        status="running",
        updated_at=boot - timedelta(minutes=5),
    )
    db = _FakeDb()

    assert reap_orphan_running_execution(db, execution) is True
    assert execution.status == "blocked"
    assert execution.trace_json[-1]["status"] == "failed"
    assert execution.trace_json[-1]["error"]["code"] == "ORPHANED_BY_RESTART"
    assert db.committed


def test_leaves_execution_updated_after_boot_alone(monkeypatch) -> None:
    boot = datetime.now(UTC) - timedelta(minutes=30)
    _boot_time(monkeypatch, boot)
    execution = _FakeExecution(
        status="running",
        updated_at=boot + timedelta(minutes=1),
    )
    db = _FakeDb()

    assert reap_orphan_running_execution(db, execution) is False
    assert execution.status == "running"
    assert not db.committed


def test_ignores_non_running_and_missing_executions(monkeypatch) -> None:
    _boot_time(monkeypatch, datetime.now(UTC))
    db = _FakeDb()

    blocked = _FakeExecution(
        status="blocked",
        updated_at=datetime.now(UTC) - timedelta(hours=1),
    )
    assert reap_orphan_running_execution(db, blocked) is False
    assert reap_orphan_running_execution(db, None) is False
    assert not db.committed


def test_naive_updated_at_treated_as_utc(monkeypatch) -> None:
    boot = datetime.now(UTC)
    _boot_time(monkeypatch, boot)
    execution = _FakeExecution(
        status="running",
        updated_at=(boot - timedelta(minutes=5)).replace(tzinfo=None),
    )
    db = _FakeDb()

    assert reap_orphan_running_execution(db, execution) is True
    assert execution.status == "blocked"


def test_gives_up_without_boot_time(monkeypatch) -> None:
    _boot_time(monkeypatch, None)
    execution = _FakeExecution(
        status="running",
        updated_at=datetime.now(UTC) - timedelta(hours=2),
    )
    db = _FakeDb()

    assert reap_orphan_running_execution(db, execution) is False
    assert execution.status == "running"
