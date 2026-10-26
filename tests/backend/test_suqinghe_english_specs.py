"""规格的英文(10-26):建档写进 K 的规格行只有中文,K 的买家规格表一行都出不来。unit,不连库、不出网。

验的是 K 自己的东西:补完英文的规格能过 K 的校验(ProductKnowledgeUpdate),K 的买家规格表(buyer_spec_rows)真的出行、单位换成英制。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.modules.agent_series.suqinghe import english_specs, executor, pipeline
from backend.app.modules.k_series.product_knowledge.buyer_display import buyer_spec_rows
from backend.app.modules.k_series.product_knowledge.schemas import ProductKnowledgeCreate, ProductKnowledgeUpdate

pytestmark = pytest.mark.unit

LIVE = json.loads((Path(__file__).parent / "fixtures" / "sqh1688" / "live_drafts_20261026.json").read_text(encoding="utf-8"))


def _k_specs(offer_id: str) -> tuple[dict, dict]:
    live = LIVE[offer_id]
    fake = SimpleNamespace(id=live["dossier_id"], offer_id=offer_id, source_url=f"https://detail.1688.com/offer/{offer_id}.html", draft=live["draft"])
    return ProductKnowledgeCreate(**executor.build_create_payload(fake)).structured_specs_json, live["draft"]["specs"]


def test_before_the_fix_k_shows_no_spec_rows_at_all() -> None:
    specs, _ = _k_specs("643348607768")
    assert buyer_spec_rows(specs, target_market="US") == []


def test_battery_specs_reach_the_buyer_table_in_imperial() -> None:
    specs, dossier_specs = _k_specs("643348607768")
    rows, todo = english_specs.plan(specs, dossier_specs)
    assert set(todo) == {"material", "battery_type"}  # 只有中文值要翻:阻燃ABS、「18650、Li-ion、全新A品电芯…」
    rows, missed = english_specs.apply_translations(
        rows, {"material": "Flame-retardant ABS", "battery_type": "18650 Li-ion cells, grade A new cells"}
    )
    assert missed == []
    updated = {**specs, "additional_specs": rows}
    ProductKnowledgeUpdate(structured_specs_json=updated)  # 过得了 K 的校验
    table = {row["label"]: (row["display_value"], row["display_unit"]) for row in buyer_spec_rows(updated, target_market="US")}
    assert table["Voltage"] == ("12", "V")
    assert table["Item Weight"][1] == "oz"  # 166 g → 盎司
    assert table["Item Dimensions"][0].endswith("in") or table["Item Dimensions"][1] == "in"  # 84×48×40 mm → 英寸
    assert table["Material"] == ("Flame-retardant ABS", None)
    assert "Cycle Life" in table and "Certifications" in table
    assert english_specs.done(updated)


def test_untranslatable_rows_are_left_out_not_invented() -> None:
    specs, dossier_specs = _k_specs("773137484620")
    rows, todo = english_specs.plan(specs, dossier_specs)
    rows, missed = english_specs.apply_translations(rows, {key: "还是中文" for key in todo})
    assert set(missed) == set(todo)
    labels = {row["label"] for row in buyer_spec_rows({**specs, "additional_specs": rows}, target_market="US")}
    assert not labels & {english_specs.LABELS_EN[key] for key in missed}
    # 这几行确实没有英文(done 说实话);流水线靠档案里这一步的记号判「做过了」,不会反复翻
    assert not english_specs.done({**specs, "additional_specs": rows})


def test_certification_claims_wait_for_the_boss() -> None:
    assert pipeline.is_certification_claim({"category": "certification", "evidence": "spec:additional_specs.sqh_certification"})
    assert pipeline.is_certification_claim({"category": "quality", "evidence": "spec:additional_specs.sqh_certification"})
    assert not pipeline.is_certification_claim({"category": "durability", "evidence": "spec:additional_specs.sqh_cycle_life"})
    review = pipeline.selling_point_review(
        {
            "review_status": "candidate",
            "bullets": [
                {"id": "a", "category": "certification", "text": "通过 UL 1642 认证", "importance_score": 8, "evidence": "spec:additional_specs.sqh_certification", "verification_status": "verified"},
                {"id": "b", "category": "durability", "text": "循环 500 次", "importance_score": 7, "evidence": "spec:additional_specs.sqh_cycle_life", "verification_status": "verified"},
            ],
        }
    )
    assert [b["review_decision"] for b in review] == ["reject", "approve"]
