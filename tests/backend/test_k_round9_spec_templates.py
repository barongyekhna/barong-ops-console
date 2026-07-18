from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Iterator
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.modules.k_series.product_knowledge import (
    spec_template_router as template_router,
)
from backend.app.modules.k_series.product_knowledge.models import (
    KCategorySpecTemplate,
)
from backend.app.modules.k_series.product_knowledge.buyer_display import (
    buyer_spec_rows,
)
from backend.app.modules.k_series.product_knowledge.spec_templates import (
    SpecTemplateValidationError,
    missing_required_fields,
    normalize_paste_parse_output,
    normalize_template_fields,
)
from backend.app.modules.k_series.product_knowledge.structured_specs import (
    normalize_operator_structured_specs,
)
from backend.app.modules.p_series.upload import assemble


pytestmark = pytest.mark.unit


def _field(
    *,
    key: str = "capacity_pot",
    target: str = "additional",
    label_zh: str = "主锅容量",
    label_en: str = "Main Pot Capacity",
    value_type: str = "number",
    required: bool = True,
    enum_options: list[str] | None = None,
    unit: str | None = "L",
) -> dict[str, object]:
    return {
        "key": key,
        "target": target,
        "label_zh": label_zh,
        "label_en": label_en,
        "value_type": value_type,
        "unit": unit,
        "required": required,
        "enum_options": enum_options,
        "hint_zh": "只填写粘贴证据中明确出现的值",
    }


def _approved_product(*, structured_specs: object = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        channel="dtc",
        google_product_category="123",
        amazon_category_id=None,
        structured_specs_json=structured_specs,
    )


@pytest.fixture
def spec_template_db() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    KCategorySpecTemplate.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        yield db
    engine.dispose()


def test_category_spec_template_model_uses_tree_and_id_as_composite_identity() -> None:
    table = KCategorySpecTemplate.__table__

    assert table.name == "k_category_spec_templates"
    assert list(table.primary_key.columns.keys()) == ["category_tree", "category_id"]
    assert table.c.category_tree.type.length == 16
    assert table.c.category_id.type.length == 32
    assert table.c.fields.nullable is False


def test_template_fields_require_snake_case_key_and_english_label() -> None:
    with pytest.raises(SpecTemplateValidationError, match="snake_case"):
        normalize_template_fields([_field(key="capacity-pot")])

    with pytest.raises(SpecTemplateValidationError, match="English label_en"):
        normalize_template_fields([_field(label_en="主锅容量")])

    with pytest.raises(SpecTemplateValidationError, match="English label_en"):
        normalize_template_fields([_field(label_en="123")])


def test_template_fields_prevent_semantic_standard_key_shadowing() -> None:
    with pytest.raises(
        SpecTemplateValidationError,
        match="battery_capacity_mah",
    ):
        normalize_template_fields(
            [
                _field(
                    key="battery_capacity",
                    label_zh="电池容量",
                    label_en="Battery Capacity",
                    unit="mAh",
                )
            ]
        )

    normalized = normalize_template_fields(
        [
            _field(
                key="battery_capacity_mah",
                target="standard",
                label_zh="电池容量",
                label_en="Battery Capacity",
                unit="mAh",
            )
        ]
    )
    assert normalized[0]["key"] == "battery_capacity_mah"
    assert normalized[0]["target"] == "standard"

    with pytest.raises(SpecTemplateValidationError, match="dimensions"):
        normalize_template_fields(
            [
                _field(
                    key="dimensions",
                    target="standard",
                    label_zh="产品尺寸",
                    label_en="Product Dimensions",
                    value_type="number",
                    unit="cm",
                )
            ]
        )


def test_template_enum_options_and_required_flag_are_strictly_validated() -> None:
    normalized = normalize_template_fields(
        [
            _field(
                key="finish_type",
                label_zh="表面处理",
                label_en="Finish Type",
                value_type="enum",
                enum_options=["Matte", "Polished"],
                required=False,
                unit=None,
            )
        ]
    )
    assert normalized[0]["enum_options"] == ["Matte", "Polished"]
    assert normalized[0]["required"] is False

    with pytest.raises(SpecTemplateValidationError, match="requires enum_options"):
        normalize_template_fields(
            [
                _field(
                    key="finish_type",
                    label_zh="表面处理",
                    label_en="Finish Type",
                    value_type="enum",
                    enum_options=None,
                )
            ]
        )

    with pytest.raises(SpecTemplateValidationError, match="duplicate enum_options"):
        normalize_template_fields(
            [
                _field(
                    key="finish_type",
                    label_zh="表面处理",
                    label_en="Finish Type",
                    value_type="enum",
                    enum_options=["Matte", "matte"],
                )
            ]
        )

    invalid_required = _field()
    invalid_required["required"] = "false"
    with pytest.raises(SpecTemplateValidationError, match="must be a boolean"):
        normalize_template_fields([invalid_required])


