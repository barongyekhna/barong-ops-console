"""苏青禾选风格包(M2a):骨架、校验、重问、降级不算数、按真实四个包判出用/变体/缺包、缺包合并、流水线什么时候选包。unit。"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.modules.agent_series.suqinghe import style_route as sr
from backend.app.modules.agent_series.suqinghe.pipeline import View, next_step
from backend.app.modules.k_series.jiagui import registry

pytestmark = pytest.mark.unit

FIX = Path(__file__).parent / "fixtures" / "jiagui"


def _pack(name: str) -> dict[str, Any]:
    import tarfile

    with tarfile.open(FIX / f"{name}.tar.gz") as tf:
        fh = tf.extractfile(f"{name}/pack.json")
        assert fh is not None
        return json.loads(fh.read())


VIEW = sorted(
    [_pack("sunny-pop-1.0.1"), _pack("household-outdoor-tools-0.1.0"), _pack("warm-home-0.1.0"), _pack("dark-hardcore-0.1.0")],
    key=lambda p: (registry.STAGE_ORDER[p["stage"]], p["id"]),
)


class _Db:
    def commit(self) -> None:
        pass


def fill(
    skel: dict[str, Any],
    *,
    scores: list[int] | None = None,
    hits: tuple[str, ...] = (),
    same: tuple[str, ...] = (),
    category: str | None = "C06",
    variant: str | None = None,
    progress: dict[str, str] | None = None,
    idea: dict[str, str] | None = None,
    new_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = copy.deepcopy(skel)
    out["product"].update(category="品类", audience="买家", main_scene="场景")
    for pid, j in out["packs"].items():
        j["category_match"] = {"reason": "对上了", "id": category}
        for rid, cell in j["red_lines"].items():
            cell.update(reason="理由", hit=rid in hits)
        for (qid, cell), s in zip(j["scores"].items(), scores or [2] * len(j["scores"]), strict=True):
            cell.update(reason="理由", score=s)
        for xid, cell in j["precedents"].items():
            cell.update(reason="理由", same_kind=xid in same)
        j["variant_pick"] = {"reason": "最贴", "id": variant}
    chosen = {**(progress or {}), **(idea or {})}
    for pid, cell in out["other_packs"].items():
        cell.update(reason="理由", match=pid in chosen, category=chosen.get(pid))
    out["new_pack"] = new_pack
    out["notes"] = "要点"
    return out


def _judge(answer_fn, **kw: Any) -> dict[str, Any]:
    calls: list[str] = []

    def call(db, prompt):
        calls.append(prompt)
        return answer_fn(len(calls))

    out = sr.judge(_Db(), "中文标题:测试品", VIEW, product_id="TST-001", price="$29.99", call=call, docs={}, **kw)
    out["_prompts"] = calls
    return out


def test_skeleton_keys_every_item_by_id_and_puts_reason_first() -> None:
    skel = sr.skeleton(VIEW, product_id="TST-001", price="$29.99")
    assert list(skel["packs"]) == ["sunny-pop"]  # 只有可用的包要打分
    sunny = skel["packs"]["sunny-pop"]
    assert list(sunny["red_lines"]) == [f"R0{i}" for i in range(1, 8)]
    assert list(sunny["scores"]) == [f"F{i}" for i in range(1, 7)]
    assert list(sunny["precedents"]) == [f"P0{i}" for i in range(1, 10)]
    assert all(list(c)[-2:] == ["reason", "hit"] for c in sunny["red_lines"].values())
    assert all(list(c)[-2:] == ["reason", "score"] for c in sunny["scores"].values())
    assert list(sunny["category_match"]) == ["reason", "id"] and list(sunny["variant_pick"]) == ["reason", "id"]
    # 在做的和未立包的合成一张表(11-02 第一遍考试:分两个列表时模型会把未立包的挪进在做的)
    assert list(skel["other_packs"]) == ["household-outdoor-tools", "warm-home", "dark-hardcore"]
    assert skel["other_packs"]["dark-hardcore"]["stage"] == "未立包" and list(skel["other_packs"]["warm-home"])[-3:] == ["reason", "match", "category"]
    prompt = sr.build_prompt("中文标题:测试品", VIEW, skel, {"sunny-pop/style-card.md": "风格卡原文"})
    assert json.dumps(skel, ensure_ascii=False, indent=1) in prompt and "中文标题:测试品" in prompt and "风格卡原文" in prompt
    assert "一律等更对口的包" in prompt and "只输出这一个 JSON" in prompt and "R07" in prompt and "C10" in prompt


def test_validate_catches_shape_problems() -> None:
    skel = sr.skeleton(VIEW, product_id="T")
    good = fill(skel)
    assert sr.validate(good, skel, VIEW) == []
    bad = copy.deepcopy(good)
    del bad["packs"]["sunny-pop"]["red_lines"]["R07"]
    assert any("red_lines 的 id 不对" in p for p in sr.validate(bad, skel, VIEW))
    bad = copy.deepcopy(good)
    bad["packs"]["sunny-pop"]["scores"]["F2"]["score"] = "2"
    assert "sunny-pop.F2 的 score 不是 0/1/2" in sr.validate(bad, skel, VIEW)
    bad = copy.deepcopy(good)
    bad["packs"]["sunny-pop"]["scores"]["F2"]["score"] = True
    assert "sunny-pop.F2 的 score 不是 0/1/2" in sr.validate(bad, skel, VIEW)
    bad = copy.deepcopy(good)
    bad["packs"]["sunny-pop"]["precedents"]["P01"]["reason"] = ""
    assert "sunny-pop.P01 没写理由" in sr.validate(bad, skel, VIEW)
    bad = copy.deepcopy(good)
    bad["other_packs"]["household-outdoor-tools"].update(match=True, category=None)
    assert any("判了对口却没填对品类 id" in p for p in sr.validate(bad, skel, VIEW))
    bad = copy.deepcopy(good)
    bad["other_packs"]["ghost"] = {"reason": "-", "match": False, "category": None}
    assert any("other_packs 的 id 不对" in p for p in sr.validate(bad, skel, VIEW))
    bad = copy.deepcopy(good)
    bad["packs"]["sunny-pop"]["scores"] = list(bad["packs"]["sunny-pop"]["scores"].values())
    assert "sunny-pop.scores 不是对象" in sr.validate(bad, skel, VIEW)
    # 换算成标准 jiagui-judgement/1:列表按包里的顺序,在做的 / 未立包的按注册表分开
    j = sr.to_judgement(good, VIEW, product_id="T", price="$9.99")
    assert [r["id"] for r in j["packs"]["sunny-pop"]["red_lines"]] == [f"R0{i}" for i in range(1, 8)]
    assert [r["q"] for r in j["packs"]["sunny-pop"]["scores"]] == [f"F{i}" for i in range(1, 7)]
    assert [r["pack"] for r in j["in_progress"]] == ["household-outdoor-tools", "warm-home"] and [r["pack"] for r in j["idea_packs"]] == ["dark-hardcore"]
    assert j["schema"] == "jiagui-judgement/1" and j["compliance"] == [] and j["product"]["id"] == "T" and j["product"]["price"] == "$9.99"
    bad = copy.deepcopy(good)
    bad["packs"]["sunny-pop"]["category_match"]["id"] = "C99"
    assert any("C99" in p for p in sr.validate(bad, skel, VIEW))
    bad = copy.deepcopy(good)
    bad["new_pack"] = {"categories": []}
    assert "new_pack 要么是 null,要么带 name" in sr.validate(bad, skel, VIEW)
    assert sr.validate(None, skel, VIEW) == ["不是 JSON 对象"]


def test_real_packs_drill_waits_for_household_tools_lamp_uses_sunny_variant() -> None:
    # 电钻:阳光冲击 R07(手枪式电动工具)出局,家务户外工具对口 → 缺包,等在做的家务户外工具
    drill = _judge(lambda n: fill(sr.skeleton(VIEW, product_id="TST-001", price="$29.99"), hits=("R07",), progress={"household-outdoor-tools": "C09"}))
    rec = drill["record"]
    assert drill["status"] == "pass" and drill["calls"] == 1
    assert rec["decision"]["kind"] == "missing" and rec["missing_pack"]["kind"] == "in_progress" and rec["missing_pack"]["pack"] == "household-outdoor-tools"
    assert rec["missing_pack"]["progress"]["doing"].startswith("等老板拍板决策稿")
    assert rec["decision"]["compliance_hold"] is False and rec["judgement"]["compliance"] == []
    assert sr.missing_key(rec["missing_pack"]) == "in_progress:household-outdoor-tools"
    assert "等「家务户外工具」(规划中)" in sr.headline(rec, VIEW)
    assert sr.out_reasons(rec, VIEW) == ["「阳光冲击」出局:R07 手枪式的电动工具（电钻、起子机、热熔胶枪、射钉枪等）：伸向镜头时会被读成举枪"]
    # 驱蚊露营灯:8/12、F4 1 分 → 变体档、没有在做的包对口 → 用阳光冲击的「室内、夜晚或冬季」变体
    lamp = _judge(lambda n: fill(sr.skeleton(VIEW, product_id="TST-001", price="$29.99"), scores=[2, 2, 1, 1, 1, 1], variant="V-indoor-night-winter"))
    s = sr.summary(lamp["record"])
    assert s == {"decision_kind": "variant", "pack_id": "sunny-pop", "pack_version": "1.0.1", "variant": "V-indoor-night-winter", "missing_key": None, "packs": None}
    assert lamp["record"]["product"] == {"id": "TST-001", "category": "品类", "price": "$29.99", "audience": "买家", "main_scene": "场景"}
    # 什么都对不上 → 要新做一个包,按建议包名合并
    sofa = _judge(lambda n: fill(sr.skeleton(VIEW, product_id="T"), scores=[0, 1, 0, 0, 1, 0], category=None, new_pack={"name": "家具 软装", "categories": ["沙发"], "references": "x", "images": ["场景"]}))
    assert sr.missing_key(sofa["record"]["missing_pack"]) == "new:家具软装"


def test_retry_once_then_give_up_and_never_count_degraded_answers() -> None:
    skel = sr.skeleton(VIEW, product_id="TST-001", price="$29.99")
    out = _judge(lambda n: {"packs": {}} if n == 1 else fill(skel, scores=[2] * 6))
    assert out["status"] == "pass" and out["calls"] == 2 and out["_prompts"][0] == out["_prompts"][1]
    assert out["record"]["decision"]["kind"] == "use"
    bad = _judge(lambda n: {"packs": {}})
    assert bad["status"] == "error" and bad["calls"] == 2 and "格式都不对" in bad["error"]
    degraded = _judge(lambda n: {**fill(skel), "_ai_degraded": True})
    assert degraded["status"] == "error" and "降级" in degraded["error"] and degraded["calls"] == 1

    def boom(n):
        raise TimeoutError("slow")

    assert _judge(boom)["error"].startswith("TimeoutError")
    assert sr.judge(_Db(), "x", [], product_id="T", call=lambda db, p: {})["error"] == "注册表里还没有生效的风格包"


def test_registry_fingerprint_changes_with_versions_and_stages() -> None:
    fp = registry.fingerprint(VIEW)
    assert fp == registry.fingerprint(list(reversed(VIEW)))
    bumped = copy.deepcopy(VIEW)
    bumped[1]["stage"] = "usable"
    assert registry.fingerprint(bumped) != fp


def test_price_helpers() -> None:
    assert sr.price_text({"low": 29.99, "high": 29.99, "source": "applied"}) == "$29.99(已定价)"
    assert sr.price_text({"low": 45.99, "high": 54.99, "source": "card"}).startswith("$45.99–$54.99(价格卡上的建议价")
    assert not sr.price_moved({"low": 29.99, "high": 29.99}, {"low": 30.49, "high": 30.49})
    assert sr.price_moved({"low": 29.99, "high": 29.99}, {"low": 39.99, "high": 39.99})
    assert not sr.price_moved(None, {"low": 1, "high": 1})


def _view(**over: Any) -> View:
    base = dict(material_done=True, stopped=False, blocked_step=None, execution_status="completed", execution_step=None, execution_minutes=1.0, risk_approved=True, sp_job="completed", sp_failures=0, sp_candidates=False, sp_approved=True, market_done=True)
    base.update(over)
    return View(**base)


def test_pipeline_routes_once_the_price_card_is_out_and_holds_only_the_image_part() -> None:
    # 价格卡在等老板:该选包就先选包,选完照样等价格卡
    assert next_step(_view(price_card="pending", route_due=True)) == "route"
    assert next_step(_view(price_card="pending", route_due=False, route_hold=True)) is None
    # 价定了、文案批了:包没定下来(缺包/同分/还没判)→ 作图那一段等着;定了 → 照旧(作图指令现在停着)
    after_copy = dict(price_applied=True, shipping_set=True, copy_ok=True, copy_checked=True, copy_approved=True)
    assert next_step(_view(**after_copy, route_hold=True, brief_paused=False)) is None
    assert next_step(_view(**after_copy, route_hold=False, brief_paused=False)) == "image_brief"
    # 文案那一段不受包的影响
    assert next_step(_view(price_applied=True, shipping_set=True, route_hold=True)) == "copy"
