from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.app.modules.cs_series.service import (
    InboundValidationError,
    inbound_rate_limiter,
    normalize_inbound,
    plain_text,
    reset_inbound_rate_limiter,
)


pytestmark = pytest.mark.unit


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "channel": "retail",
        "name": "Alice",
        "email": "alice@example.com",
        "company": "",
        "order_number": "ORDER-1",
        "message": "Please help with my order.",
        "source_url": "https://shop.example.com/contact",
        "honeypot": "",
        "form_ms": 5000,
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _reset_limiter_for_each_test() -> Iterator[None]:
    reset_inbound_rate_limiter()
    yield
    reset_inbound_rate_limiter()


def test_plain_text_removes_html_unsafe_content_and_nuls() -> None:
    assert plain_text("<b>Alice</b>\x00   Smith") == "Alice Smith"
    assert plain_text(
        "<p>First line</p><script>alert('x')</script>"
        "<style>.hidden { display:none }</style><p>Second<br>third</p>",
        multiline=True,
    ) == "First line\n\nSecond\nthird"


def test_normalize_inbound_stores_clean_plain_text_fields() -> None:
    normalized = normalize_inbound(
        _valid_payload(
            name=" <strong>Alice</strong> ",
            company="<em>Example &amp; Co.</em>",
            order_number="<span>ORDER-2</span>",
            message="<p>Hello <b>support</b>.</p><script>bad()</script>",
        )
    )

    assert normalized.name == "Alice"
    assert normalized.company == "Example & Co."
    assert normalized.order_number == "ORDER-2"
    assert normalized.message == "Hello support."


@pytest.mark.parametrize(
    "email",
    [
        "missing-at.example.com",
        "a@localhost",
        ".alice@example.com",
        "alice..ops@example.com",
        "alice @example.com",
        "alice@-example.com",
    ],
)
def test_normalize_inbound_rejects_invalid_email(email: str) -> None:
    with pytest.raises(InboundValidationError):
        normalize_inbound(_valid_payload(email=email))


@pytest.mark.parametrize("channel", ["", "all", "Retail", "b2b"])
def test_normalize_inbound_rejects_invalid_channel(channel: str) -> None:
    with pytest.raises(InboundValidationError):
        normalize_inbound(_valid_payload(channel=channel))


@pytest.mark.parametrize(
    "message",
    ["", "   \n\t ", "<script>onlyUnsafeContent()</script>", "x" * 5001],
)
def test_normalize_inbound_rejects_empty_or_oversized_message(message: str) -> None:
    with pytest.raises(InboundValidationError):
        normalize_inbound(_valid_payload(message=message))


@pytest.mark.parametrize(
    ("form_ms", "expected_status"),
    [(2999, "spam"), (3000, "new")],
)
def test_form_completion_time_boundary(
    form_ms: int,
    expected_status: str,
) -> None:
    assert normalize_inbound(_valid_payload(form_ms=form_ms)).status == expected_status


def test_rate_limiter_allows_five_per_minute_and_rejects_sixth() -> None:
    assert all(
        inbound_rate_limiter.allow("203.0.113.10", now=100.0)
        for _ in range(5)
    )
    assert inbound_rate_limiter.allow("203.0.113.10", now=100.0) is False


def test_rate_limiter_allows_twenty_per_hour_and_rejects_twenty_first() -> None:
    # Space attempts beyond the minute window so only the hourly limit applies.
    assert all(
        inbound_rate_limiter.allow("203.0.113.20", now=index * 61.0)
        for index in range(20)
    )
    assert inbound_rate_limiter.allow("203.0.113.20", now=20 * 61.0) is False