def test_missing_required_fields_distinguishes_standard_and_additional() -> None:
    fields = [
        _field(
            key="lumens",
            target="standard",
            label_zh="光通量",
            label_en="Luminous Flux",
            unit="lm",
        ),
        _field(
            key="is_dishwasher_safe",
            label_zh="是否可用洗碗机清洗",
            label_en="Dishwasher Safe",
            value_type="boolean",
            unit=None,
        ),
    ]

    assert missing_required_fields(fields, None) == [
        "lumens",
        "is_dishwasher_safe",
    ]
    assert missing_required_fields(
        fields,
        {
            "lumens": {"value": 0, "raw_value": "0 lm"},
            "additional_specs": [
                {"key": "is_dishwasher_safe", "value": False, "raw_value": "否"}
            ],
        },
    ) == []


def test_unknown_markers_do_not_satisfy_required_fields() -> None:
    fields = [
        _field(
            key="lumens",
            target="standard",
            label_zh="光通量",
            label_en="Luminous Flux",
            unit="lm",
        ),
        _field(
            key="is_dishwasher_safe",
            label_zh="是否可用洗碗机清洗",
            label_en="Dishwasher Safe",
            value_type="boolean",
            unit=None,
        ),
    ]

    assert missing_required_fields(
        fields,
        {
            "lumens": {"value": "unknown"},
            "additional_specs": [
                {"key": "is_dishwasher_safe", "value": "未知"}
            ],
        },
    ) == ["lumens", "is_dishwasher_safe"]


def test_required_fields_reject_wrong_types_enum_values_and_missing_units() -> None:
    fields = [
        _field(),
        _field(
            key="dishwasher_safe",
            label_zh="是否可机洗",
            label_en="Dishwasher Safe",
            value_type="boolean",
            unit=None,
        ),
        _field(
            key="finish_type",
            label_zh="表面处理",
            label_en="Finish Type",
            value_type="enum",
            enum_options=["Matte", "Polished"],
            unit=None,
        ),
    ]

    assert missing_required_fields(
        fields,
        {
            "additional_specs": [
                {"key": "capacity_pot", "value": "banana"},
                {"key": "dishwasher_safe", "value": "maybe"},
                {"key": "finish_type", "value": "Glossy"},
            ]
        },
    ) == ["capacity_pot", "dishwasher_safe", "finish_type"]
    assert missing_required_fields(
        fields,
        {
            "additional_specs": [
                {"key": "capacity_pot", "value": 1.4},
                {"key": "dishwasher_safe", "value": False},
                {"key": "finish_type", "value": "Matte"},
            ]
        },
    ) == ["capacity_pot"]


def test_paste_parser_whitelists_template_keys_and_same_row_evidence() -> None:
    fields = [
        _field(),
        _field(
            key="battery_capacity_mah",
            target="standard",
            label_zh="电池容量",
            label_en="Battery Capacity",
            unit="mAh",
        ),
        _field(
            key="supplier_note",
            label_zh="供应商备注",
            label_en="Supplier Note",
            value_type="text",
            required=False,
            unit=None,
        ),
    ]
    raw_text = "主锅容量\t1.4 L\n电池容量\t1000 mAh\n材质\t铝合金"
    provider_output = {
        "matched": {
            "capacity_pot": {
                "value": 1.4,
                "raw_value": "1.4 L",
                "source_label": "主锅容量",
            },
            # Both tokens exist in the paste, but never in the same source row.
            "battery_capacity_mah": {
                "value": 1000,
                "raw_value": "1000 mAh",
                "source_label": "主锅容量",
            },
            # Known key, fabricated supplier value.
            "supplier_note": {
                "value": "Titanium alloy",
                "raw_value": "钛合金",
                "source_label": "材质",
            },
            # Real evidence cannot create a field absent from the template.
            "supplier_color": {
                "value": "Aluminum alloy",
                "raw_value": "铝合金",
                "source_label": "材质",
            },
        },
        "unmatched_lines": ["虚构行", "材质\t铝合金"],
        # Provider diagnostics are untrusted and must be recomputed server-side.
        "missing_required": [],
    }

    parsed = normalize_paste_parse_output(
        provider_output,
        raw_text=raw_text,
        fields=fields,
    )

    assert parsed["matched"] == {
        "capacity_pot": {
            "value": 1.4,
            "raw_value": "1.4 L",
            "source_label": "主锅容量",
        }
    }
    assert parsed["missing_required"] == ["battery_capacity_mah"]
    assert "虚构行" not in parsed["unmatched_lines"]
    assert "电池容量\t1000 mAh" in parsed["unmatched_lines"]
    assert "材质\t铝合金" in parsed["unmatched_lines"]


