"""苏青禾运行时(2026-10-22 骨架,影子期):人设门、脑子解析、快照兜底、C19 指令、主动开口规矩、台账记名。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.models.organization import OrganizationRecord
from backend.app.modules.agent_series.suqinghe import brain, persona, snapshot, worker_main
from backend.app.modules.k_series.product_knowledge.constants import TARGET_ORGANIZATION_NAME
from backend.app.services import ai_provider_router as router_module
from backend.app.services.ai_provider_router import AIExecutionRouter, ProviderRequest
from backend.app.services.module_execution_gate import ModuleExecutionContext, ModuleExecutionKey

pytestmark = pytest.mark.unit

LA_NOON = datetime(2026, 10, 22, 19, 0, tzinfo=UTC)  # 洛杉矶 12:00
LA_NIGHT = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)  # 洛杉矶 00:00


# ---------------------------------------------------------------- 人设门


def test_enforce_style_strips_emoji_banned_phrases_and_caps_length() -> None:
    out = persona.enforce_style("亲爱的老板😊,作为一个AI我觉得" + "好" * 2000)
    assert "😊" not in out and "亲爱的" not in out and "作为一个AI" not in out
    assert len(out) <= persona.MAX_MESSAGE_CHARS
    assert out.endswith("…")


def test_system_prompt_carries_character_and_boundaries() -> None:
    prompt = persona.system_prompt("ctx-line")
    assert "女强人" in prompt and "大姐姐" in prompt and "老板" in prompt
    assert "影子期" in prompt and "ctx-line" in prompt
    assert "这个我来兜" in prompt


# ---------------------------------------------------------------- 脑子解析


def test_parse_plan_handles_fenced_json_and_caps_cards() -> None:
    cards = [
        {"dedupe_key_suffix": f"k{i}", "kind": "product_blocker", "title": f"卡{i}", "conclusion": "要老板定", "confidence": "high"}
        for i in range(8)
    ]
    import json

    raw = {"content": "```json\n" + json.dumps({"plan": "今天先清 P 闸门", "cards": cards}, ensure_ascii=False) + "\n```"}
    parsed = brain.parse_plan(raw)
    assert parsed is not None
    plan_text, parsed_cards = parsed
    assert plan_text == "今天先清 P 闸门"
    assert len(parsed_cards) == 5
    assert parsed_cards[0]["dedupe_key_suffix"] == "k0"


def test_parse_plan_drops_cards_missing_required_fields_and_bad_kind() -> None:
    parsed = brain.parse_plan({"plan": "p", "cards": [{"title": "无结论"}, {"dedupe_key_suffix": "a", "title": "t", "conclusion": "c", "kind": "weird", "confidence": "x"}]})
    assert parsed is not None
    _, cards = parsed
    assert len(cards) == 1 and cards[0]["kind"] == "other" and cards[0]["confidence"] == "medium"


def test_parse_plan_without_plan_text_is_none() -> None:
    assert brain.parse_plan({"content": "not json at all"}) is None
    assert brain.parse_plan({"plan": "", "cards": []}) is None


def test_parse_chat_clamps_mute_and_falls_back_to_raw_text() -> None:
    result = brain.parse_chat({"reply": "收到", "dictation": "以后先上减压玩具", "mute_days": 99})
    assert result is not None and result.mute_days == 30 and result.dictation == "以后先上减压玩具"
    raw = brain.parse_chat({"content": "好的老板"})
    assert raw is not None and raw.reply == "好的老板"


# ---------------------------------------------------------------- 快照兜底


def test_snapshot_one_failing_source_only_marks_that_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(db: Any) -> dict[str, Any]:
        raise RuntimeError("db down")

    fake_products = {"total": 2, "by_stage": {s: 0 for s in snapshot.STAGES} | {"published": 1, "blocked_gate": 1}, "woo_checked": True, "items": []}
    monkeypatch.setitem(snapshot.SOURCES, "products", lambda db: fake_products)
    monkeypatch.setitem(snapshot.SOURCES, "content", boom)
    monkeypatch.setitem(snapshot.SOURCES, "workers", lambda db: {"total": 3, "stale": ["r-w-worker"]})
    monkeypatch.setitem(snapshot.SOURCES, "keys", lambda db: {"counts": {}, "failing": []})
    monkeypatch.setitem(snapshot.SOURCES, "ai", lambda db: {"claude_usd_today": 0.1})
    monkeypatch.setitem(snapshot.SOURCES, "approvals", lambda db: {"pending": 0})
    monkeypatch.setattr(snapshot, "goals_section", lambda db, products: [{"id": 1, "text": "30 个品", "metric": {"metric": "published_products", "target": 30}, "current": 1}])
    db = SimpleNamespace(rollback=lambda: None)
    snap = snapshot.build_snapshot(db, now=LA_NOON)
    assert snap["content"] == {"error": "读不到"}
    assert snap["products"] is fake_products
    assert "已发布 1 个品,离 30 还差 29" in snap["headline"]
    assert "1 个卡在 P 闸门" in snap["headline"] and "1 个后台进程掉线" in snap["headline"]


def test_product_stage_rules() -> None:
    product = SimpleNamespace(marketing_copy_json={"x": 1})
    job = SimpleNamespace(external_product_id="3445", status="succeeded")
    assert snapshot.product_stage(product=product, workflow=None, gate=[], job=job, woo={3445: {"status": "publish"}}) == "published"
    assert snapshot.product_stage(product=product, workflow=None, gate=[], job=job, woo={3445: {"status": "draft"}}) == "uploaded_draft"
    assert snapshot.product_stage(product=product, workflow=None, gate=[], job=job, woo=None) == "uploaded_unknown"
    assert snapshot.product_stage(product=product, workflow=None, gate=["未绑定图片"], job=None, woo=None) == "blocked_gate"
    assert snapshot.product_stage(product=product, workflow=None, gate=[], job=None, woo=None) == "ready_to_upload"
    bare = SimpleNamespace(marketing_copy_json=None)
    assert snapshot.product_stage(product=bare, workflow=SimpleNamespace(status="running"), gate=None, job=None, woo=None) == "k_workflow"
    assert snapshot.product_stage(product=bare, workflow=None, gate=None, job=None, woo=None) == "k_draft"


# ---------------------------------------------------------------- C19 指令


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("批 #a3f9", ("approve", "a3f9", "")),
        ("批#A3F9。", ("approve", "a3f9", "")),
        ("同意 0042", ("approve", "0042", "")),
        ("驳 #a3f9 价格太低了", ("reject", "a3f9", "价格太低了")),
        ("驳回 #a3f9:先别上", ("reject", "a3f9", "先别上")),
        ("驳 #a3f9", ("reject", "a3f9", "")),
    ],
)
def test_parse_command(text: str, expected: tuple[str, str, str]) -> None:
    command = worker_main.parse_command(text)
    assert command is not None
    assert (command.decision, command.ref, command.reason) == expected


@pytest.mark.parametrize("text", ["今天怎么样", "批一下那个", "#a3f9 批", "批 #xyz1"])
def test_non_commands_are_not_parsed(text: str) -> None:
    assert worker_main.parse_command(text) is None


def test_decided_text_reports_first_channel_when_already_decided() -> None:
    card = SimpleNamespace(ref="a3f9", title="t", status="approved", decided_via="web")
    assert "已经批过了(网页)" in worker_main.decided_text(card, changed=False, decision="approve")


# ---------------------------------------------------------------- 主动开口规矩


def test_may_speak_rules() -> None:
    today = date(2026, 10, 22)
    assert worker_main.may_speak(now=LA_NOON, pending=2, last_spoke=None, muted_until=None, paused=False) is True
    assert worker_main.may_speak(now=LA_NOON, pending=0, last_spoke=None, muted_until=None, paused=False) is False
    assert worker_main.may_speak(now=LA_NIGHT, pending=2, last_spoke=None, muted_until=None, paused=False) is False
    assert worker_main.may_speak(now=LA_NOON, pending=2, last_spoke=today, muted_until=None, paused=False) is False
    assert worker_main.may_speak(now=LA_NOON, pending=2, last_spoke=None, muted_until=today, paused=False) is False
    assert worker_main.may_speak(now=LA_NOON, pending=2, last_spoke=None, muted_until=None, paused=True) is False


def test_should_run_morning_once_per_la_day_after_seven() -> None:
    seven_am = datetime(2026, 10, 22, 14, 5, tzinfo=UTC)  # 洛杉矶 07:05
    six_am = datetime(2026, 10, 22, 13, 5, tzinfo=UTC)
    assert worker_main.should_run_morning(now=seven_am, last_plan=None) is True
    assert worker_main.should_run_morning(now=six_am, last_plan=None) is False
    assert worker_main.should_run_morning(now=seven_am, last_plan=date(2026, 10, 22)) is False


# ---------------------------------------------------------------- 台账记在她名下

ORG_ID = "org_11111111111111111111111111111111"


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(OrganizationRecord(org_id=ORG_ID, org_name=TARGET_ORGANIZATION_NAME, org_type="store", owner_user_id="1", status="active", metadata_json={}))
    db.commit()
    return db


def test_usage_label_is_recorded_as_ledger_module(monkeypatch: pytest.MonkeyPatch) -> None:
    ledger: list[dict[str, Any]] = []

    def fake_post_json(*, request: ProviderRequest, timeout_seconds: float, deadline: float | None = None) -> dict[str, Any]:
        del request, timeout_seconds, deadline
        return {"content": [{"type": "text", "text": '{"ok": true}'}], "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 5}}

    monkeypatch.setattr(router_module, "_post_json", fake_post_json)
    monkeypatch.setattr(router_module, "emit_event", lambda **kwargs: None)
    monkeypatch.setattr(router_module, "claude_budget_exhausted", lambda: False)
    monkeypatch.setattr(router_module, "record_ai_usage", lambda **kwargs: ledger.append(kwargs))
    key = ModuleExecutionKey(step_name="anthropic", key_alias="anthropic", key_id="k1", name="a", url="https://api.anthropic.com", header_name="x-api-key", header_value="sk-ant")
    context = ModuleExecutionContext(org_id=ORG_ID, requested_module_id="k.product_knowledge", control_module_id="k.product_knowledge", keys={"anthropic": key})
    for label, expected in ((None, "k.product_knowledge"), ("suqinghe", "suqinghe")):
        AIExecutionRouter(_session(), max_attempts=1).execute(
            provider="fast",
            task_type="agent_chat",
            payload={"prompt": "x"},
            org=TARGET_ORGANIZATION_NAME,
            execution_context=context,
            usage_label=label,
        )
        assert ledger[-1]["module"] == expected


def test_morning_retry_is_capped_per_day() -> None:
    from datetime import UTC, datetime, timedelta

    from backend.app.modules.agent_series.suqinghe import worker_main as wm

    worker = wm.SuqingheWorker.__new__(wm.SuqingheWorker)
    worker._morning_day, worker._morning_attempts, worker._morning_last = None, 0, None
    t0 = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)  # 洛杉矶早上 8 点
    assert worker._morning_attempt_allowed(t0) is True
    assert worker._morning_attempt_allowed(t0 + timedelta(minutes=1)) is False
    assert worker._morning_attempt_allowed(t0 + timedelta(minutes=31)) is True
    assert worker._morning_attempt_allowed(t0 + timedelta(minutes=62)) is True
    assert worker._morning_attempt_allowed(t0 + timedelta(minutes=93)) is False
    assert worker._morning_attempt_allowed(t0 + timedelta(days=1)) is True


def test_keys_section_ignores_failing_keys_without_bindings(monkeypatch) -> None:
    from backend.app.modules.agent_series.suqinghe import snapshot
    from backend.app.modules.key_health import service as kh

    monkeypatch.setattr(
        kh,
        "key_health_summary",
        lambda db: {
            "counts": {},
            "items": [
                {"key_name": "old 4sapi", "status": "invalid", "reason_code": "x", "bindings": []},
                {"key_name": "image", "status": "invalid", "reason_code": "x", "bindings": [{"module_id": "i.image_system", "key_alias": "chatgpt"}]},
                {"key_name": "ok", "status": "healthy", "reason_code": "", "bindings": [{"module_id": "k", "key_alias": "deepseek"}]},
            ],
        },
    )
    out = snapshot.keys_section(None)
    assert [f["name"] for f in out["failing"]] == ["image"]
    assert out["failing"][0]["used_by"] == ["i.image_system"]
    assert out["failing_but_unused"] == 1
