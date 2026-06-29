from __future__ import annotations

import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.i_series.image_system.constants import (
    TARGET_ORGANIZATION_NAME,
)
from backend.app.modules.i_series.image_system.models import IImageAsset
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeVariant,
)


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c020000000b4944415478da63fcff1f0003030200efbfa7db0000000049454e44ae426082"
)


def _assert_fast(elapsed_ms: float, *, limit_ms: float, label: str) -> None:
    assert elapsed_ms < limit_ms, f"{label} took {elapsed_ms:.2f}ms, limit {limit_ms:.2f}ms"


def _request_json(
    client: TestClient,
    method: str,
    path: str,
    *,
    expected_status: int = 200,
    **kwargs,
) -> tuple[dict, float]:
    started = time.perf_counter()
    response = client.request(method, path, **kwargs)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert response.status_code == expected_status, response.text
    return response.json(), elapsed_ms


def _seed_target_owner() -> tuple[str, str]:
    username = f"ik_e2e_owner_{uuid4().hex[:10]}"
    password = "IK-E2E-Test-Only-Password-2026"
    org_id = f"org_{uuid4().hex}"
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role="owner",
            is_active=True,
            organization_id=org_id,
        )
        db.add(user)
        db.flush()
        organization = OrganizationRecord(
            org_id=org_id,
            org_name=TARGET_ORGANIZATION_NAME,
            org_type="store",
            owner_user_id=str(user.id),
            status="active",
            metadata_json={},
        )
        db.add(organization)
        db.flush()
        db.add(
            OrgMembershipRecord(
                membership_id=f"mem_{uuid4().hex}",
                user_id=str(user.id),
                org_id=org_id,
                role="owner",
                status="active",
            )
        )
        db.commit()
    return username, password


