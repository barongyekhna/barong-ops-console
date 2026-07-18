"""Deterministic evidence guards for customer-facing PDP claims."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .buyer_display import imperial_measurement


_TITLE_SEPARATORS = re.compile(r"\s*(?:\||—|–|•|:)\s*")
_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_SUPPLIER_MODEL_HYPHENATED = re.compile(
    r"(?<![a-z0-9-])(?:[a-z]{2,}[-_]\d[a-z0-9_-]*)(?![a-z0-9])",
    re.IGNORECASE,
)
_SUPPLIER_MODEL_COMPACT = re.compile(
    r"(?<![A-Za-z0-9])[A-Z]{2,}\d{3,}[A-Z0-9-]*(?![A-Za-z0-9])"
)
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


class TitleEvidenceConsistencyError(ValueError):
    """Raised when neither generated title copy nor product identity is usable."""


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
_NON_PIECE_SET_NOUN_PATTERN = (
    r"(?:sizes?|colors?|colours?|styles?|options?|models?|variants?|settings?)"
)
_PIECE_CLAIM = re.compile(
    rf"""
    (?<![A-Za-z0-9.+])(?:
        (?P<piece_count>{_CLAIM_COUNT_PATTERN})
        \s*(?:-|\s)?\s*(?:piece|pieces|pc|pcs)\b(?:\s+set\b)?
        |
        set\s+of\s+(?P<set_count>{_CLAIM_COUNT_PATTERN})\b
        (?!\s+{_NON_PIECE_SET_NOUN_PATTERN}\b)
        (?:\s*(?:-|\s)?\s*(?:piece|pieces|pc|pcs)\b)?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_NUMERIC_ATOM_PATTERN = r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
_NUMERIC_RANGE_SEPARATOR_PATTERN = r"(?:-|\u2013|\u2014|~|\uff5e|\u81f3|\u5230|to)"
_NUMERIC_RANGE_PATTERN = (
    rf"{_NUMERIC_ATOM_PATTERN}(?:\s*{_NUMERIC_RANGE_SEPARATOR_PATTERN}\s*"
    rf"{_NUMERIC_ATOM_PATTERN})?"
)
_PEOPLE_CLAIM = re.compile(
    rf"(?<![A-Za-z0-9.+])"
    rf"(?P<prefix>(?:(?:suitable|designed|ideal)\s+for|for)\s+)?"
    rf"(?P<count>{_NUMERIC_RANGE_PATTERN})"
    rf"(?P<separator>\s*-\s*|\s+)(?P<noun>people|persons?)(?![A-Za-z])",
    re.IGNORECASE,
)
_CHINESE_PEOPLE_CLAIM = re.compile(
    rf"(?<![A-Za-z0-9.+])"
    rf"(?P<prefix>\u9002\u7528\u4e8e?|\u9002\u5408\u4e8e?|\u53ef\u4f9b|\u4f9b)?"
    rf"(?P<count>{_NUMERIC_RANGE_PATTERN})\s*\u4eba"
    rf"(?P<suffix>\u4f7f\u7528(?:\u7684)?|\u7528|\u4efd)?"
)
_CHINESE_PIECE_CLAIM = re.compile(
    r"(?<![A-Za-z0-9.+])(?P<count>\d+)\s*\u4ef6"
    r"(?!(?:\u5957\u88c5?|\u88c5)?(?:\u4ee3\u53d1|\u8d77\u6279|\u8d77\u552e|\u6df7\u6279|\u53ef\u552e|\u5305\u90ae))"
    r"(?P<suffix>\u5957\u88c5?|\u88c5)?"
)
_CAPACITY_CLAIM = re.compile(
    rf"(?<![A-Za-z0-9.+])(?P<count>{_NUMERIC_RANGE_PATTERN})"
    rf"(?P<space>\s*|-?)"
    r"(?P<unit>qts?|quarts?|m(?:illi)?l(?:iters?|itres?)?|"
    r"l(?:iters?|itres?)?|\u6beb\u5347|\u5347)(?![A-Za-z])"
    r"(?P<suffix>\u88c5)?",
    re.IGNORECASE,
)
_SPEC_NUMBER_RANGE = re.compile(
    rf"(?<![0-9.])(?P<minimum>{_NUMERIC_ATOM_PATTERN})"
    rf"(?:\s*{_NUMERIC_RANGE_SEPARATOR_PATTERN}\s*"
    rf"(?P<maximum>{_NUMERIC_ATOM_PATTERN}))?(?![0-9.])",
    re.IGNORECASE,
)
_CAPACITY_UNIT = re.compile(
    r"(?<![A-Za-z])(?P<unit>qts?|quarts?|m(?:illi)?l(?:iters?|itres?)?|"
    r"l(?:iters?|itres?)?|\u6beb\u5347|\u5347)(?![A-Za-z])",
    re.IGNORECASE,
)
_UNSUPPORTED_COMPOSITE_NUMERIC_CLAIM = re.compile(
    r"(?<![A-Za-z0-9])\d+(?:\.\d+)?\s*[/+]\s*\d+(?:\.\d+)?\s*-?\s*"
    r"(?:people|persons?|pieces?|pcs?|qts?|quarts?|"
    r"m(?:illi)?l(?:iters?|itres?)?|l(?:iters?|itres?)?|"
    r"\u4eba|\u4ef6|\u6beb\u5347|\u5347)(?![A-Za-z])",
    re.IGNORECASE,
)
_NUMERIC_CLAIM_NOUN_OR_UNIT = (
    r"(?:people|persons?|pieces?|pcs?|qts?|quarts?|"
    r"m(?:illi)?l(?:iters?|itres?)?|l(?:iters?|itres?)?|"
    r"\u4eba|\u4ef6|\u6beb\u5347|\u5347)"
)
_UNSUPPORTED_COMMA_NUMERIC_CLAIM = re.compile(
    rf"(?<![A-Za-z0-9])\d+(?:,\d+)+\s*-?\s*"
    rf"{_NUMERIC_CLAIM_NOUN_OR_UNIT}(?![A-Za-z])",
    re.IGNORECASE,
)
_UNSUPPORTED_FRACTIONAL_PIECE_CLAIM = re.compile(
    r"(?<![A-Za-z0-9])(?:\d+\.\d+|\.\d+)\s*-?\s*"
    r"(?:(?:pieces?|pcs?)\b|\u4ef6(?:\u5957)?)",
    re.IGNORECASE,
)
_UNSUPPORTED_NEGATIVE_NUMERIC_CLAIM = re.compile(
    rf"(?<![A-Za-z0-9])-\d+(?:\.\d+)?\s*-?\s*"
    rf"{_NUMERIC_CLAIM_NOUN_OR_UNIT}(?![A-Za-z])",
    re.IGNORECASE,
)
_UNSUPPORTED_POSITIVE_NUMERIC_CLAIM = re.compile(
    rf"(?<![A-Za-z0-9])\+\d+(?:\.\d+)?\s*-?\s*"
    rf"{_NUMERIC_CLAIM_NOUN_OR_UNIT}(?![A-Za-z])",
    re.IGNORECASE,
)
_QUALIFIED_CLAIM_TARGET = (
    r"(?:people|persons?|pieces?|pcs?|"
    r"(?:qts?|quarts?|m(?:illi)?l(?:iters?|itres?)?|"
    r"l(?:iters?|itres?)?|\u6beb\u5347|\u5347)(?:\u88c5)?|"
    r"\u4eba(?:\u4f7f\u7528(?:\u7684)?|\u7528|\u4efd)?|"
    r"\u4ef6(?:\u5957\u88c5?|\u88c5)?)(?![A-Za-z])"
)
_UNSUPPORTED_QUALIFIED_NUMERIC_CLAIM = re.compile(
    rf"""
    (?:
        (?<![A-Za-z0-9])between\s+{_NUMERIC_ATOM_PATTERN}\s+and\s+
            {_NUMERIC_ATOM_PATTERN}\s*-?\s*{_QUALIFIED_CLAIM_TARGET}
        |
        (?<![A-Za-z0-9])(?:up\s+to|at\s+least|at\s+most|no\s+more\s+than|
            no\s+less\s+than|more\s+than|less\s+than|under|over|about|around|
            approximately?|approx\.?|(?:\u7ea6|\u5927\u7ea6)(?:\u4e3a)?|\u6700\u591a|
            \u81f3\u5c11|\u4e0d\u8d85\u8fc7|\u4e0d\u4f4e\u4e8e|\u8d85\u8fc7|
            \u5c11\u4e8e)\s*{_NUMERIC_RANGE_PATTERN}\s*-?\s*
            {_QUALIFIED_CLAIM_TARGET}
        |
        [<>\u2264\u2265\u2248\u2272\u2273]\s*{_NUMERIC_RANGE_PATTERN}
            \s*-?\s*{_QUALIFIED_CLAIM_TARGET}
        |
        (?:^|[^0-9.\s])\s*~\s*{_NUMERIC_RANGE_PATTERN}\s*-?\s*
            {_QUALIFIED_CLAIM_TARGET}
        |
        (?<![A-Za-z0-9.+]){_NUMERIC_ATOM_PATTERN}\s*
            (?:and|or|&|,|\u6216|\u3001)\s*{_NUMERIC_ATOM_PATTERN}
            \s*-?\s*{_QUALIFIED_CLAIM_TARGET}
        |
        (?<![A-Za-z0-9.+]){_NUMERIC_ATOM_PATTERN}\s*
            (?:\+|plus|\u5de6\u53f3|\u7ea6)\s*-?\s*
            {_QUALIFIED_CLAIM_TARGET}
        |
        (?<![A-Za-z0-9.+]){_NUMERIC_ATOM_PATTERN}\s*-?\s*
            {_QUALIFIED_CLAIM_TARGET}\s*(?:or\s+more|or\s+less|and\s+up|
            and\s+above|approximately?|approx\.?|\+|\u4ee5\u4e0a|
            \u4ee5\u4e0b|\u4ee5\u5185|\u4ee5\u5916|\u5de6\u53f3|
            \u53ca\u4ee5\u4e0a|\u53ca\u4ee5\u4e0b|\u6216\u66f4\u591a|
            \u6216\u66f4\u5c11)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_UNSUPPORTED_PIECE_RANGE_CLAIM = re.compile(
    rf"(?<![A-Za-z0-9.+]){_NUMERIC_ATOM_PATTERN}\s*"
    rf"{_NUMERIC_RANGE_SEPARATOR_PATTERN}\s*{_NUMERIC_ATOM_PATTERN}"
    r"\s*(?:-\s*)?(?:(?:pieces?|pcs?)\b|\u4ef6(?:\u5957)?)",
    re.IGNORECASE,
)
_UNSUPPORTED_SPEC_NUMERIC_QUALIFIER = re.compile(
    rf"""
    (?:
        \b(?:between|up\s+to|at\s+least|at\s+most|no\s+more\s+than|
            no\s+less\s+than|more\s+than|less\s+than|under|over|about|around|
            approximately?|approx\.?|or\s+more|or\s+less)\b
        |[<>\u2264\u2265\u2248\u2272\u2273]
        |(?:^|[^0-9.\s])\s*~\s*{_NUMERIC_ATOM_PATTERN}
        |{_NUMERIC_ATOM_PATTERN}\s*~(?!\s*{_NUMERIC_ATOM_PATTERN})
        |(?:^|[^0-9.\s])\s*[+\-\u2212]\s*{_NUMERIC_ATOM_PATTERN}
        |{_NUMERIC_ATOM_PATTERN}\s*\+
        |{_NUMERIC_ATOM_PATTERN}\s*(?:and|or|&|,|\u6216|\u3001)\s*
            {_NUMERIC_ATOM_PATTERN}
        |(?:\u7ea6|\u5927\u7ea6|\u6700\u591a|\u81f3\u5c11|\u4e0d\u8d85\u8fc7|
            \u4e0d\u4f4e\u4e8e|\u8d85\u8fc7|\u5c11\u4e8e|\u4ee5\u4e0a|
            \u4ee5\u4e0b|\u4ee5\u5185|\u4ee5\u5916|\u5de6\u53f3|
            \u53ca\u4ee5\u4e0a|\u53ca\u4ee5\u4e0b|\u6216\u66f4\u591a|
            \u6216\u66f4\u5c11)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_UNSUPPORTED_POSTFIX_NUMERIC_CLAIM = re.compile(
    rf"(?<![A-Za-z0-9]){_NUMERIC_ATOM_PATTERN}\s*(?:\+|plus)\s*"
    rf"{_NUMERIC_CLAIM_NOUN_OR_UNIT}(?![A-Za-z])",
    re.IGNORECASE,
)
_UNSUPPORTED_UNICODE_FRACTION_CLAIM = re.compile(
    rf"(?<![A-Za-z0-9])(?:\d+)?[\u00bc\u00bd\u00be\u2150-\u215e]\s*-?\s*"
    rf"{_NUMERIC_CLAIM_NOUN_OR_UNIT}(?![A-Za-z])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _NumericSpecEvidence:
    """One deterministic numeric fact read from structured specifications."""

    kind: str
    numbers: tuple[Decimal, ...]
    source_path: str
    unit: str | None = None
    display_unit: str | None = None
    subject: str | None = None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def _numeric_range(value: Any) -> tuple[Decimal, ...] | None:
    """Read only a single positive scalar or an explicit two-value range."""

    if isinstance(value, dict):
        minimum = _decimal(value.get("min"))
        if minimum is None:
            return None
        if "max" not in value:
            return (minimum,)
        maximum = _decimal(value.get("max"))
        # An explicitly supplied but unreadable upper bound is not a scalar.
        # Treat it as malformed so the caller blocks instead of guessing that
        # the lower bound was the entire fact.
        if maximum is None:
            return None
        if maximum < minimum:
            return None
        if maximum == minimum:
            return (minimum,)
        return (minimum, maximum)
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number = _decimal(value)
        return (number,) if number is not None else None
    if not isinstance(value, str):
        return None
    if _UNSUPPORTED_SPEC_NUMERIC_QUALIFIER.search(value):
        return None
    matches = list(_SPEC_NUMBER_RANGE.finditer(value))
    if len(matches) != 1:
        return None
    match = matches[0]
    # Do not reinterpret two unrelated numbers as a range.  The range regex
    # must have consumed every numeric atom present in the source value.
    numeric_atoms = re.findall(_NUMERIC_ATOM_PATTERN, value)
    consumed_atoms = [match.group("minimum")]
    if match.group("maximum") is not None:
        consumed_atoms.append(match.group("maximum"))
    if len(numeric_atoms) != len(consumed_atoms):
        return None
    minimum = _decimal(match.group("minimum"))
    maximum = _decimal(match.group("maximum"))
    if minimum is None:
        return None
    if maximum is None:
        return (minimum,)
    if maximum < minimum:
        return None
    if maximum == minimum:
        return (minimum,)
    return (minimum, maximum)


def _numeric_node_range(node: Any) -> tuple[Decimal, ...] | None:
    if not isinstance(node, dict):
        return _numeric_range(node)
    parsed_values: list[tuple[Decimal, ...]] = []
    unreadable_value = False
    for key in ("value", "value_en", "raw_value"):
        candidate = node.get(key)
        if candidate in (None, "", [], {}):
            continue
        parsed = _numeric_range(candidate)
        if parsed is None:
            unreadable_value = True
        else:
            parsed_values.append(parsed)
    # The normalized value, translated value, and raw supplier value are all
    # evidence for the same fact.  A disagreement (or an unreadable populated
    # representation) must not be hidden by taking whichever field came first.
    unique_values = set(parsed_values)
    if unreadable_value or len(unique_values) != 1:
        return None
    return next(iter(unique_values))


def _format_decimal(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _numeric_range_text(numbers: tuple[Decimal, ...]) -> str:
    if len(numbers) == 1:
        return _format_decimal(numbers[0])
    return f"{_format_decimal(numbers[0])}-{_format_decimal(numbers[1])}"


def _integer_count(numbers: tuple[Decimal, ...] | None) -> tuple[Decimal, ...] | None:
    if not numbers or any(number != number.to_integral_value() for number in numbers):
        return None
    return numbers


def _normalized_descriptor(*values: Any) -> str:
    text = " ".join(str(value or "") for value in values).casefold()
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def _numeric_spec_kind(descriptor: str) -> str | None:
    if any(
        term in descriptor
        for term in (
            "capacitypeople",
            "peoplecapacity",
            "personcapacity",
            "personsuitability",
            "suitablepeople",
            "\u9002\u7528\u4eba\u6570",
            "\u4f7f\u7528\u4eba\u6570",
            "\u5bb9\u7eb3\u4eba\u6570",
            "\u5efa\u8bae\u4eba\u6570",
            "\u5c31\u9910\u4eba\u6570",
        )
    ) or "\u4eba\u6570" in descriptor:
        return "people"
    if any(
        term in descriptor
        for term in (
            "piececount",
            "piecescount",
            "numberofpieces",
            "setcount",
            "packagequantity",
            "\u4ef6\u6570",
            "\u5957\u88c5\u6570\u91cf",
            "\u5305\u88c5\u6570\u91cf",
        )
    ):
        return "piece"
    if any(
        term in descriptor
        for term in ("batterycapacity", "\u7535\u6c60\u5bb9\u91cf", "\u7535\u82af\u5bb9\u91cf")
    ):
        return None
    if "capacity" in descriptor or "\u5bb9\u91cf" in descriptor:
        return "capacity"
    return None


def _canonical_capacity_unit(value: str) -> str:
    normalized = value.casefold()
    if normalized.startswith(("q", "quart")):
        return "qt"
    if normalized.startswith("m") or "\u6beb\u5347" in normalized:
        return "ml"
    return "l"


def _capacity_unit(node: Any, *, descriptor_text: str) -> tuple[str, str] | None:
    """Return one unambiguous unit shared by every populated representation."""

    texts: list[str] = [descriptor_text]
    if isinstance(node, dict):
        texts.extend(
            str(node.get(key) or "")
            for key in ("unit", "value", "value_en", "raw_value")
        )
    else:
        texts.append(str(node or ""))
    units = {
        _canonical_capacity_unit(match.group("unit"))
        for text in texts
        for match in _CAPACITY_UNIT.finditer(text)
    }
    normalized = re.sub(r"[^a-z0-9]+", "_", descriptor_text.casefold()).strip("_")
    if re.search(r"(?:^|_)capacity_ml(?:$|_)", normalized):
        units.add("ml")
    if re.search(r"(?:^|_)capacity_l(?:$|_)", normalized):
        units.add("l")
    if re.search(r"(?:^|_)capacity_(?:qt|quart)(?:$|_)", normalized):
        units.add("qt")
    if len(units) != 1:
        return None
    unit = next(iter(units))
    return unit, {"l": "L", "ml": "mL", "qt": "qt"}[unit]


def _buyer_capacity_projection(
    numbers: tuple[Decimal, ...],
    unit: str,
) -> tuple[tuple[Decimal, ...], str, str] | None:
    """Project verified capacity evidence into the US buyer-display unit."""

    if unit == "qt":
        return numbers, unit, "qt"
    if unit not in {"l", "ml"}:
        return None
    source_value: Any = (
        numbers[0]
        if len(numbers) == 1
        else {"min": numbers[0], "max": numbers[1]}
    )
    converted = imperial_measurement(source_value, unit)
    if converted is None:
        return None
    display_value, display_unit = converted
    display_numbers = _numeric_range(display_value)
    canonical_display_unit = _canonical_capacity_unit(display_unit)
    if display_numbers is None or canonical_display_unit != "qt":
        return None
    return display_numbers, canonical_display_unit, "qt"


_CAPACITY_SUBJECT_ALIASES: dict[str, tuple[str, ...]] = {
    "kettle": (
        "kettle",
        "kettles",
        "tea kettle",
        "tea kettles",
        "teakettle",
        "\u6c34\u58f6",
        "\u8336\u58f6",
    ),
    "pot": (
        "pot",
        "pots",
        "cooking pot",
        "cooking pots",
        "main pot",
        "stockpot",
        "stockpots",
        "saucepan",
        "saucepans",
        "\u4e3b\u9505",
    ),
    "pan": (
        "pan",
        "pans",
        "frying pan",
        "frying pans",
        "skillet",
        "skillets",
        "\u714e\u76d8",
        "\u714e\u9505",
        "\u5e73\u5e95\u9505",
    ),
    "bottle": ("bottle", "bottles", "flask", "flasks", "\u74f6"),
    "cup": ("cup", "cups", "mug", "mugs", "\u676f"),
    "bowl": ("bowl", "bowls", "\u7897"),
}


def _capacity_subjects(value: Any) -> set[str]:
    text = re.sub(r"[_-]+", " ", str(value or "")).casefold()
    matches = {
        subject
        for subject, aliases in _CAPACITY_SUBJECT_ALIASES.items()
        if any(
            re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text)
            for alias in aliases
        )
    }
    # A bare Chinese \u201c\u9505\u201d means pot only when a more specific pan/kettle
    # label was not present.  This prevents \u714e\u9505 / \u5e73\u5e95\u9505 from being
    # classified as both pot and pan.
    if "\u9505" in text and not matches.intersection({"pan", "kettle"}):
        matches.add("pot")
    return matches


def _iter_numeric_spec_nodes(
    structured_specs: dict[str, Any] | None,
) -> list[tuple[str, Any, str, str]]:
    if not isinstance(structured_specs, dict):
        return []
    output: list[tuple[str, Any, str, str]] = []
    for key, node in structured_specs.items():
        if key in {
            "schema_version",
            "source",
            "buyer_translation",
            "package_includes",
            "package_includes_source",
            "additional_specs",
        }:
            continue
        descriptor_text = " ".join(
            [
                str(key),
                str(node.get("label") or "") if isinstance(node, dict) else "",
                str(node.get("label_en") or "") if isinstance(node, dict) else "",
                str(node.get("source_label") or "") if isinstance(node, dict) else "",
            ]
        )
        output.append(
            (
                str(key),
                node,
                _normalized_descriptor(descriptor_text),
                descriptor_text,
            )
        )
    additional = structured_specs.get("additional_specs")
    if isinstance(additional, dict):
        additional_items = [
            ({"key": key, **value} if isinstance(value, dict) else {"key": key, "value": value})
            for key, value in additional.items()
        ]
    elif isinstance(additional, list):
        additional_items = additional
    else:
        additional_items = []
    for index, node in enumerate(additional_items):
        if not isinstance(node, dict):
            continue
        key = str(node.get("key") or f"row_{index + 1}")
        descriptor_text = " ".join(
            str(node.get(field) or "")
            for field in ("key", "label", "label_en", "source_label")
        )
        output.append(
            (
                f"additional_specs.{key}",
                node,
                _normalized_descriptor(descriptor_text),
                descriptor_text,
            )
        )
    return output


def _numeric_spec_evidence(
    kind: str,
    structured_specs: dict[str, Any] | None,
    *,
    package_includes: Any,
) -> tuple[list[_NumericSpecEvidence], list[str]]:
    evidence: list[_NumericSpecEvidence] = []
    malformed: list[str] = []
    for path, node, descriptor, descriptor_text in _iter_numeric_spec_nodes(
        structured_specs
    ):
        if _numeric_spec_kind(descriptor) != kind:
            continue
        numbers = _numeric_node_range(node)
        if kind in {"people", "piece"}:
            numbers = _integer_count(numbers)
        if numbers is None:
            malformed.append(path)
            continue
        unit: str | None = None
        display_unit: str | None = None
        if kind == "capacity":
            capacity_unit = _capacity_unit(node, descriptor_text=descriptor_text)
            subjects = _capacity_subjects(descriptor_text)
            if capacity_unit is None or len(subjects) > 1:
                malformed.append(path)
                continue
            unit, display_unit = capacity_unit
            buyer_projection = _buyer_capacity_projection(numbers, unit)
            if buyer_projection is None:
                malformed.append(path)
                continue
            numbers, unit, display_unit = buyer_projection
        else:
            subjects = set()
        evidence.append(
            _NumericSpecEvidence(
                kind=kind,
                numbers=numbers,
                source_path=path,
                unit=unit,
                display_unit=display_unit,
                subject=(next(iter(subjects)) if subjects else None),
            )
        )
    if kind == "piece":
        includes = canonical_package_includes(package_includes, structured_specs)
        if includes:
            evidence.append(
                _NumericSpecEvidence(
                    kind="piece",
                    numbers=(Decimal(len(includes)),),
                    source_path="package_includes",
                )
            )
    return evidence, malformed


def _select_numeric_spec_evidence(
    kind: str,
    *,
    current_numbers: tuple[Decimal, ...],
    current_unit: str | None,
    current_subject: str | None = None,
    structured_specs: dict[str, Any] | None,
    package_includes: Any,
) -> _NumericSpecEvidence | None:
    candidates, malformed = _numeric_spec_evidence(
        kind,
        structured_specs,
        package_includes=package_includes,
    )
    if not candidates and not malformed:
        return None
    if malformed:
        raise TitleEvidenceConsistencyError(
            f"Cannot safely reconcile {kind} title claim from malformed specification "
            f"field(s): {', '.join(sorted(malformed))}."
        )
    if kind == "capacity" and current_subject:
        matching = [
            candidate for candidate in candidates if candidate.subject == current_subject
        ]
        if len(matching) == 1:
            candidates = matching
        elif not matching and any(candidate.subject for candidate in candidates):
            raise TitleEvidenceConsistencyError(
                "Cannot safely reconcile capacity title claim because its product "
                f"subject ({current_subject}) does not match the available capacity_* "
                "specification field."
            )
    unique: dict[tuple[tuple[Decimal, ...], str | None], _NumericSpecEvidence] = {}
    for candidate in candidates:
        unique.setdefault((candidate.numbers, candidate.unit), candidate)
    candidates = list(unique.values())
    if len(candidates) == 1:
        return candidates[0]
    raise TitleEvidenceConsistencyError(
        f"Cannot safely reconcile {kind} title claim because corresponding "
        "structured specification fields disagree or are ambiguous."
    )


def _cleanup_numeric_claim_removal(value: str) -> str:
    clean = re.sub(r"\(\s*\)|\[\s*\]|\{\s*\}", " ", value)
    clean = re.sub(
        r"(?P<separator>[,;:/|\u00b7\-\u2013\u2014])"
        r"(?:\s*[,;:/|\u00b7\-\u2013\u2014])+",
        r"\g<separator> ",
        clean,
    )
    clean = re.sub(r"\s+([,;:.!?])", r"\1", clean)
    clean = re.sub(r"\s+", " ", clean)
    clean = re.sub(r"^(?:and|or)\b|\b(?:and|or)$", "", clean, flags=re.IGNORECASE)
    return clean.strip(" \t\r\n,;:/|\u00b7-\u2013\u2014")


def reconcile_title_numeric_claims(
    title: Any,
    structured_specs: dict[str, Any] | None,
    *,
    package_includes: Any = None,
) -> str:
    """Reconcile buyer-visible numeric title claims with verified specs.

    Missing corresponding evidence removes the claim.  A single verified fact
    rewrites a mismatch.  Ambiguous or malformed corresponding evidence raises
    ``TitleEvidenceConsistencyError`` rather than guessing which number is true.
    This pure function is shared by generated SEO copy, supplier-name import,
    and post-provider product naming.
    """

    output = html.unescape(str(title or ""))
    if _UNSUPPORTED_COMPOSITE_NUMERIC_CLAIM.search(output):
        raise TitleEvidenceConsistencyError(
            "Cannot safely parse a composite or fractional numeric title claim."
        )
    if _UNSUPPORTED_COMMA_NUMERIC_CLAIM.search(output):
        raise TitleEvidenceConsistencyError(
            "Cannot safely parse a comma-formatted numeric title claim."
        )
    if _UNSUPPORTED_FRACTIONAL_PIECE_CLAIM.search(output):
        raise TitleEvidenceConsistencyError(
            "Cannot safely parse a fractional piece-count title claim."
        )
    if _UNSUPPORTED_NEGATIVE_NUMERIC_CLAIM.search(output):
        raise TitleEvidenceConsistencyError(
            "Cannot safely parse a negative numeric title claim."
        )
    if _UNSUPPORTED_POSITIVE_NUMERIC_CLAIM.search(output):
        raise TitleEvidenceConsistencyError(
            "Cannot safely parse a signed numeric title claim."
        )
    if _UNSUPPORTED_QUALIFIED_NUMERIC_CLAIM.search(output):
        raise TitleEvidenceConsistencyError(
            "Cannot safely parse a qualified or alternative numeric title claim."
        )
    if _UNSUPPORTED_PIECE_RANGE_CLAIM.search(output):
        raise TitleEvidenceConsistencyError(
            "Cannot safely reconcile a ranged piece-count title claim."
        )
    if _UNSUPPORTED_POSTFIX_NUMERIC_CLAIM.search(output):
        raise TitleEvidenceConsistencyError(
            "Cannot safely parse a postfix-qualified numeric title claim."
        )
    if _UNSUPPORTED_UNICODE_FRACTION_CLAIM.search(output):
        raise TitleEvidenceConsistencyError(
            "Cannot safely parse a Unicode fraction numeric title claim."
        )
    claim_matches = {
        "people": [
            *_PEOPLE_CLAIM.finditer(output),
            *_CHINESE_PEOPLE_CLAIM.finditer(output),
        ],
        "piece": [
            *_PIECE_CLAIM.finditer(output),
            *_CHINESE_PIECE_CLAIM.finditer(output),
        ],
        "capacity": list(_CAPACITY_CLAIM.finditer(output)),
    }
    for claim_kind, matches in claim_matches.items():
        if len(matches) <= 1:
            continue
        candidates, malformed = _numeric_spec_evidence(
            claim_kind,
            structured_specs,
            package_includes=package_includes,
        )
        # With no corresponding evidence, deleting every claim is deterministic
        # and is required by the contract.  Once any fact exists, broadcasting
        # it across multiple claims would be unsafe, so the title is blocked.
        if candidates or malformed:
            raise TitleEvidenceConsistencyError(
                f"Cannot safely reconcile multiple {claim_kind} claims in one title."
            )

    def replace_people(match: re.Match[str]) -> str:
        current = _integer_count(_numeric_range(match.group("count")))
        if current is None:
            raise TitleEvidenceConsistencyError(
                "Cannot safely parse people count in title claim."
            )
        verified = _select_numeric_spec_evidence(
            "people",
            current_numbers=current,
            current_unit=None,
            structured_specs=structured_specs,
            package_includes=package_includes,
        )
        if verified is None:
            return ""
        noun = match.group("noun")
        separator = match.group("separator")
        if "-" not in separator:
            singular = len(verified.numbers) == 1 and verified.numbers[0] == 1
            if singular and noun.casefold() in {"people", "persons"}:
                noun = "Person" if noun[:1].isupper() else "person"
            elif not singular and noun.casefold() == "person":
                noun = "People" if noun[:1].isupper() else "people"
        if verified.numbers == current and noun == match.group("noun"):
            return match.group(0)
        return (
            (match.group("prefix") or "")
            + (
                match.group("count")
                if verified.numbers == current
                else _numeric_range_text(verified.numbers)
            )
            + separator
            + noun
        )

    output = _PEOPLE_CLAIM.sub(replace_people, output)

    def replace_chinese_people(match: re.Match[str]) -> str:
        current = _integer_count(_numeric_range(match.group("count")))
        if current is None:
            raise TitleEvidenceConsistencyError(
                "Cannot safely parse people count in supplier title claim."
            )
        verified = _select_numeric_spec_evidence(
            "people",
            current_numbers=current,
            current_unit=None,
            structured_specs=structured_specs,
            package_includes=package_includes,
        )
        if verified is None:
            return ""
        if verified.numbers == current:
            return match.group(0)
        return (
            f"{match.group('prefix') or ''}{_numeric_range_text(verified.numbers)}\u4eba"
            f"{match.group('suffix') or ''}"
        )

    output = _CHINESE_PEOPLE_CLAIM.sub(replace_chinese_people, output)

    def replace_piece(match: re.Match[str]) -> str:
        current = (Decimal(_piece_claim_count(match)),)
        verified = _select_numeric_spec_evidence(
            "piece",
            current_numbers=current,
            current_unit=None,
            structured_specs=structured_specs,
            package_includes=package_includes,
        )
        if verified is None:
            return "set" if re.search(r"\bset\b", match.group(0), re.IGNORECASE) else ""
        if len(verified.numbers) != 1:
            raise TitleEvidenceConsistencyError(
                "A piece_count specification must be a single integer."
            )
        if verified.numbers == current:
            return match.group(0)
        group_name = "piece_count" if match.group("piece_count") else "set_count"
        start, end = match.span(group_name)
        relative_start = start - match.start()
        relative_end = end - match.start()
        raw = match.group(0)
        return (
            raw[:relative_start]
            + _numeric_range_text(verified.numbers)
            + raw[relative_end:]
        )

    output = _PIECE_CLAIM.sub(replace_piece, output)

    def replace_chinese_piece(match: re.Match[str]) -> str:
        current = (Decimal(match.group("count")),)
        verified = _select_numeric_spec_evidence(
            "piece",
            current_numbers=current,
            current_unit=None,
            structured_specs=structured_specs,
            package_includes=package_includes,
        )
        if verified is None:
            return ""
        if len(verified.numbers) != 1:
            raise TitleEvidenceConsistencyError(
                "A piece_count specification must be a single integer."
            )
        if verified.numbers == current:
            return match.group(0)
        return (
            f"{_numeric_range_text(verified.numbers)}\u4ef6"
            f"{match.group('suffix') or ''}"
        )

    output = _CHINESE_PIECE_CLAIM.sub(replace_chinese_piece, output)
    capacity_source_title = output
    capacity_candidates, capacity_malformed = _numeric_spec_evidence(
        "capacity",
        structured_specs,
        package_includes=package_includes,
    )

    def replace_capacity(match: re.Match[str]) -> str:
        current = _numeric_range(match.group("count"))
        if current is None:
            raise TitleEvidenceConsistencyError(
                "Cannot safely parse capacity in title claim."
            )
        if not capacity_candidates and not capacity_malformed:
            return ""
        current_unit = _canonical_capacity_unit(match.group("unit"))
        subject_context = capacity_source_title[
            max(0, match.start() - 48) : min(
                len(capacity_source_title), match.end() + 48
            )
        ]
        subjects = _capacity_subjects(subject_context)
        if len(subjects) > 1:
            raise TitleEvidenceConsistencyError(
                "Cannot safely reconcile capacity title claim because its product "
                "subject is ambiguous."
            )
        verified = _select_numeric_spec_evidence(
            "capacity",
            current_numbers=current,
            current_unit=current_unit,
            current_subject=(next(iter(subjects)) if subjects else None),
            structured_specs=structured_specs,
            package_includes=package_includes,
        )
        if verified is None:
            return ""
        if verified.numbers == current and verified.unit == current_unit:
            return match.group(0)
        display_unit = verified.display_unit or verified.unit
        spacing = match.group("space")
        if not spacing and display_unit and len(display_unit) > 2:
            spacing = " "
        return (
            f"{_numeric_range_text(verified.numbers)}{spacing}{display_unit or ''}"
            f"{match.group('suffix') or ''}"
        )

    output = _CAPACITY_CLAIM.sub(replace_capacity, output)
    return _cleanup_numeric_claim_removal(output)


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
    """Validate components and N-piece claims against verified count evidence."""

    unsupported = unsupported_component_terms(
        value,
        package_includes=package_includes,
        structured_specs=structured_specs,
    )
    if unsupported:
        return "Unsupported package component(s): " + ", ".join(unsupported)
    verified_count, count_error = _verified_piece_count(
        package_includes=package_includes,
        structured_specs=structured_specs,
    )
    for match in _PIECE_CLAIM.finditer(str(value or "")):
        claimed = _piece_claim_count(match)
        if count_error:
            return count_error
        if verified_count is None:
            return f"{claimed}-piece claim requires a verified piece_count."
        if claimed != verified_count:
            return (
                f"{claimed}-piece claim does not match verified piece count "
                f"({verified_count})."
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


def _verified_piece_count(
    *,
    package_includes: Any,
    structured_specs: dict[str, Any] | None,
) -> tuple[int | None, str | None]:
    candidates, malformed = _numeric_spec_evidence(
        "piece",
        structured_specs,
        package_includes=package_includes,
    )
    if malformed:
        return None, (
            "Cannot safely reconcile piece claim from malformed specification "
            f"field(s): {', '.join(sorted(malformed))}."
        )
    ranged = [
        candidate.source_path
        for candidate in candidates
        if len(candidate.numbers) != 1
    ]
    if ranged:
        return None, (
            "Cannot safely reconcile piece claim because piece_count must be "
            "a single verified integer, not a range."
        )
    counts = {
        int(candidate.numbers[0])
        for candidate in candidates
        if len(candidate.numbers) == 1
        and candidate.numbers[0] == candidate.numbers[0].to_integral_value()
    }
    if len(counts) > 1:
        return None, (
            "Cannot safely reconcile piece claim because piece_count and "
            "package_includes disagree."
        )
    return (next(iter(counts)) if counts else None), None


def _downgrade_unverified_piece_claims(value: str, verified_count: int | None) -> str:
    def replace(match: re.Match[str]) -> str:
        claimed = _piece_claim_count(match)
        if verified_count is None:
            return "set"
        if claimed == verified_count:
            return match.group(0)
        group_name = "piece_count" if match.group("piece_count") else "set_count"
        start, end = match.span(group_name)
        relative_start = start - match.start()
        relative_end = end - match.start()
        raw = match.group(0)
        return raw[:relative_start] + str(verified_count) + raw[relative_end:]

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
    verified_piece_count, piece_count_error = _verified_piece_count(
        package_includes=includes,
        structured_specs=structured_specs,
    )
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
        if piece_count_error and _PIECE_CLAIM.search(value):
            raise TitleEvidenceConsistencyError(piece_count_error)
        piece_safe = _downgrade_unverified_piece_claims(value, verified_piece_count)
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
        "verified_piece_count": verified_piece_count,
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


def _strip_supplier_model_tokens(value: Any) -> str:
    """Remove supplier-style model identifiers from customer-facing identity."""

    clean = html.unescape(str(value or ""))
    clean = _SUPPLIER_MODEL_HYPHENATED.sub(" ", clean)
    clean = _SUPPLIER_MODEL_COMPACT.sub(" ", clean)
    return re.sub(r"\s+", " ", clean).strip(" -_/|:;")


def title_evidence_corpus(
    *,
    product_name: str | None,
    product_type: str | None,
    category_name: str | None = None,
    site_brand: str,
    approved_selling_points: dict[str, Any],
    structured_specs: dict[str, Any] | None,
    package_includes: Any = None,
) -> set[str]:
    # Identity text is needed to retain the product noun, but legacy names may
    # themselves contain unsupported modifiers. Never let those modifiers
    # self-prove merely because they appeared in the old title.
    includes = canonical_package_includes(package_includes, structured_specs)
    clean_product_name = _strip_supplier_model_tokens(product_name)
    clean_category_name = _strip_supplier_model_tokens(category_name or product_type)
    clean_product_name = reconcile_title_numeric_claims(
        clean_product_name,
        structured_specs,
        package_includes=includes,
    )
    clean_category_name = reconcile_title_numeric_claims(
        clean_category_name,
        structured_specs,
        package_includes=includes,
    )
    identity = f"{clean_product_name} {clean_category_name}"
    identity_tokens = _claim_tokens(identity)
    tokens = identity_tokens - _UNTRUSTED_IDENTITY_CLAIMS
    unsupported_identity_components = unsupported_component_terms(
        f"{clean_product_name} {clean_category_name}",
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
    # Numeric facts stored as normalized values (for example
    # capacity_people.value={min: 2, max: 3}) do not repeat their semantic noun
    # in a value.  Once the numeric parser has verified that fact, inject only
    # the corresponding unit/noun vocabulary so the older word-level gate does
    # not reject the already-verified claim.
    semantic_tokens = {
        "people": {"people", "person", "persons"},
        "piece": {"piece", "pieces", "pc", "pcs", "set"},
        "capacity": {
            "l",
            "liter",
            "liters",
            "litre",
            "litres",
            "ml",
            "milliliter",
            "milliliters",
            "millilitre",
            "millilitres",
            "qt",
            "qts",
            "quart",
            "quarts",
        },
    }
    for kind, vocabulary in semantic_tokens.items():
        evidence, malformed = _numeric_spec_evidence(
            kind,
            structured_specs,
            package_includes=includes,
        )
        if evidence and not malformed:
            tokens.update(vocabulary)
            for fact in evidence:
                for number in fact.numbers:
                    tokens.update(_claim_tokens(_format_decimal(number)))
    return tokens


def _neutral_fallback(
    product_name: str | None,
    product_type: str | None,
    *,
    package_includes: Any = None,
    structured_specs: dict[str, Any] | None = None,
) -> str:
    original = _strip_supplier_model_tokens(product_name or product_type or "Product")
    includes = canonical_package_includes(package_includes, structured_specs)
    original = reconcile_title_numeric_claims(
        original,
        structured_specs,
        package_includes=includes,
    )
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


def _title_is_degenerate(value: Any, *, site_brand: str) -> bool:
    """Return whether a title has fewer than two distinct identity words."""

    clean = _strip_supplier_model_tokens(value)
    brand_tokens = _claim_tokens(site_brand)
    meaningful = {
        token
        for token in _TOKEN.findall(clean.casefold())
        if token not in _STOPWORDS
        and token not in brand_tokens
        and token not in {"product", "products"}
        and not token.isdigit()
    }
    return len(meaningful) < 2


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
) -> tuple[str, list[str], bool]:
    clean = re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()
    if not clean:
        return fallback, [], True
    kept: list[str] = []
    removed: list[str] = []
    for segment in [part.strip() for part in _TITLE_SEPARATORS.split(clean) if part.strip()]:
        tokens = _claim_tokens(segment)
        if tokens and tokens.issubset(corpus):
            kept.append(segment)
        else:
            removed.append(segment)
    return (" | ".join(kept) if kept else fallback), removed, not kept


def enforce_title_evidence_consistency(
    result: dict[str, Any],
    *,
    product_name: str | None,
    product_type: str | None,
    category_name: str | None = None,
    site_brand: str,
    approved_selling_points: dict[str, Any],
    structured_specs: dict[str, Any] | None,
    package_includes: Any = None,
) -> dict[str, Any]:
    """Remove unsupported SEO/H1 claim segments and decode HTML entities."""

    output = dict(result)
    raw_seo = output.get("seo")
    seo = dict(raw_seo) if isinstance(raw_seo, dict) else {}
    fallback = _neutral_fallback(
        product_name,
        None,
        package_includes=package_includes,
        structured_specs=structured_specs,
    )
    corpus = title_evidence_corpus(
        product_name=product_name,
        product_type=product_type,
        category_name=category_name,
        site_brand=site_brand,
        approved_selling_points=approved_selling_points,
        structured_specs=structured_specs,
        package_includes=package_includes,
    )
    removed: dict[str, list[str]] = {}
    fallback_fields: list[str] = []
    numeric_reconciled_fields: list[str] = []
    for field in ("title", "h1"):
        raw_title = seo.get(field)
        reconciled_title = reconcile_title_numeric_claims(
            raw_title,
            structured_specs,
            package_includes=package_includes,
        )
        if reconciled_title != re.sub(
            r"\s+", " ", html.unescape(str(raw_title or ""))
        ).strip():
            numeric_reconciled_fields.append(field)
        clean, dropped, used_fallback = _supported_title(
            reconciled_title, corpus=corpus, fallback=fallback
        )
        if _title_is_degenerate(clean, site_brand=site_brand):
            if _title_is_degenerate(fallback, site_brand=site_brand):
                raise TitleEvidenceConsistencyError(
                    f"SEO {field} degenerated and product_name_en does not provide "
                    "at least two meaningful non-brand words."
                )
            clean = fallback
            used_fallback = True
        clean = reconcile_title_numeric_claims(
            clean,
            structured_specs,
            package_includes=package_includes,
        )
        if used_fallback:
            fallback_fields.append(field)
        seo[field] = clean
        if dropped:
            removed[field] = dropped
    output["seo"] = seo
    output["evidence_consistency"] = {
        "status": (
            "sanitized"
            if removed or fallback_fields or numeric_reconciled_fields
            else "passed"
        ),
        "removed_unsupported_title_segments": removed,
        "product_name_fallback_fields": fallback_fields,
        "numeric_reconciled_fields": sorted(set(numeric_reconciled_fields)),
        "approved_selling_points_only": True,
    }
    return output
