"""Deterministic evidence guards for customer-facing PDP claims."""

from __future__ import annotations

import html
import re
from typing import Any


_TITLE_SEPARATORS = re.compile(r"\s*(?:\||—|–|•|:)\s*")
_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_UNTRUSTED_IDENTITY_CLAIMS = {
    "windproof",
    "waterproof",
    "safe",
    "safety",
    "indoor",
    "indoors",
    "home",
    "durable",
    "lightweight",
    "compact",
    "certified",
    "guaranteed",
}

# Concrete set components are claims, not harmless category language.  A legacy
# supplier title may say "kettle" (or "7-piece") even when no reviewed package
# list/spec proves it, so those terms need a deterministic boundary in addition
# to prompt instructions.
_COMPONENT_ALIASES: dict[str, tuple[str, ...]] = {
    "kettle": ("kettle", "kettles", "tea kettle", "tea kettles", "teakettle"),
    "teapot": ("teapot", "teapots"),
    "pot": ("pot", "pots", "saucepan", "saucepans", "stockpot", "stockpots"),
    "pan": ("pan", "pans", "skillet", "skillets", "frying pan", "frying pans"),
    "steamer": (
        "steamer",
        "steamers",
        "steamer basket",
        "steamer baskets",
        "steaming basket",
        "steaming baskets",
    ),
    "bowl": ("bowl", "bowls"),
    "plate": ("plate", "plates"),
    "cup": ("cup", "cups", "mug", "mugs"),
    "lid": ("lid", "lids"),
    "spoon": ("spoon", "spoons"),
    "fork": ("fork", "forks"),
    "knife": ("knife", "knives"),
    "tongs": ("tongs", "kitchen tongs", "serving tongs"),
    "cutting_board": (
        "cutting board",
        "cutting boards",
        "chopping board",
        "chopping boards",
    ),
}
_SMALL_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS_NUMBER_WORDS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_ONES_WORD_PATTERN = "|".join(tuple(_SMALL_NUMBER_WORDS)[1:10])
_NUMBER_WORD_PATTERN = "|".join(
    (
        *tuple(_SMALL_NUMBER_WORDS),
        rf"(?:{'|'.join(_TENS_NUMBER_WORDS)})(?:[- ](?:{_ONES_WORD_PATTERN}))?",
    )
)
_CLAIM_COUNT_PATTERN = rf"(?:\d+|{_NUMBER_WORD_PATTERN})"
_PIECE_CLAIM = re.compile(
    rf"""
    \b(?:
        (?P<piece_count>{_CLAIM_COUNT_PATTERN})
        \s*(?:-|\s)?\s*(?:piece|pieces|pc|pcs)\b(?:\s+set\b)?
        |
        set\s+of\s+(?P<set_count>{_CLAIM_COUNT_PATTERN})\b
        (?:\s*(?:-|\s)?\s*(?:piece|pieces|pc|pcs)\b)?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _piece_claim_count(match: re.Match[str]) -> int:
    raw = (match.group("piece_count") or match.group("set_count") or "").casefold()
    if raw.isdigit():
        return int(raw)
    parts = re.split(r"[- ]", raw)
    if len(parts) == 1:
        return _SMALL_NUMBER_WORDS.get(raw, _TENS_NUMBER_WORDS.get(raw, -1))
    return _TENS_NUMBER_WORDS.get(parts[0], 0) + _SMALL_NUMBER_WORDS.get(parts[1], 0)


def canonical_package_includes(
    package_includes: Any,
    structured_specs: dict[str, Any] | None = None,
) -> list[str]:
    """Return the reviewed package list, with a supplier-spec fallback.

    K's product column is canonical.  ``structured_specs.package_includes`` is
    retained as a compatibility path for newly imported supplier evidence.
    """

    raw = package_includes
    if not isinstance(raw, list) and isinstance(structured_specs, dict):
        raw = structured_specs.get("package_includes")
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = re.sub(r"\s+", " ", html.unescape(str(item or ""))).strip()
        key = text.casefold()
        if text and key not in seen:
            output.append(text)
            seen.add(key)
    return output


def _component_evidence_text(
    package_includes: list[str], structured_specs: dict[str, Any] | None
) -> str:
    evidence: list[str] = [*package_includes]

    def visit(value: Any, *, key: str = "") -> None:
        if isinstance(value, dict):
            for nested_key, nested in value.items():
                if nested_key in {"source", "url", "source_url"}:
                    continue
                evidence.append(str(nested_key))
                visit(nested, key=str(nested_key))
        elif isinstance(value, list):
            for nested in value:
                visit(nested, key=key)
        elif key in {"label", "label_en", "source_label", "component", "name"}:
            evidence.append(str(value or ""))

    visit(structured_specs or {})
    return " ".join(evidence).casefold()


def unsupported_component_terms(
    value: Any,
    *,
    package_includes: Any = None,
    structured_specs: dict[str, Any] | None = None,
) -> list[str]:
    """List concrete component families mentioned without component evidence."""

    text = html.unescape(str(value or "")).casefold()
    includes = canonical_package_includes(package_includes, structured_specs)
    evidence = _component_evidence_text(includes, structured_specs)
    unsupported: list[str] = []
    for component, aliases in _COMPONENT_ALIASES.items():
        mentioned = any(
            re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text)
            for alias in aliases
        )
        supported = any(
            re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", evidence)
            for alias in aliases
        )
        if mentioned and not supported:
            unsupported.append(component)
    return unsupported


def package_claim_error(
    value: Any,
    *,
    package_includes: Any = None,
    structured_specs: dict[str, Any] | None = None,
) -> str | None:
    """Validate component names and N-piece claims against the reviewed list."""

    unsupported = unsupported_component_terms(
        value,
        package_includes=package_includes,
        structured_specs=structured_specs,
    )
    if unsupported:
        return "Unsupported package component(s): " + ", ".join(unsupported)
    includes = canonical_package_includes(package_includes, structured_specs)
    for match in _PIECE_CLAIM.finditer(str(value or "")):
        claimed = _piece_claim_count(match)
        if not includes:
            return f"{claimed}-piece claim requires a reviewed package_includes list."
        if claimed != len(includes):
            return (
                f"{claimed}-piece claim does not match package_includes count "
                f"({len(includes)})."
            )
    return None


def _remove_unsupported_component_sentences(
    value: str,
    *,
    package_includes: list[str],
    structured_specs: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    pieces = re.split(r"(?<=[.!?])\s+", value)
    kept: list[str] = []
    removed: list[str] = []
    for piece in pieces:
        unsupported = unsupported_component_terms(
            piece,
            package_includes=package_includes,
            structured_specs=structured_specs,
        )
        if unsupported:
            removed.extend(unsupported)
        else:
            kept.append(piece)
    return " ".join(kept).strip(), sorted(set(removed))


def _downgrade_unverified_piece_claims(value: str, package_count: int) -> str:
    def replace(match: re.Match[str]) -> str:
        claimed = _piece_claim_count(match)
        return match.group(0) if package_count and claimed == package_count else "set"

    output = _PIECE_CLAIM.sub(replace, value)
    output = re.sub(r"\bset\s+set\b", "set", output, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", output).strip()


def enforce_package_evidence_consistency(
    result: dict[str, Any],
    *,
    package_includes: Any = None,
    structured_specs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Strip ghost components and downgrade unverifiable N-piece wording.

    Only customer-facing copy surfaces are traversed.  Evidence references and
    internal audit fields remain byte-for-byte intact.
    """

    output = dict(result)
    includes = canonical_package_includes(package_includes, structured_specs)
    removed: list[dict[str, Any]] = []
    downgraded: list[str] = []

    def sanitize(value: Any, path: str) -> Any:
        if isinstance(value, dict):
            return {
                key: sanitize(nested, f"{path}.{key}" if path else str(key))
                for key, nested in value.items()
            }
        if isinstance(value, list):
            cleaned_items = [sanitize(item, f"{path}[{index}]") for index, item in enumerate(value)]
            return [item for item in cleaned_items if item not in (None, "", [], {})]
        if not isinstance(value, str):
            return value
        piece_safe = _downgrade_unverified_piece_claims(value, len(includes))
        if piece_safe != re.sub(r"\s+", " ", value).strip():
            downgraded.append(path)
        component_safe, terms = _remove_unsupported_component_sentences(
            piece_safe,
            package_includes=includes,
            structured_specs=structured_specs,
        )
        if terms:
            removed.append({"path": path, "components": terms})
        return component_safe

    for key in (
        "listing_copy",
        "a_plus_outline",
        "product_page_copy",
        "page_faq",
        "json_ld",
        "seo",
    ):
        if key in output:
            output[key] = sanitize(output[key], key)
    output["package_evidence_consistency"] = {
        "status": "sanitized" if removed or downgraded else "passed",
        "package_count": len(includes),
        "removed_unsupported_components": removed,
        "downgraded_piece_claim_paths": sorted(set(downgraded)),
    }
    return output


def _claim_tokens(value: Any) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN.findall(html.unescape(str(value or "")))
        if token.casefold() not in _STOPWORDS
    }


