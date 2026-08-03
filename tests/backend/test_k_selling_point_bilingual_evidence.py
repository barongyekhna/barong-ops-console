"""卖点证据门的中英文对齐回归。

运营用中文录规格(label「续航」/「防水等级」),卖点是英文写的。门禁原来只读中文
label,英文文案永远「找不到证据」——PSPE-002 熊猫花洒 15 条候选里被误杀 4 条
(2026-08-03)。这组测试锁住两件事:双语能对齐、门禁没被放宽。
"""

from __future__ import annotations

import pytest

from backend.app.modules.k_series.product_knowledge.router import (
    SellingPointBullet,
    _humanize_selling_point_error,
    _selling_point_review_error_message,
    _selling_point_support_error,
    _structured_spec_evidence_snapshot,
)


pytestmark = pytest.mark.unit


def _operator_specs() -> dict:
    """PSPE-002 的真实形状:中文 label + 英文对照,单位分开存。"""

    return {
        "schema_version": "1.0",
        "source": {"platform": "operator", "evidence_type": "operator_fact"},
        "additional_specs": [
            {
                "key": "operator_attribute_10",
                "label": "续航",
                "label_en": "Battery Life",
                "value": "120-180",
                "value_en": "120-180",
                "raw_value": "120-180",
                "unit": "min",
            },
            {
                "key": "operator_attribute_8",
                "label": "防水等级",
                "label_en": "Waterproof Rating",
                "value": "IPX8",
                "value_en": "IPX8",
                "raw_value": "IPX8",
            },
            {
                "key": "operator_attribute_7",
                "label": "认证",
                "label_en": "Certifications",
                "value": "CE, RoHS",
                "value_en": "CE, RoHS",
                "raw_value": "CE, RoHS",
            },
            {
                "key": "operator_attribute_6",
                "label": "风格",
                "label_en": "Style",
                "value": "可爱熊猫造型",
                "value_en": "Cute Panda Design",
                "raw_value": "可爱熊猫造型",
            },
        ],
    }


def _snapshot(path: str) -> dict:
    snapshot = _structured_spec_evidence_snapshot(_operator_specs(), path)
    assert snapshot is not None
    return snapshot


def _bullet(text: str, *, evidence: str, category: str = "feature") -> SellingPointBullet:
    return SellingPointBullet(
        category=category,
        text=text,
        importance_score=1,
        evidence=evidence,
    )


def _weight_snapshot() -> dict:
    """verified_feature 的重量:嵌套字典,不是可以正则扫的文本。"""

    return {
        "evidence": "verified_feature:fd6e1027",
        "kind": "verified_feature",
        "key": "weight",
        "unit": "lb",
        "value": {
            "unit": "lb",
            "value": 2.67,
            "source": {"unit": "g", "value": 1211},
            "target_market": "US",
        },
        "value_text": '{"source": {"unit": "g", "value": 1211}, "unit": "lb", "value": 2.67}',
    }


def _dimensions_snapshot() -> dict:
    return {
        "evidence": "verified_feature:918488d2",
        "kind": "verified_feature",
        "key": "dimensions",
        "unit": "inch",
        "value": {
            "unit": "inch",
            "width": 9.843,
            "height": 6.102,
            "length": 9.843,
            "source": {"unit": "cm", "width": 25, "height": 15.5, "length": 25},
            "target_market": "US",
        },
        "value_text": "{}",
    }


def test_chinese_label_supports_english_topic_without_relaxing_numbers() -> None:
    snapshot = _snapshot("additional_specs.operator_attribute_10")
    assert snapshot["label"] == "续航"
    assert snapshot["label_en"] == "Battery Life"

    assert (
        _selling_point_support_error(
            _bullet(
                "Up to 120-180 minutes of runtime on a full charge",
                evidence="spec:additional_specs.operator_attribute_10",
                category="battery",
            ),
            snapshot,
        )
        is None
    )
    # 门没被放宽:证据里没有的数字照拦。
    assert _selling_point_support_error(
        _bullet(
            "Up to 200 minutes of runtime on a full charge",
            evidence="spec:additional_specs.operator_attribute_10",
            category="battery",
        ),
        snapshot,
    ) == "Claim contains numbers absent from the current evidence: 200"


