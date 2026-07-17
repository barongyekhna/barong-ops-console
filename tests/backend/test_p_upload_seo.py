from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.modules.p_series.upload import assemble


pytestmark = pytest.mark.unit


def test_upload_seo_prefers_k_marketing_copy_meta_description() -> None:
    product = SimpleNamespace(
        seo_title_en="Legacy title",
        seo_description_en="Legacy description",
    )
    marketing_copy = {
        "seo": {
            "title": "  Authored K title  ",
            "meta_description": "  Sentences keep their intended spacing.  ",
            "description": "Compatibility description must not win.",
            "url_slug": "  compact-camp-stove  ",
        },
        "product_page_copy": {
            "short_description": "HTML-derived text must not become SEO metadata."
        },
    }

    seo = assemble._seo_for_upload(marketing_copy, product)

    assert seo.title == "Authored K title"
    assert seo.description == "Sentences keep their intended spacing."
    assert seo.url_slug == "compact-camp-stove"


def test_upload_seo_falls_back_safely_without_valid_generated_copy() -> None:
    product = SimpleNamespace(
        seo_title_en="  Legacy title  ",
        seo_description_en="  Legacy description  ",
    )

    seo = assemble._seo_for_upload(
        {"seo": {"title": {"invalid": True}, "meta_description": []}},
        product,
    )

    assert seo.title == "Legacy title"
    assert seo.description == "Legacy description"
    assert seo.url_slug is None


def test_n8n_writes_only_authored_seo_copy_to_yoast_product_meta() -> None:
    workflow_path = (
        Path(__file__).resolve().parents[2]
        / "backend/app/modules/p_series/n8n/p_upload_workflow.json"
    )
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    transform = next(
        node for node in workflow["nodes"] if node["name"] == "转 Woo 格式"
    )
    js_code = transform["parameters"]["jsCode"]

    assert "const seo = p.seo || {};" in js_code
    assert "typeof seo.meta_description === 'string'" in js_code
    assert ") ? seo.meta_description : seo.description;" in js_code
    assert (
        "body.meta_data.push({ key: '_yoast_wpseo_title', value: seoTitle });"
        in js_code
    )
    assert (
        "body.meta_data.push({ key: '_yoast_wpseo_metadesc', "
        "value: seoDescription });" in js_code
    )
    assert "typeof seo.url_slug === 'string'" in js_code
    assert "body.slug = seoUrlSlug;" in js_code
    assert "p.title" not in js_code.split(
        "// Woo permalink only accepts K's short SEO slug;", 1
    )[1].split("// 买家类目已由控制台确保；", 1)[0]

    seo_block = js_code.split("// K 的 SEO 文案是唯一 meta 来源；", 1)[1].split(
        "// 买家类目已由控制台确保；", 1
    )[0]
    assert "desc." not in seo_block
    assert "html.match" not in seo_block
    assert "replace(" not in seo_block
