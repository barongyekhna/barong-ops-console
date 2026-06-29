import pytest
import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import LargeBinary
from uuid import uuid4

from backend.app.modules.i_series.image_system.constants import (
    MAX_EDIT_REFERENCE_IMAGES,
    MAX_GENERATION_COUNT,
    SOURCE_GENERATE,
)
from backend.app.modules.i_series.image_system.models import IImageAsset
from backend.app.modules.i_series.image_system.prompt_skills import (
    image_prompt_skill_instruction,
)
from backend.app.modules.i_series.image_system.schemas import (
    ImageGenerationRequest,
    ImageSaveItem,
    MediaLibrarySaveRequest,
    PromptTransformRequest,
)
from backend.app.modules.i_series.image_system.service import (
    IImagePromptEngine,
    IImageModelEngine,
    _IMAGE_GENERATION_CACHE,
    _PROMPT_TRANSFORM_CACHE,
    decode_image_base64,
    deterministic_png,
    encode_image_base64,
    image_dimensions_from_png,
    provider_url,
    sha256_hex,
    validate_image_bytes,
)


def test_i_generated_candidate_png_is_valid_base64_image() -> None:
    contents = deterministic_png(320, 240, "yellow product on white background")
    encoded = encode_image_base64(contents)

    decoded = decode_image_base64(encoded)

    assert decoded == contents
    assert validate_image_bytes(decoded, "image/png") == "image/png"
    assert image_dimensions_from_png(decoded) == (320, 240)
    assert sha256_hex(decoded) == sha256_hex(contents)


def test_i_media_library_rejects_k_handoff_save() -> None:
    contents = deterministic_png(64, 64, "candidate")
    item = ImageSaveItem(
        image_base64=encode_image_base64(contents),
        mime_type="image/png",
        width=64,
        height=64,
        content_sha256=sha256_hex(contents),
    )

    with pytest.raises(ValueError):
        MediaLibrarySaveRequest(
            source_type=SOURCE_GENERATE,
            image_prompt_enhanced="A clean product catalog image.",
            origin_context="k_handoff",
            images=[item],
        )


def test_i_k_handoff_generation_requires_product_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ImageGenerationRequest(
            prompt="Create a clean product image.",
            origin_context="k_handoff",
        )

    assert "product_id" in str(exc_info.value)


def test_i_media_library_limits_final_saved_candidates() -> None:
    contents = deterministic_png(64, 64, "candidate")
    item = ImageSaveItem(
        image_base64=encode_image_base64(contents),
        mime_type="image/png",
        width=64,
        height=64,
        content_sha256=sha256_hex(contents),
    )

    with pytest.raises(ValidationError):
        MediaLibrarySaveRequest(
            source_type=SOURCE_GENERATE,
            image_prompt_enhanced="A clean product catalog image.",
            images=[item] * (MAX_GENERATION_COUNT + 1),
        )


def test_i_image_assets_use_optional_binary_content_for_file_first_storage() -> None:
    content_column = IImageAsset.__table__.c.content_bytes

    assert content_column.nullable is True
    assert isinstance(content_column.type, LargeBinary)


def test_i_edit_reference_image_limit_is_ten() -> None:
    assert MAX_EDIT_REFERENCE_IMAGES == 10


def test_i_prompt_skill_blocks_reference_image_persistence() -> None:
    instruction = image_prompt_skill_instruction().lower()

    assert "reference images" in instruction
    assert "never ask to" in instruction
    assert "persist reference images" in instruction


def test_i_provider_url_joins_4sapi_suffix_without_duplicate_v1() -> None:
    assert (
        provider_url("https://api.4sapi.example", "/v1/images/generations")
        == "https://api.4sapi.example/v1/images/generations"
    )
    assert (
        provider_url("https://api.4sapi.example/v1", "/v1/images/edits")
        == "https://api.4sapi.example/v1/images/edits"
    )


def test_i_provider_response_becomes_image_candidate() -> None:
    contents = deterministic_png(64, 64, "provider-output")
    engine = IImageModelEngine(db=None)  # type: ignore[arg-type]

    candidates = engine._candidates_from_provider_response(
        response_payload={"data": [{"b64_json": encode_image_base64(contents)}]},
        source_type=SOURCE_GENERATE,
        image_prompt_enhanced="A clean product image.",
        requested_width=64,
        requested_height=64,
        endpoint="/v1/images/generations",
        generation_count=1,
        reference_image_count=0,
    )

    assert len(candidates) == 1
    assert candidates[0].metadata["model"] == "gpt-image-2"
    assert candidates[0].metadata["provider"] == "4sapi"
    assert candidates[0].metadata["endpoint"] == "/v1/images/generations"
    assert decode_image_base64(candidates[0].image_base64) == contents