@pytest.mark.integration
def test_i_k_series_image_e2e_audit(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("I_IMAGE_ALLOW_LOCAL_FALLBACK", "1")
    monkeypatch.setenv("I_IMAGE_MEDIA_STORAGE_DIR", str(tmp_path / "i-media"))
    monkeypatch.setenv("K_PRODUCT_MEDIA_STORAGE_DIR", str(tmp_path / "k-media"))
    username, password = _seed_target_owner()

    login = auth_client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text

    prompt_transform_payload = {
        "prompt": "Clean ecommerce catalog image for a stainless steel pump.",
        "source_type": "generate",
        "style_config": {"background": "white", "lighting": "softbox"},
    }
    transformed_warm, _warm_transform_ms = _request_json(
        auth_client,
        "POST",
        "/api/app/i/prompts/transform",
        json=prompt_transform_payload,
    )
    assert transformed_warm["image_prompt_enhanced"]
    assert transformed_warm["provider"] == "local_fallback"

    transformed, transform_ms = _request_json(
        auth_client,
        "POST",
        "/api/app/i/prompts/transform",
        json=prompt_transform_payload,
    )
    assert (
        transformed["image_prompt_enhanced"]
        == transformed_warm["image_prompt_enhanced"]
    )
    assert transformed["provider"] == "local_fallback"
    _assert_fast(transform_ms, limit_ms=1500, label="I prompt transform")

    product_payload = {
        "raw_input_text": "Stainless steel transfer pump for B2B industrial buyers.",
        "main_keyword": "stainless steel transfer pump",
        "target_market": "US",
        "product_name_en": "IK E2E Stainless Pump",
        "product_type": "variable_product",
        "parent_sku": f"IK-E2E-{uuid4().hex[:8]}",
        "variants": [
            {"color": "silver", "size": "M", "function": "standard", "quantity": 10},
        ],
    }
    product, product_ms = _request_json(
        auth_client,
        "POST",
        "/api/app/k/products",
        json=product_payload,
        expected_status=201,
    )
    _assert_fast(product_ms, limit_ms=1500, label="K product create")
    product_id = product["id"]
    variant_id = product["variants"][0]["id"]

    generation_payload = {
        "prompt": "Stainless steel transfer pump on clean ecommerce background.",
        "style_config": {"background": "white", "composition": "centered"},
        "aspect_ratio": "1:1",
        "generation_count": 2,
        "origin_context": "k_handoff",
        "product_id": product_id,
        "variant_id": variant_id,
    }
    generated_warm, _warm_generate_ms = _request_json(
        auth_client,
        "POST",
        "/api/app/i/images/generate",
        json=generation_payload,
    )
    assert generated_warm["candidates"] and len(generated_warm["candidates"]) == 2

    generated, generate_ms = _request_json(
        auth_client,
        "POST",
        "/api/app/i/images/generate",
        json=generation_payload,
    )
    assert generated["candidates"] and len(generated["candidates"]) == 2
    assert [item["content_sha256"] for item in generated["candidates"]] == [
        item["content_sha256"] for item in generated_warm["candidates"]
    ]
    _assert_fast(
        generate_ms,
        limit_ms=2500,
        label="I K-context cached image generate",
    )

    edited_response = auth_client.post(
        "/api/app/i/images/edit",
        data={
            "prompt": "Keep the product identity and improve the catalog background.",
            "style_config": '{"background":"white","lighting":"balanced"}',
            "aspect_ratio": "1:1",
            "generation_count": "1",
            "origin_context": "i_direct",
        },
        files={"files": ("reference.png", PNG_1X1, "image/png")},
    )
    assert edited_response.status_code == 200, edited_response.text
    edited = edited_response.json()
    assert edited["candidates"] and edited["reference_image_count"] == 1

    saved, save_ms = _request_json(
        auth_client,
        "POST",
        "/api/app/i/media-library",
        json={
            "source_type": "generate",
            "prompt_original": "Direct I media save audit.",
            "image_prompt_enhanced": generated["image_prompt_enhanced"],
            "style_config": {"background": "white"},
            "aspect_ratio": "1:1",
            "images": generated["candidates"],
        },
        expected_status=201,
    )
    assert saved["count"] == 2
    _assert_fast(save_ms, limit_ms=3000, label="I save media library")
    media_asset_id = saved["items"][0]["id"]
    assert saved["items"][0]["thumbnail_url"].endswith("/thumbnail")
    assert saved["items"][0]["preview_url"].endswith("/preview")
    assert saved["items"][0]["file_url"].endswith("/file")

    media_list, list_ms = _request_json(
        auth_client,
        "GET",
        "/api/app/i/media-library?limit=50",
    )
    assert media_list["count"] >= 2
    assert len(media_list["items"]) >= 2
    _assert_fast(list_ms, limit_ms=1000, label="I media library list")

    for suffix, max_ms in (("thumbnail", 1500), ("preview", 2000), ("file", 1500)):
        started = time.perf_counter()
        response = auth_client.get(f"/api/app/i/media-library/{media_asset_id}/{suffix}")
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"\x89PNG") or response.headers.get(
            "content-type", ""
        ).startswith("image/")
        _assert_fast(elapsed_ms, limit_ms=max_ms, label=f"I media {suffix}")

    imported, import_ms = _request_json(
        auth_client,
        "POST",
        f"/api/app/k/products/{product_id}/images/import-i-output",
        json={
            "variant_id": variant_id,
            "source_type": "generate",
            "image_prompt_enhanced": generated["image_prompt_enhanced"],
            "prompt_original": "Imported from I E2E audit.",
            "aspect_ratio": "1:1",
            "style_config": {"background": "white"},
            "event_id": generated["event_id"],
            "images": generated["candidates"],
        },
        expected_status=201,
    )
    assert imported["asset_ids"]
    _assert_fast(import_ms, limit_ms=3000, label="K import I output")
    k_asset_id = imported["asset_ids"][0]

    k_media, k_list_ms = _request_json(
        auth_client,
        "GET",
        f"/api/app/k/media?product_id={product_id}&limit=20",
    )
    assert k_media["count"] >= 2
    assert any(item["id"] == k_asset_id for item in k_media["items"])
    _assert_fast(k_list_ms, limit_ms=1000, label="K media list")

    for suffix, max_ms in (("thumbnail", 1500), ("preview", 2000), ("file", 1500)):
        started = time.perf_counter()
        response = auth_client.get(f"/api/app/k/media/{k_asset_id}/{suffix}")
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert response.status_code == 200, response.text
        assert response.content
        assert response.headers.get("cache-control")
        _assert_fast(elapsed_ms, limit_ms=max_ms, label=f"K media {suffix}")

    download, _download_ms = _request_json(
        auth_client,
        "GET",
        f"/api/app/k/media/{k_asset_id}/download",
    )
    assert download["original_url"].endswith(f"/k/media/{k_asset_id}/file")

    deleted, delete_ms = _request_json(
        auth_client,
        "DELETE",
        f"/api/app/i/media-library/{media_asset_id}",
    )
    assert deleted["status"] == "removed"
    _assert_fast(delete_ms, limit_ms=1000, label="I media delete")

    with SessionLocal() as db:
        i_rows = list(db.scalars(select(IImageAsset)))
        assert i_rows
        assert all(row.storage_provider == "local_filesystem" for row in i_rows)
        assert all(row.content_bytes is None for row in i_rows)
        for row in i_rows:
            metadata = row.metadata_json or {}
            if row.status != "REMOVED":
                assert Path(metadata["storage_path"]).is_file()
                assert Path(metadata["thumbnail_path"]).is_file()
                assert Path(metadata["preview_path"]).is_file()

        k_product = db.get(KProductKnowledgeProduct, UUID(product_id))
        assert k_product is not None
        assert k_product.image_asset_status == "bound"
        assert k_product.media_notes_json["original_url"].endswith("/file")
        k_variant = db.get(KProductKnowledgeVariant, UUID(variant_id))
        assert k_variant is not None
        k_rows = list(
            db.scalars(
                select(KProductKnowledgeMediaAsset).where(
                    KProductKnowledgeMediaAsset.product_id == UUID(product_id)
                )
            )
        )
        assert k_rows
        assert all(row.storage_provider == "local_filesystem" for row in k_rows)
        assert all("db_content_base64" not in (row.metadata_json or {}) for row in k_rows)
        for row in k_rows:
            metadata = row.metadata_json or {}
            assert Path(metadata["storage_path"]).is_file()
            assert Path(metadata["thumbnail_path"]).is_file()
            assert Path(metadata["preview_path"]).is_file()
