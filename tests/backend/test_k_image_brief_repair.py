"""作图指令降级修复:缺标注层的 feature_callout 不再一票否决(2026-07-22)。"""

from __future__ import annotations

import pytest

from backend.app.modules.k_series.product_knowledge.workflow_engine import (
    _normalize_evidence_driven_image_brief,
)

pytestmark = pytest.mark.unit


def _points() -> list[dict]:
    return [{"id": "bp1", "text": "Slow rebound squeeze relief"}]


def test_feature_callout_without_overlay_downgrades_to_proof_scene() -> None:
    result = {
        "images": [
            {"position": 1, "role": "main", "prompt": "white background"},
            {
                "position": 2,
                "role": "feature_callout",
                "selling_point_id": "bp1",
                "prompt": "hand squeezing the ball",
            },
            # 绑不上卖点的缺标注图:丢弃而不是炸掉整套方案
            {"position": 3, "role": "feature_callout", "prompt": "orphan callout"},
        ]
    }
    out = _normalize_evidence_driven_image_brief(result, _points())
    by_position = {image["position"]: image for image in out["images"]}
    assert 3 not in by_position
    converted = by_position[2]
    assert converted["role"] == "proof_scene"
    assert converted["proof_intent"] == "Slow rebound squeeze relief"
    assert converted["selling_point_id"] == "bp1"
    assert converted["selling_point_index"] == 1