def test_i_image_provider_request_does_not_send_unsupported_response_format() -> None:
    source = IImageModelEngine.generate_candidates.__code__.co_consts

    assert "response_format" not in source


def test_i_image_provider_error_exposes_sanitized_provider_message() -> None:
    engine = IImageModelEngine(db=None)  # type: ignore[arg-type]
    response = httpx.Response(
        400,
        json={
            "error": {
                "message": "Unknown parameter: 'response_format'.",
                "type": "invalid_request_error",
            }
        },
        request=httpx.Request("POST", "https://4sapi.example/v1/images/generations"),
    )

    with pytest.raises(HTTPException) as exc_info:
        engine._raise_provider_error(
            endpoint="/v1/images/generations",
            exc=httpx.HTTPStatusError(
                "bad request",
                request=response.request,
                response=response,
            ),
            response=response,
        )

    assert exc_info.value.status_code == 502
    assert "Unknown parameter" in exc_info.value.detail["message"]
    assert (
        exc_info.value.detail["details"]["provider_error"]
        == "Unknown parameter: 'response_format'."
    )


def test_i_image_provider_releases_open_db_transaction_before_http_call() -> None:
    class FakeSession:
        commits = 0
        rollbacks = 0

        def in_transaction(self) -> bool:
            return True

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

    session = FakeSession()
    engine = IImageModelEngine(db=session)  # type: ignore[arg-type]

    engine._release_db_transaction()

    assert session.commits == 1
    assert session.rollbacks == 0


def test_i_prompt_transform_uses_prompt_hash_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("I_IMAGE_ALLOW_LOCAL_FALLBACK", "1")
    _PROMPT_TRANSFORM_CACHE.clear()
    payload = PromptTransformRequest(
        prompt="Create a clean product image.",
        source_type=SOURCE_GENERATE,
        style_config={"background": "white"},
    )
    engine = IImagePromptEngine(db=None)  # type: ignore[arg-type]

    first = engine.transform(
        payload=payload,
        request=None,  # type: ignore[arg-type]
        user=None,  # type: ignore[arg-type]
    )

    def fail_local_fallback(_payload: PromptTransformRequest) -> str:
        raise AssertionError("prompt cache miss")

    monkeypatch.setattr(
        "backend.app.modules.i_series.image_system.service.local_enhanced_prompt",
        fail_local_fallback,
    )
    second = engine.transform(
        payload=payload,
        request=None,  # type: ignore[arg-type]
        user=None,  # type: ignore[arg-type]
    )

    assert second == first


def test_i_image_generation_cache_returns_cached_image_without_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("I_IMAGE_ALLOW_LOCAL_FALLBACK", "1")
    _IMAGE_GENERATION_CACHE.clear()
    engine = IImageModelEngine(db=None)  # type: ignore[arg-type]

    first = engine.generate_candidates(
        event_id=uuid4(),
        source_type=SOURCE_GENERATE,
        image_prompt_enhanced="Professional ecommerce image prompt.",
        aspect_ratio="1:1",
        generation_count=1,
        request=None,  # type: ignore[arg-type]
        user=None,  # type: ignore[arg-type]
        style_config={"background": "white"},
    )

    def fail_local_candidates(**_kwargs):
        raise AssertionError("image cache miss")

    monkeypatch.setattr(engine, "_local_candidates", fail_local_candidates)
    second = engine.generate_candidates(
        event_id=uuid4(),
        source_type=SOURCE_GENERATE,
        image_prompt_enhanced="Professional ecommerce image prompt.",
        aspect_ratio="1:1",
        generation_count=1,
        request=None,  # type: ignore[arg-type]
        user=None,  # type: ignore[arg-type]
        style_config={"background": "white"},
    )

    assert second[0].content_sha256 == first[0].content_sha256
    assert second[0].image_base64 == first[0].image_base64
    assert second[0].candidate_id != first[0].candidate_id
