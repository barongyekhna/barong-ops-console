"""独立站合规门(11-02 老板拍板):清单、骨架、校验、结论、重问、降级不算数、流水线先过门。unit,不连库、不出网。"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.modules.agent_series.suqinghe import compliance_gate as g
from backend.app.modules.agent_series.suqinghe.pipeline import View, next_step

pytestmark = pytest.mark.unit


class _Db:
    def commit(self) -> None:
        pass


def _filled(hits: dict[str, bool] | None = None, outside: bool = False, category: str = "") -> dict[str, Any]:
    hits = hits or {}
    sk = g.skeleton()
    for r in sk["rules"]:
        r["reason"] = f"{r['id']} 的理由"
        r["hit"] = bool(hits.get(r["id"], False))
    sk["outside_list"] = {"reason": "清单外的理由", "category": category, "hit": outside}
    return sk


def test_rules_file_is_versioned_and_carries_the_boss_words() -> None:
    data = g.rules()
    assert data["version"] == 1 and [r["id"] for r in data["rules"]] == ["G01", "G02", "G03", "G04", "G05", "G06"]
    quotes = [q["text"] for q in data["boss_quotes"]]
    assert "1688一律过门无论是我给的还是他抓的。因为自产品我压根不会给他1688链接" in quotes
    assert "化妆品和食品及时不归FDA管我也不会做，所以直接毙掉就可以了。开始做合规门" in quotes
    assert "锂电池不包含在哪，其余的直接毙掉。" in quotes and "驱蚊不算，其他照毙" in quotes
    blob = json.dumps(data, ensure_ascii=False)
    assert "锂电池" in blob and "驱蚊" in blob and "水杯" in blob  # 不挡的写明白,免得模型把水杯当食品


def test_only_factory_goods_skip_the_gate() -> None:
    assert g.applies("1688") and g.applies(None) and g.applies("") and not g.applies("factory")


def test_skeleton_fixes_ids_and_order_and_puts_reason_before_hit() -> None:
    sk = g.skeleton()
    assert [r["id"] for r in sk["rules"]] == ["G01", "G02", "G03", "G04", "G05", "G06"]
    assert all(list(r) == ["id", "rule", "reason", "hit"] and r["hit"] is None for r in sk["rules"])
    prompt = g.build_prompt("中文标题:玻尿酸面霜")
    assert json.dumps(sk, ensure_ascii=False, indent=1) in prompt and "玻尿酸面霜" in prompt and "只输出这一个 JSON" in prompt


def test_validate_catches_every_shape_problem() -> None:
    assert g.validate(_filled()) == []
    missing = _filled()
    missing["rules"] = missing["rules"][:5]
    assert any("id 不对" in p for p in g.validate(missing))
    dup = _filled()
    dup["rules"][5] = dict(dup["rules"][4])
    assert any("id 不对" in p for p in g.validate(dup))
    swapped = _filled()
    swapped["rules"][0], swapped["rules"][1] = swapped["rules"][1], swapped["rules"][0]
    assert any("id 不对" in p for p in g.validate(swapped))
    not_bool = _filled()
    not_bool["rules"][2]["hit"] = "false"
    assert "G03 的 hit 不是 true/false" in g.validate(not_bool)
    no_reason = _filled()
    no_reason["rules"][3]["reason"] = " "
    assert "G04 没写理由" in g.validate(no_reason)
    assert "outside_list 判了 true 却没写类别" in g.validate(_filled(outside=True))
    assert g.validate(None) == ["不是 JSON 对象"] and g.validate({"rules": "x"}) == ["rules 不是列表"]


def test_code_decides_drop_ask_pass() -> None:
    drop = g.decide(_filled({"G02": True, "G05": True}))
    assert drop["status"] == "drop" and [h["id"] for h in drop["hits"]] == ["G02", "G05"] and drop["outside"] is None
    assert drop["hits"][0]["text"].startswith("美国 FDA") and drop["hits"][0]["reason"] == "G02 的理由"
    # 清单命中优先于清单外
    assert g.decide(_filled({"G06": True}, outside=True, category="电子烟"))["status"] == "drop"
    ask = g.decide(_filled(outside=True, category="农药杀虫剂"))
    assert ask["status"] == "ask" and ask["outside"]["category"] == "农药杀虫剂"
    assert g.decide(_filled())["status"] == "pass"


def test_judge_retries_once_on_a_bad_sheet_then_decides() -> None:
    calls: list[str] = []
    answers = [{"rules": []}, _filled({"G03": True})]

    def call(db, prompt):
        calls.append(prompt)
        return answers.pop(0)

    out = g.judge(_Db(), "婴儿推车", call=call)
    assert out["status"] == "drop" and out["calls"] == 2 and len(calls) == 2 and calls[0] == calls[1]
    assert out["version"] == 1 and out["source"] == "1688" and out["judged_at"]


def test_judge_gives_up_after_two_bad_sheets_and_never_counts_degraded_or_failed_calls() -> None:
    bad = g.judge(_Db(), "x", call=lambda db, p: {"rules": "nope"})
    assert bad["status"] == "error" and bad["calls"] == 2 and "格式都不对" in bad["error"]
    degraded = g.judge(_Db(), "x", call=lambda db, p: {**_filled({"G01": True}), "_ai_degraded": True})
    assert degraded["status"] == "error" and "降级" in degraded["error"]  # DeepSeek 顶班判的不算数

    def boom(db, p):
        raise TimeoutError("slow")

    failed = g.judge(_Db(), "x", call=boom)
    assert failed["status"] == "error" and failed["error"].startswith("TimeoutError")
    # 自产品:不调模型
    skipped = g.judge(_Db(), "x", call=boom, source="factory")
    assert skipped["status"] == "skip" and skipped["calls"] == 0


def test_state_and_override() -> None:
    assert g.state({}) is None and g.state({"compliance_gate": {"status": "error"}}) is None
    assert g.state({"compliance_gate": {"status": "pass"}}) == "pass"
    assert g.state({"compliance_gate": {"status": "drop"}}) == "drop"
    assert g.state({"compliance_gate": {"status": "drop", "override": {"by": "1"}}}) == "override"


def test_dossier_facts_use_what_she_read_and_leave_out_price_and_link() -> None:
    draft = {
        "fields": {"name_zh": {"value": "跨境户外灭蚊灯"}, "name_en": {"value": "Mosquito Repellent Camping Light"}, "category": {"value": {"path": "Sporting Goods > Camping Lights", "name_zh": "营地灯"}}},
        "other_attributes": [{"name": "电源形式", "value": "充电"}],
        "specs": {"power": {"value": "10", "unit": "W"}},
        "variants": [{"name_zh": "黑色"}, {"name_zh": "绿色"}],
        "image_read": {"facts": [{"text": "多功能驱蚊露营灯"}]},
        "pricing": {"cost_cny": 28.5},
        "source_url": "https://detail.1688.com/offer/1.html",
    }
    facts = g.dossier_facts(draft, {"title_zh": "备用标题"})
    assert "跨境户外灭蚊灯" in facts and "Camping Lights" in facts and "营地灯" in facts and "电源形式: 充电" in facts
    assert "power: 10 W" in facts and "黑色 / 绿色" in facts and "多功能驱蚊露营灯" in facts
    assert "28.5" not in facts and "1688.com" not in facts


def test_candidate_flag_uses_f_red_line_shape_and_blocks_automation() -> None:
    row = SimpleNamespace(red_flags_json=[{"type": "category_red_line", "reason": "老红线"}], automation_blocked=False)
    g.flag_candidate(row, {"status": "drop", "version": 1, "hits": [{"id": "G05", "text": "化妆品", "reason": "面霜"}]})
    assert row.automation_blocked is True
    assert row.red_flags_json[0]["type"] == "category_red_line"
    new = row.red_flags_json[-1]
    assert new["type"] == "sqh_compliance_gate" and new["gate"] == "drop" and "G05" in new["reason"]
    assert all(isinstance(v, str) for v in new.values())  # F 的接口要 dict[str, str]


def _view(**over: Any) -> View:
    base = dict(material_done=True, stopped=False, blocked_step=None, execution_status=None, execution_step=None, execution_minutes=None, risk_approved=False, sp_job=None, sp_failures=0, sp_candidates=False, sp_approved=False, market_done=True)
    base.update(over)
    return View(**base)


def test_pipeline_runs_the_gate_first_and_holds_on_drop_or_ask() -> None:
    assert next_step(_view(gate=None, material_done=False)) == "compliance_gate"
    assert next_step(_view(gate="drop")) is None and next_step(_view(gate="ask")) is None
    for ok in ("pass", "skip", "override"):
        assert next_step(_view(gate=ok, material_done=False)) == "material"
    # 老板驳了「卡住」卡 = 这个品先不做:不补判
    assert next_step(_view(gate=None, stopped=True)) is None
