"""两把 Claude 钥匙按动态配额分(11-02 老板拍板):周期、当天可花、挑钥匙、路由切钥匙、苏青禾按比例。unit,不连库。"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from backend.app.services import ai_provider_router as router_module
from backend.app.services import ai_usage_ledger as ledger
from backend.app.services.ai_provider_router import AIExecutionRouter
from backend.app.services.module_execution_gate import ModuleExecutionKey
from tests.backend.test_ai_role_layer import ANTHROPIC_KEY, ANTHROPIC_OK, DEEPSEEK_OK, MODULE_ID, _context, _key, _session, harness  # noqa: F401

pytestmark = pytest.mark.unit

OLD = ledger.KeyBudget("key_old", "老钥匙", 200.0, 18, 10, True)
NEW = ledger.KeyBudget("key_new", "新钥匙", 100.0, 11, 10, False)


def test_cycle_bounds_follow_the_reset_day() -> None:
    assert ledger.cycle_bounds(18, date(2026, 11, 2)) == (date(2026, 10, 18), date(2026, 11, 18))
    assert ledger.cycle_bounds(11, date(2026, 11, 2)) == (date(2026, 10, 11), date(2026, 11, 11))
    assert ledger.cycle_bounds(11, date(2026, 11, 11)) == (date(2026, 11, 11), date(2026, 12, 11))  # 重置日当天算新一期
    assert ledger.cycle_bounds(18, date(2026, 12, 20)) == (date(2026, 12, 18), date(2027, 1, 18))  # 跨年
    assert ledger.cycle_bounds(28, date(2026, 3, 1)) == (date(2026, 2, 28), date(2026, 3, 28))  # 2 月


def test_allowance_spreads_what_is_left_over_the_days_left() -> None:
    # $100,留 10%,本期前面一分没花,还剩 8 天 → 每天 11.25
    assert ledger.allowance_today(monthly_usd=100, reserve_pct=10, spent_before_today=0, days_left=8) == pytest.approx(11.25)
    # 前面花多了,后面自动收紧;花光了就是 0,不是负数
    assert ledger.allowance_today(monthly_usd=100, reserve_pct=10, spent_before_today=80, days_left=8) == pytest.approx(1.25)
    assert ledger.allowance_today(monthly_usd=100, reserve_pct=10, spent_before_today=95, days_left=8) == 0.0
    # 最后一天把剩的全给出去
    assert ledger.allowance_today(monthly_usd=100, reserve_pct=0, spent_before_today=70, days_left=1) == pytest.approx(30)


def test_key_status_headroom_remaining_and_idle_warning() -> None:
    s = ledger.key_status(NEW, spent_cycle=3.5, spent_today=2.0, today=date(2026, 11, 2), avg_daily_recent=1.0)
    assert s["days_left"] == 9 and s["cycle_end"] == "2026-11-11"
    # 到昨天为止花了 1.5 → (90−1.5)/9 = 9.83;今天已花 2 → 剩 7.83
    assert s["allowance_today_usd"] == pytest.approx(9.8333, abs=1e-3)
    assert s["headroom_today_usd"] == pytest.approx(7.8333, abs=1e-3)
    assert s["remaining_usd"] == 96.5 and s["projected_leftover_usd"] == pytest.approx(87.5)
    assert s["idle_warning"] is False  # 还有 9 天,不到提醒期
    late = ledger.key_status(NEW, spent_cycle=20.0, spent_today=0.0, today=date(2026, 11, 8), avg_daily_recent=2.0)
    assert late["days_left"] == 3 and late["idle_warning"] is True  # 3 天内还剩 80% → 要浪费了
    spent_out = ledger.key_status(NEW, spent_cycle=96.0, spent_today=0.0, today=date(2026, 11, 8))
    assert spent_out["idle_warning"] is False and spent_out["allowance_today_usd"] == 0.0


def test_pick_key_prefers_more_headroom_and_bound_key_on_ties() -> None:
    a = {"key_id": "key_old", "headroom_today_usd": 3.0}
    b = {"key_id": "key_new", "headroom_today_usd": 9.0}
    assert ledger.pick_key([a, b], preferred="key_old") == "key_new"
    assert ledger.pick_key([a, {**b, "headroom_today_usd": 3.0}], preferred="key_old") == "key_old"
    assert ledger.pick_key([{**a, "headroom_today_usd": 0.0}, {**b, "headroom_today_usd": -1}], preferred="key_old") is None
    assert ledger.pick_key([], preferred="key_old") is None


def _dynamic_overview(headrooms: dict[str, float]) -> dict[str, Any]:
    keys = [{"key_id": k, "name": k, "headroom_today_usd": h, "allowance_today_usd": max(h, 0) + 1, "spent_today_usd": 1.0} for k, h in headrooms.items()]
    return {"mode": "dynamic", "keys": keys, "total_spent_today_usd": 2.0, "total_allowance_today_usd": sum(k["allowance_today_usd"] for k in keys), "exhausted": ledger.pick_key(keys) is None, "idle_warnings": []}


def test_pick_claude_key_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "claude_budget_overview", lambda **kw: _dynamic_overview({"key_old": 0.0, "key_new": 4.0}))
    assert ledger.pick_claude_key(["key_old", "key_new"], preferred="key_old") == "key_new"
    assert ledger.pick_claude_key(["key_old"], preferred="key_old") is None  # 候选里只有用完的那把
    assert ledger.pick_claude_key(["key_old", "key_ghost"], preferred="key_old") is None  # 没登记额度的钥匙不参加
    assert ledger.claude_budget_exhausted() is False
    monkeypatch.setattr(ledger, "claude_budget_overview", lambda **kw: _dynamic_overview({"key_old": 0.0, "key_new": 0.0}))
    assert ledger.claude_budget_exhausted() is True and ledger.pick_claude_key(["key_old", "key_new"], "key_old") is None
    # legacy(表里没预算行):没用完就用绑的那把
    monkeypatch.setattr(ledger, "claude_budget_overview", lambda **kw: {"mode": "legacy", "keys": [], "exhausted": False})
    monkeypatch.setattr(ledger, "_legacy_claude_budget_exhausted", lambda: False)
    assert ledger.pick_claude_key(["key_old", "key_new"], preferred="key_old") == "key_old"
    monkeypatch.setattr(ledger, "_legacy_claude_budget_exhausted", lambda: True)
    assert ledger.pick_claude_key(["key_old"], preferred="key_old") is None and ledger.claude_budget_exhausted() is True
    # 读不到 → 按用完
    monkeypatch.setattr(ledger, "claude_budget_overview", lambda **kw: None)
    assert ledger.claude_budget_exhausted() is True and ledger.pick_claude_key(["key_old"], "key_old") is None


class _Alt:
    def __init__(self, key_id: str) -> None:
        self.key_id, self.name, self.url, self.header_name, self.header_value = key_id, "新钥匙", "https://api.anthropic.com", "x-api-key", "sk-ant-new"


def test_router_switches_to_the_key_with_headroom_and_ledgers_it(harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    harness["responses"] = [ANTHROPIC_OK]
    monkeypatch.setattr(router_module, "claude_keys_for_org", lambda db, *, org_id: [_Alt("key_new"), _Alt(ANTHROPIC_KEY.key_id)])
    monkeypatch.setattr(router_module, "pick_claude_key", lambda ids, preferred=None: "key_new" if "key_new" in ids else None)
    result = AIExecutionRouter(_session(), max_attempts=1).execute(
        provider="judge", task_type="agent_chat", payload={"messages": [{"role": "user", "content": "hi"}]},
        org="涌龙麟（深圳）国际贸易有限公司", module_id=MODULE_ID, execution_context=_context(ANTHROPIC_KEY), usage_label="suqinghe",
    )
    assert result.get("_ai_degraded") is None
    sent = harness["requests"][-1]
    assert sent.headers["x-api-key"] == "sk-ant-new"  # 真用了另一把
    assert harness["ledger"][-1]["key_id"] == "key_new" and harness["ledger"][-1]["module"] == "suqinghe"


def test_router_keeps_bound_key_when_it_has_headroom(harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    harness["responses"] = [ANTHROPIC_OK]
    monkeypatch.setattr(router_module, "claude_keys_for_org", lambda db, *, org_id: [_Alt("key_new")])
    monkeypatch.setattr(router_module, "pick_claude_key", lambda ids, preferred=None: preferred)
    AIExecutionRouter(_session(), max_attempts=1).execute(
        provider="judge", task_type="agent_chat", payload={"messages": [{"role": "user", "content": "hi"}]},
        org="涌龙麟（深圳）国际贸易有限公司", module_id=MODULE_ID, execution_context=_context(ANTHROPIC_KEY),
    )
    assert harness["requests"][-1].headers["x-api-key"] == "sk-ant-secret"
    assert harness["ledger"][-1]["key_id"] == ANTHROPIC_KEY.key_id


def test_router_degrades_only_when_every_key_is_out(harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    harness["responses"] = [DEEPSEEK_OK]
    harness["budget_exhausted"] = True  # 总闸:两把都没剩
    monkeypatch.setattr(router_module, "claude_keys_for_org", lambda db, *, org_id: [_Alt("key_new")])
    monkeypatch.setattr(router_module, "pick_claude_key", lambda ids, preferred=None: None)
    result = AIExecutionRouter(_session(), max_attempts=1).execute(
        provider="judge", task_type="agent_chat", payload={"messages": [{"role": "user", "content": "hi"}]},
        org="涌龙麟（深圳）国际贸易有限公司", module_id=MODULE_ID, execution_context=_context(ANTHROPIC_KEY),
    )
    assert result.get("_ai_degraded") is True and harness["ledger"][-1]["degraded"] is True
    assert harness["ledger"][-1]["key_id"] == "key_deepseek"


def test_router_alternate_lookup_failure_falls_back_to_bound_key(harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    harness["responses"] = [ANTHROPIC_OK]

    def boom(db, *, org_id):
        raise RuntimeError("table missing")

    monkeypatch.setattr(router_module, "claude_keys_for_org", boom)
    monkeypatch.setattr(router_module, "pick_claude_key", lambda ids, preferred=None: preferred)
    AIExecutionRouter(_session(), max_attempts=1).execute(
        provider="judge", task_type="agent_chat", payload={"messages": [{"role": "user", "content": "hi"}]},
        org="涌龙麟（深圳）国际贸易有限公司", module_id=MODULE_ID, execution_context=_context(ANTHROPIC_KEY),
    )
    assert harness["requests"][-1].headers["x-api-key"] == "sk-ant-secret"


def test_suqinghe_budget_is_a_share_of_the_total_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.modules.agent_series.suqinghe import constants

    monkeypatch.setattr(ledger, "claude_budget_overview", lambda **kw: _dynamic_overview({"key_old": 6.0, "key_new": 10.0}))
    monkeypatch.delenv("SQH_CLAUDE_SHARE_PCT", raising=False)
    assert constants.daily_claude_budget_usd() == pytest.approx(round((7.0 + 11.0) * 0.30, 2))
    monkeypatch.setenv("SQH_CLAUDE_SHARE_PCT", "50")
    assert constants.daily_claude_budget_usd() == pytest.approx(9.0)
    # 没登记额度 / 读不到 → 退回 $2 保底
    monkeypatch.setattr(ledger, "claude_budget_overview", lambda **kw: {"mode": "legacy", "keys": [], "total_allowance_today_usd": 6.4})
    assert constants.daily_claude_budget_usd() == 2.0
    monkeypatch.setattr(ledger, "claude_budget_overview", lambda **kw: None)
    assert constants.daily_claude_budget_usd() == 2.0


def test_snapshot_ai_section_and_budget_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.modules.agent_series.suqinghe import brain, snapshot

    ov = _dynamic_overview({"key_old": 1.0, "key_new": 2.0})
    ov["keys"][1].update({"idle_warning": True, "remaining_usd": 60.0, "days_left": 3})
    ov["idle_warnings"] = [{"key_id": "key_new", "name": "新钥匙", "remaining_usd": 60.0, "days_left": 3}]
    monkeypatch.setattr(ledger, "claude_budget_overview", lambda **kw: ov)
    section = snapshot.ai_section(None)
    assert section["claude_daily_budget_usd"] == ov["total_allowance_today_usd"] and section["mode"] == "dynamic" and len(section["keys"]) == 2
    live, readable = brain.issues_in({"ai": section})
    assert "budget" in readable and live == {"budget:key_new": {"name": "新钥匙"}}
    monkeypatch.setattr(ledger, "claude_budget_overview", lambda **kw: None)
    assert "error" in snapshot.ai_section(None)


def test_router_keeps_bound_key_when_picker_cannot_rank(harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    harness["responses"] = [ANTHROPIC_OK]
    monkeypatch.setattr(router_module, "claude_keys_for_org", lambda db, *, org_id: [])
    monkeypatch.setattr(router_module, "pick_claude_key", lambda ids, preferred=None: None)
    result = AIExecutionRouter(_session(), max_attempts=1).execute(
        provider="judge", task_type="agent_chat", payload={"messages": [{"role": "user", "content": "hi"}]},
        org="涌龙麟（深圳）国际贸易有限公司", module_id=MODULE_ID, execution_context=_context(ANTHROPIC_KEY),
    )
    assert result.get("_ai_degraded") is None and harness["requests"][-1].headers["x-api-key"] == "sk-ant-secret"