def _flatten_text(value: Any) -> list[str]:
    if isinstance(value, dict):
        texts: list[str] = []
        for key, nested in value.items():
            if key in {"source", "url", "platform"}:
                continue
            texts.extend(_flatten_text(nested))
        return texts
    if isinstance(value, list):
        texts: list[str] = []
        for nested in value:
            texts.extend(_flatten_text(nested))
        return texts
    if value is None or isinstance(value, bool):
        return []
    return [str(value)]


def title_evidence_corpus(
    *,
    product_name: str | None,
    product_type: str | None,
    site_brand: str,
    approved_selling_points: dict[str, Any],
    structured_specs: dict[str, Any] | None,
    package_includes: Any = None,
) -> set[str]:
    # Identity text is needed to retain the product noun, but legacy names may
    # themselves contain unsupported modifiers. Never let those modifiers
    # self-prove merely because they appeared in the old title.
    includes = canonical_package_includes(package_includes, structured_specs)
    identity = _downgrade_unverified_piece_claims(
        f"{product_name or ''} {product_type or ''}", len(includes)
    )
    identity_tokens = _claim_tokens(identity)
    tokens = identity_tokens - _UNTRUSTED_IDENTITY_CLAIMS
    unsupported_identity_components = unsupported_component_terms(
        f"{product_name or ''} {product_type or ''}",
        package_includes=package_includes,
        structured_specs=structured_specs,
    )
    for component in unsupported_identity_components:
        for alias in _COMPONENT_ALIASES[component]:
            tokens.difference_update(_claim_tokens(alias))
    tokens.update(_claim_tokens(site_brand))
    texts: list[str] = []
    for bullet in approved_selling_points.get("bullets") or []:
        if isinstance(bullet, dict) and bullet.get("verification_status") == "verified":
            texts.append(str(bullet.get("text") or ""))
    texts.extend(_flatten_text(structured_specs or {}))
    texts.extend(includes)
    for text in texts:
        tokens.update(_claim_tokens(text))
    return tokens


