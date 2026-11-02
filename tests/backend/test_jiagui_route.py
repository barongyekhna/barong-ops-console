"""选包判定 route.decide()(M0 冻结版第三部分第 4、7 节):Mac 参考实现的 18 条向量逐条一致 + 边界。unit,纯函数。

向量文件是交接 12 的 12_route_ref/vectors_v1.json 原样拷贝(tests/backend/fixtures/jiagui/route_vectors_v1.json)。"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.modules.k_series.jiagui.route import decide, validate

pytestmark = pytest.mark.unit

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "jiagui" / "route_vectors_v1.json").read_text(encoding="utf-8"))


def _got(rec: dict[str, Any]) -> dict[str, Any]:
    d, mp = rec["decision"], rec["missing_pack"] or {}
    return {
        "kind": d["kind"],
        "pack": d.get("pack"),
        "variant": d.get("variant"),
        "listing": d["listing"],
        "compliance_hold": d["compliance_hold"],
        "flags": sorted(f["code"] for f in rec["flags"]),
        "missing_kind": mp.get("kind"),
        "missing_pack": mp.get("pack"),
        "packs": sorted(d.get("packs") or []),
        "out": {pid: row["out"] for pid, row in rec["computed"]["packs"].items() if row["out"]},
    }


@pytest.mark.parametrize("case", VECTORS["vectors"], ids=[c["id"] for c in VECTORS["vectors"]])
def test_matches_mac_reference_vectors(case: dict[str, Any]) -> None:
    rec = decide(case["judgement"], case["registry"], {"allowed_styles": case.get("allowed_styles") or []}, case.get("overrides") or [])
    exp = case["expect"]
    if "error" in exp:
        assert rec["status"] == "error" and rec["codes"][0] == exp["error"]
        assert rec["decision"]["listing"] == "hold" and validate(rec) == []
        return
    assert rec["status"] == "pass", rec["error"]
    assert validate(rec) == []
    got = _got(rec)
    for key, want in exp.items():
        assert (sorted(got[key]) if key in ("flags", "packs") else got[key]) == (sorted(want) if key in ("flags", "packs") else want), key


def _base() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    case = next(c for c in VECTORS["vectors"] if c["id"] == "D01")
    return copy.deepcopy(case["judgement"]), copy.deepcopy(case["registry"])


def _scores(j: dict[str, Any], values: list[Any]) -> None:
    for row, v in zip(j["packs"]["sunny-pop"]["scores"], values, strict=True):
        row["score"] = v


def test_variant_band_without_a_pick_still_variant_but_flagged() -> None:
    j, reg = _base()
    _scores(j, [2, 2, 1, 0, 1, 2])
    rec = decide(j, reg)
    assert rec["decision"]["kind"] == "variant" and rec["decision"]["variant"] is None
    assert [f["code"] for f in rec["flags"]] == ["ROUTE.VARIANT_TRIGGER_MISMATCH"]


@pytest.mark.parametrize("override", [[{"pack": "sunny-pop", "category": "C01"}], [["sunny-pop", "C01"]]])
def test_owner_override_by_pack_and_category_knocks_the_pack_out(override: Any) -> None:
    j, reg = _base()
    rec = decide(j, reg, None, override)
    assert rec["computed"]["packs"]["sunny-pop"]["out"] == {"by": "owner_override", "id": "C01"} and rec["decision"]["kind"] == "missing"


def test_bad_ids_and_scores_are_errors_not_guesses() -> None:
    j, reg = _base()
    j["packs"]["sunny-pop"]["variant_pick"] = {"id": "V-nope", "reason": "-"}
    assert decide(j, reg)["codes"] == ["E.JUDGEMENT.BAD_ID"]
    j, reg = _base()
    _scores(j, [2, True, 1, 0, 1, 2])  # 布尔不是分数
    assert decide(j, reg)["codes"] == ["E.JUDGEMENT.BAD_SCORE"]
    j, reg = _base()
    j["in_progress"] = j["in_progress"][:1]  # 漏列一个在做的包
    assert decide(j, reg)["codes"] == ["E.JUDGEMENT.INCOMPLETE"]
    j, reg = _base()
    j["idea_packs"][0].update(match=True, category=None)
    assert decide(j, reg)["codes"] == ["E.JUDGEMENT.BAD_ID"]
    j, reg = _base()
    j["packs"]["ghost"] = copy.deepcopy(j["packs"]["sunny-pop"])
    assert decide(j, reg)["codes"] == ["E.JUDGEMENT.BAD_ID"]
    j, reg = _base()
    del j["packs"]["sunny-pop"]["category_match"]
    assert decide(j, reg)["codes"] == ["E.JUDGEMENT.INCOMPLETE"]