def test_paste_parser_verifies_number_boolean_and_dimension_normalization() -> None:
    fields = [
        _field(),
        _field(
            key="dishwasher_safe",
            label_zh="是否可机洗",
            label_en="Dishwasher Safe",
            value_type="boolean",
            unit=None,
        ),
        _field(
            key="dimensions",
            target="standard",
            label_zh="产品尺寸",
            label_en="Product Dimensions",
            value_type="text",
            unit="cm",
        ),
    ]
    raw_text = "主锅容量\t1400 ml\n是否可机洗\t否\n产品尺寸\t100×200×300 mm"

    valid = normalize_paste_parse_output(
        {
            "matched": {
                "capacity_pot": {
                    "value": 1.4,
                    "raw_value": "1400 ml",
                    "source_label": "主锅容量",
                },
                "dishwasher_safe": {
                    "value": False,
                    "raw_value": "否",
                    "source_label": "是否可机洗",
                },
                "dimensions": {
                    "value": "10 x 20 x 30",
                    "raw_value": "100×200×300 mm",
                    "source_label": "产品尺寸",
                },
            }
        },
        raw_text=raw_text,
        fields=fields,
    )
    assert set(valid["matched"]) == {
        "capacity_pot",
        "dishwasher_safe",
        "dimensions",
    }

    fabricated = normalize_paste_parse_output(
        {
            "matched": {
                "capacity_pot": {
                    "value": 999,
                    "raw_value": "1400 ml",
                    "source_label": "主锅容量",
                },
                "dishwasher_safe": {
                    "value": True,
                    "raw_value": "否",
                    "source_label": "是否可机洗",
                },
                "dimensions": {
                    "value": "99 x 99 x 99",
                    "raw_value": "100×200×300 mm",
                    "source_label": "产品尺寸",
                },
            }
        },
        raw_text=raw_text,
        fields=fields,
    )
    assert fabricated["matched"] == {}
    assert fabricated["missing_required"] == [
        "capacity_pot",
        "dishwasher_safe",
        "dimensions",
    ]


def test_operator_additional_spec_preserves_source_label_and_value_en() -> None:
    normalized = normalize_operator_structured_specs(
        {
            "source": {"platform": "operator"},
            "additional_specs": [
                {
                    "key": "capacity_pot",
                    "label": "主锅容量",
                    "label_en": "Main Pot Capacity",
                    "source_label": "锅体最大容积",
                    "value": "1.4",
                    "raw_value": "1.4升",
                    "unit": "L",
                }
            ],
        }
    )

    assert normalized is not None
    item = normalized["additional_specs"][0]
    assert item["source_label"] == "锅体最大容积"
    assert item["raw_value"] == "1.4升"
    assert item["value_en"] == "1.4"
    assert item["label_en"] == "Main Pot Capacity"


def test_operator_additional_specs_preserve_typed_normalized_values() -> None:
    normalized = normalize_operator_structured_specs(
        {
            "source": {"platform": "operator"},
            "additional_specs": [
                {
                    "key": "capacity_pot",
                    "label": "主锅容量",
                    "label_en": "Main Pot Capacity",
                    "value": 1.4,
                    "raw_value": "1.4升",
                    "source_label": "锅体最大容积",
                    "unit": "L",
                },
                {
                    "key": "dishwasher_safe",
                    "label": "可用洗碗机清洗",
                    "label_en": "Dishwasher Safe",
                    "value": False,
                    "raw_value": "否",
                    "source_label": "是否可机洗",
                },
            ],
        }
    )

    assert normalized is not None
    capacity, dishwasher_safe = normalized["additional_specs"]
    assert capacity["value"] == 1.4
    assert capacity["raw_value"] == "1.4升"
    assert dishwasher_safe["value"] is False
    assert dishwasher_safe["raw_value"] == "否"
    assert capacity["value_en"] == "1.4"
    assert dishwasher_safe["value_en"] == "No"
    assert [
        row["display_value"]
        for row in buyer_spec_rows(normalized, target_market="EU")
    ] == [
        "1.4",
        "No",
    ]


def test_operator_template_dimensions_keep_the_canonical_axis_shape() -> None:
    normalized = normalize_operator_structured_specs(
        {
            "source": {"platform": "operator"},
            "dimensions": {
                "value": "100 x 200 x 300",
                "raw_value": "100×200×300 mm",
                "source_label": "产品尺寸",
                "unit": "mm",
            },
        }
    )

    assert normalized is not None
    dimensions = normalized["dimensions"]
    assert "value" not in dimensions
    assert dimensions["unit"] == "cm"
    assert dimensions["length"]["value"] == 10
    assert dimensions["width"]["value"] == 20
    assert dimensions["height"]["value"] == 30
    assert dimensions["length"]["raw_value"] == "100×200×300 mm"
    assert dimensions["length"]["evidence"] == "operator_fact"