def test_chinese_label_alone_supports_topic_when_english_is_missing() -> None:
    """就算没录 label_en,中文「续航」自己也要撑得起 runtime。"""

    snapshot = _snapshot("additional_specs.operator_attribute_10")
    snapshot["label_en"] = ""
    snapshot["value_en"] = None

    assert (
        _selling_point_support_error(
            _bullet(
                "Runtime reaches 120-180 minutes per charge",
                evidence="spec:additional_specs.operator_attribute_10",
                category="battery",
            ),
            snapshot,
        )
        is None
    )


def test_ip_rating_supports_waterproof_and_safety_claims() -> None:
    snapshot = _snapshot("additional_specs.operator_attribute_8")

    assert (
        _selling_point_support_error(
            _bullet(
                "IPX8 waterproof rating ensures safe operation even when fully submerged",
                evidence="spec:additional_specs.operator_attribute_8",
                category="safety",
            ),
            snapshot,
        )
        is None
    )


def test_certification_evidence_supports_safety_wording() -> None:
    snapshot = _snapshot("additional_specs.operator_attribute_7")

    assert (
        _selling_point_support_error(
            _bullet(
                "CE and RoHS certified for safety and environmental standards",
                evidence="spec:additional_specs.operator_attribute_7",
                category="certification",
            ),
            snapshot,
        )
        is None
    )


def test_pump_type_wording_is_not_a_waterproof_claim() -> None:
    """「submersible pump」说的是泵的类型,不是防水声称,不能拿防水词表去卡。"""

    snapshot = {
        "kind": "spec",
        "path": "operator_attribute_12",
        "label": "最低吸水高度",
        "label_en": "Minimum Water Level",
        "value": "0.39",
        "raw_value": "0.39",
        "unit": "inch",
        "value_text": "0.39 inch",
    }

    assert (
        _selling_point_support_error(
            _bullet(
                "Submersible pump draws water from as low as 0.39 inch, "
                "ideal for shallow buckets",
                evidence="spec:additional_specs.operator_attribute_12",
                category="performance",
            ),
            snapshot,
        )
        is None
    )


def test_safety_wording_still_blocked_without_safety_evidence() -> None:
    """放行的只有认证/防护等级这一类,别的证据配「safe」照样拦。"""

    snapshot = _snapshot("additional_specs.operator_attribute_6")

    assert _selling_point_support_error(
        _bullet(
            "Safe for children to use unsupervised",
            evidence="spec:additional_specs.operator_attribute_6",
            category="safety",
        ),
        snapshot,
    ) == "Evidence does not support the claim topic 'safety'."


def test_structured_weight_and_dimensions_bind_numbers_to_their_units() -> None:
    assert (
        _selling_point_support_error(
            _bullet(
                "Lightweight at only 2.67 lb, easy to pack for camping and travel",
                evidence="verified_feature:fd6e1027",
                category="portability",
            ),
            _weight_snapshot(),
        )
        is None
    )
    assert (
        _selling_point_support_error(
            _bullet(
                "Compact size: 9.843 x 9.843 x 6.102 inches fits in any bag",
                evidence="verified_feature:918488d2",
                category="size",
            ),
            _dimensions_snapshot(),
        )
        is None
    )
    # 单位换成别的维度就必须拦住。
    assert _selling_point_support_error(
        _bullet(
            "Lightweight at only 2.67 oz",
            evidence="verified_feature:fd6e1027",
            category="portability",
        ),
        _weight_snapshot(),
    ) == "Claim contains number/unit pairs absent from the current evidence: 2.67 oz"


def test_review_errors_are_reported_in_chinese_and_in_full() -> None:
    assert _humanize_selling_point_error(
        "Evidence does not support the claim topic 'runtime'."
    ).startswith("文案里说了「续航」")

    message = _selling_point_review_error_message(
        [
            {
                "index": 2,
                "text": "Up to 120-180 minutes of runtime on a full charge",
                "error": "Evidence does not support the claim topic 'runtime'.",
            },
            {
                "index": 10,
                "text": "Lightweight at only 2.67 lb",
                "error": (
                    "Claim contains number/unit pairs absent from the current "
                    "evidence: 2.67 lb"
                ),
            },
        ]
    )

    assert "共 2 条问题" in message
    assert "第 3 条" in message
    assert "第 11 条" in message
    assert "2.67 lb" in message
