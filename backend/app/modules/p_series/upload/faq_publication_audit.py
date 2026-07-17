"""Fail-safe post-publication audit for visible FAQ and FAQPage schema sync."""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlsplit

_MAX_PAGE_BYTES = 5_000_000
_SPACE = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]*>")
_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_Origin = tuple[str, str, int]


def _normalized_text(value: Any) -> str:
    plain = _TAG.sub(" ", unescape(str(value or "")))
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", plain)).strip().casefold()


def _url_origin(value: Any, *, label: str) -> _Origin:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{label} is not configured")
    parsed = urlsplit(raw)
    scheme = parsed.scheme.casefold()
    if (
        scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"{label} must be an http(s) origin without credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} contains an invalid port") from exc
    return scheme, parsed.hostname.casefold(), port or (443 if scheme == "https" else 80)


def _require_same_origin(
    value: Any,
    *,
    allowed_origin: _Origin,
    label: str,
) -> None:
    if _url_origin(value, label=label) != allowed_origin:
        raise ValueError(f"{label} must remain on the configured WordPress origin")


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject a redirect before urllib can fetch an off-origin location."""

    def __init__(self, allowed_origin: _Origin) -> None:
        super().__init__()
        self.allowed_origin = allowed_origin

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        _require_same_origin(
            newurl,
            allowed_origin=self.allowed_origin,
            label="published page redirect URL",
        )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PublishedFaqParser(HTMLParser):
    """Collect JSON-LD blocks plus text inside the deterministic ``kp-faq``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.visible_faq_text: list[str] = []
        self.jsonld_blocks: list[str] = []
        self._faq_depth = 0
        self._jsonld_parts: list[str] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.casefold()
        attrs_map = {str(key).casefold(): value or "" for key, value in attrs}
        if tag == "script":
            script_type = attrs_map.get("type", "").split(";", 1)[0].strip().casefold()
            if script_type == "application/ld+json":
                self._jsonld_parts = []
            return

        classes = {item.casefold() for item in attrs_map.get("class", "").split()}
        if self._faq_depth:
            if tag not in _VOID_ELEMENTS:
                self._faq_depth += 1
        elif "kp-faq" in classes:
            self._faq_depth = 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "script" and self._jsonld_parts is not None:
            self.jsonld_blocks.append("".join(self._jsonld_parts))
            self._jsonld_parts = None
            return
        if self._faq_depth and tag not in _VOID_ELEMENTS:
            self._faq_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._jsonld_parts is not None:
            self._jsonld_parts.append(data)
        elif self._faq_depth:
            self.visible_faq_text.append(data)


def _schema_types(value: Any) -> set[str]:
    raw = value.get("@type") if isinstance(value, dict) else None
    types = raw if isinstance(raw, list) else [raw]
    return {str(item).strip().casefold() for item in types if str(item or "").strip()}


def _answer_text(value: Any) -> str:
    candidates = value if isinstance(value, list) else [value]
    for candidate in candidates:
        if isinstance(candidate, dict):
            text = str(candidate.get("text") or "").strip()
            if text:
                return text
    return ""


def _faq_pairs(value: Any) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        if "faqpage" in _schema_types(node):
            entities = node.get("mainEntity")
            entities = entities if isinstance(entities, list) else [entities]
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                question = str(entity.get("name") or "").strip()
                answer = _answer_text(entity.get("acceptedAnswer"))
                if question:
                    pairs.append((question, answer))
        for nested in node.values():
            visit(nested)

    visit(value)
    # A plugin can expose the same graph in more than one JSON-LD block.  The
    # audit is about question membership, so duplicate pairs are immaterial.
    return list(dict.fromkeys(pairs))


def audit_published_faq_html(
    page_html: str,
    *,
    page_url: str | None = None,
) -> dict[str, Any]:
    """Assert every FAQPage question/answer is visible in the page FAQ block."""

    parser = _PublishedFaqParser()
    parser.feed(page_html)
    parser.close()
    visible = _normalized_text(" ".join(parser.visible_faq_text))
    pairs: list[tuple[str, str]] = []
    invalid_jsonld_blocks = 0
    for block in parser.jsonld_blocks:
        try:
            pairs.extend(_faq_pairs(json.loads(block)))
        except (TypeError, ValueError):
            invalid_jsonld_blocks += 1
    pairs = list(dict.fromkeys(pairs))

    missing: list[dict[str, Any]] = []
    for question, answer in pairs:
        missing_fields: list[str] = []
        if _normalized_text(question) not in visible:
            missing_fields.append("question")
        if answer and _normalized_text(answer) not in visible:
            missing_fields.append("answer")
        if missing_fields:
            missing.append(
                {
                    "question": question,
                    "missing_fields": missing_fields,
                }
            )

    return {
        "status": "mismatch" if missing else "passed",
        "ok": not missing,
        "page_url": page_url,
        "schema_faq_count": len(pairs),
        "visible_faq_present": bool(visible),
        "missing_from_visible": missing,
        "invalid_jsonld_blocks": invalid_jsonld_blocks,
    }


def audit_published_faq(
    page_url: str,
    *,
    allowed_base_url: str | None,
    timeout_seconds: float = 10.0,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Fetch a Woo product page and run the fail-safe FAQ/schema audit."""

    allowed_origin = _url_origin(
        allowed_base_url,
        label="WP_BASE_URL",
    )
    _require_same_origin(
        page_url,
        allowed_origin=allowed_origin,
        label="published page URL",
    )
    request = urllib.request.Request(
        page_url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Barong-P-FAQ-Audit/1.0",
        },
        method="GET",
    )
    open_url = opener or urllib.request.build_opener(
        _SameOriginRedirectHandler(allowed_origin)
    ).open
    with open_url(request, timeout=timeout_seconds) as response:
        response_url = (
            response.geturl()
            if callable(getattr(response, "geturl", None))
            else page_url
        )
        _require_same_origin(
            response_url,
            allowed_origin=allowed_origin,
            label="published page final URL",
        )
        raw = response.read(_MAX_PAGE_BYTES + 1)
        if len(raw) > _MAX_PAGE_BYTES:
            raise ValueError("published page exceeds FAQ audit size limit")
        headers = getattr(response, "headers", None)
        charset = headers.get_content_charset() if headers is not None else None
    return audit_published_faq_html(
        raw.decode(charset or "utf-8", errors="replace"),
        page_url=page_url,
    )