def test_p_gate_blocks_approved_template_with_missing_required(
    spec_template_db: Session,
) -> None:
    spec_template_db.add(
        KCategorySpecTemplate(
            category_tree="google",
            category_id="123",
            status="approved",
            fields_json=[_field()],
        )
    )
    spec_template_db.commit()

    assert assemble._required_spec_template_blockers(
        spec_template_db,
        _approved_product(),
    ) == ["类目规格必填未齐：capacity_pot"]


def test_p_gate_does_not_block_when_category_has_no_template(
    spec_template_db: Session,
) -> None:
    assert (
        assemble._required_spec_template_blockers(
            spec_template_db,
            _approved_product(),
        )
        == []
    )


def test_p_gate_fails_closed_when_template_query_raises(
    spec_template_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def query_failure(_db: Session, _product: object) -> list[str]:
        raise RuntimeError("template database unavailable")

    monkeypatch.setattr(assemble, "missing_required_for_product", query_failure)

    assert assemble._required_spec_template_blockers(
        spec_template_db,
        _approved_product(),
    ) == ["规格模板校验暂不可用"]


class _DraftDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, value: object) -> None:
        now = datetime.now(UTC)
        value.created_at = now
        value.updated_at = now


def test_draft_route_forces_ai_template_to_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _DraftDb()
    fields = [
        _field(
            key=f"field_{index}",
            label_zh=f"规格字段 {index}",
            label_en=f"Specification Field {index}",
            value_type="text",
            required=False,
            unit=None,
        )
        for index in range(8)
    ]
    monkeypatch.setattr(
        template_router,
        "_resolve_category_tree",
        lambda *args, **kwargs: (
            "google",
            {
                "id": "123",
                "name": "Cookware",
                "full_path": "Home > Kitchen > Cookware",
            },
        ),
    )
    monkeypatch.setattr(template_router, "get_spec_template", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        template_router,
        "_execution_context",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        template_router,
        "_execute_provider_json",
        lambda *args, **kwargs: {
            "status": "approved",
            "fields": fields,
        },
    )

    result = template_router.draft_category_spec_template(
        category_id="123",
        request=Request({"type": "http", "method": "POST", "path": "/"}),
        tree=None,
        db=db,  # type: ignore[arg-type]
        user=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert result.status == "draft"
    assert len(db.added) == 1
    assert isinstance(db.added[0], KCategorySpecTemplate)
    assert db.added[0].status == "draft"
    assert db.rollbacks == 1
    assert db.commits == 1


class _ParseDb:
    def __init__(self) -> None:
        self.rollbacks = 0
        self.add_calls = 0
        self.commit_calls = 0

    def rollback(self) -> None:
        self.rollbacks += 1

    def add(self, _value: object) -> None:
        self.add_calls += 1

    def commit(self) -> None:
        self.commit_calls += 1


def test_parse_route_returns_preview_without_persisting_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _ParseDb()
    original_specs = {"source": {"platform": "operator"}}
    product = _approved_product(structured_specs=original_specs.copy())
    template = SimpleNamespace(
        category_tree="google",
        category_id="123",
        fields_json=[_field()],
    )
    monkeypatch.setattr(template_router, "get_product", lambda *args, **kwargs: product)
    monkeypatch.setattr(template_router, "_scope_context", lambda _request: object())
    monkeypatch.setattr(
        template_router,
        "approved_template_for_product",
        lambda *args, **kwargs: template,
    )
    monkeypatch.setattr(
        template_router,
        "_execution_context",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        template_router,
        "_execute_provider_json",
        lambda *args, **kwargs: {
            "matched": {
                "capacity_pot": {
                    "value": 2.5,
                    "raw_value": "2.5 L",
                    "source_label": "主锅容量",
                }
            },
            "unmatched_lines": [],
            "missing_required": [],
        },
    )

    response = template_router.parse_product_specs_paste(
        product_id=product.id,
        payload=template_router.SpecsPasteRequest(raw_text="主锅容量\t2.5 L"),
        request=Request({"type": "http", "method": "POST", "path": "/"}),
        db=db,  # type: ignore[arg-type]
        user=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert response.matched["capacity_pot"].value == 2.5
    assert product.structured_specs_json == original_specs
    assert db.rollbacks == 1
    assert db.add_calls == 0
    assert db.commit_calls == 0