def _neutral_fallback(
    product_name: str | None,
    product_type: str | None,
    *,
    package_includes: Any = None,
    structured_specs: dict[str, Any] | None = None,
) -> str:
    original = re.sub(
        r"\s+", " ", html.unescape(str(product_name or product_type or "Product"))
    ).strip()
    includes = canonical_package_includes(package_includes, structured_specs)
    original = _downgrade_unverified_piece_claims(original, len(includes))
    unsupported = unsupported_component_terms(
        original,
        package_includes=includes,
        structured_specs=structured_specs,
    )
    unsupported_tokens = {
        token
        for component in unsupported
        for alias in _COMPONENT_ALIASES[component]
        for token in _claim_tokens(alias)
    }
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&'/-]*", original)
    kept = [
        word
        for word in words
        if word.casefold().strip("-/") not in _UNTRUSTED_IDENTITY_CLAIMS
        and word.casefold().strip("-/") not in unsupported_tokens
    ]
    return " ".join(kept).strip() or "Product"


def project_approved_selling_points(
    result: dict[str, Any],
    approved_selling_points: list[dict[str, Any]],
) -> dict[str, Any]:
    """Make customer-facing bullet grids an exact projection of approvals."""

    output = dict(result)
    approved_text = [
        re.sub(r"\s+", " ", html.unescape(str(item.get("text") or ""))).strip()
        for item in approved_selling_points
        if isinstance(item, dict)
        and item.get("verification_status") == "verified"
        and str(item.get("text") or "").strip()
    ]
    if isinstance(output.get("product_page_copy"), dict):
        product_page_copy = dict(output["product_page_copy"])
        product_page_copy["key_bullets"] = approved_text
        output["product_page_copy"] = product_page_copy
    if isinstance(output.get("listing_copy"), dict):
        listing_copy = dict(output["listing_copy"])
        listing_copy["bullet_points"] = approved_text
        output["listing_copy"] = listing_copy
    output["selling_points_projection"] = {
        "source": "selling_points_approved",
        "count": len(approved_text),
        "exact": True,
    }
    return output


def _supported_title(
    value: Any,
    *,
    corpus: set[str],
    fallback: str,
) -> tuple[str, list[str]]:
    clean = re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()
    if not clean:
        return fallback, []
    kept: list[str] = []
    removed: list[str] = []
    for segment in [part.strip() for part in _TITLE_SEPARATORS.split(clean) if part.strip()]:
        tokens = _claim_tokens(segment)
        if tokens and tokens.issubset(corpus):
            kept.append(segment)
        else:
            removed.append(segment)
    return (" | ".join(kept) if kept else fallback), removed


def enforce_title_evidence_consistency(
    result: dict[str, Any],
    *,
    product_name: str | None,
    product_type: str | None,
    site_brand: str,
    approved_selling_points: dict[str, Any],
    structured_specs: dict[str, Any] | None,
    package_includes: Any = None,
) -> dict[str, Any]:
    """Remove unsupported SEO/H1 claim segments and decode HTML entities."""

    output = dict(result)
    seo = dict(output.get("seo") or {})
    fallback = _neutral_fallback(
        product_name,
        product_type,
        package_includes=package_includes,
        structured_specs=structured_specs,
    )
    corpus = title_evidence_corpus(
        product_name=product_name,
        product_type=product_type,
        site_brand=site_brand,
        approved_selling_points=approved_selling_points,
        structured_specs=structured_specs,
        package_includes=package_includes,
    )
    removed: dict[str, list[str]] = {}
    for field in ("title", "h1"):
        clean, dropped = _supported_title(
            seo.get(field), corpus=corpus, fallback=fallback
        )
        seo[field] = clean
        if dropped:
            removed[field] = dropped
    output["seo"] = seo
    output["evidence_consistency"] = {
        "status": "sanitized" if removed else "passed",
        "removed_unsupported_title_segments": removed,
        "approved_selling_points_only": True,
    }
    return output
