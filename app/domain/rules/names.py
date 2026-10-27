"""Brand, class/type, bottler and country of origin: text that must match the application."""

import re
import unicodedata
from collections.abc import Callable

from rapidfuzz import fuzz

from app.domain.models import FieldResult, LabelField, Status
from app.domain.normalize import describe_all, latinize, lookalike_characters, normalize_text

# rapidfuzz scores run from 0 to 100. A near miss at or above these goes to a person; below
# them it fails. Brand and class/type use plain edit distance, so an extra, missing or
# reordered word scores too low to reach review on similarity alone.
NAME_REVIEW_SIMILARITY = 90
BOTTLER_REVIEW_SIMILARITY = 85  # addresses vary more ("KY" vs "Kentucky"), so be forgiving
COUNTRY_REVIEW_SIMILARITY = 90

_VERB = (
    r"(?:bottled|distilled|produced|brewed|vinted|cellared|made|blended|imported|packed"
    r"|prepared|manufactured|canned|crafted|aged|finished)"
)
_BOTTLED_BY = re.compile(rf"^{_VERB}(?: and {_VERB})* by ")
_ORIGIN_WORDING = re.compile(
    r"^(?:product of|produce of|made in|produced in|imported from|country of origin"
    r"|hecho en|producto de|produit de|prodotto in) "
)

Similarity = Callable[[str, str], float]


def check_name(field: LabelField, expected: str, found: str | None, *, cfr: str) -> FieldResult:
    """Brand name or class/type: cosmetic differences pass, near misses go to review."""
    return _compare(field, expected, found, cfr, normalize_text, fuzz.ratio, NAME_REVIEW_SIMILARITY)


def check_bottler(expected: str, found: str | None, *, cfr: str) -> FieldResult:
    """Name and address: "Bottled by" style wording is ignored, and matching is forgiving."""
    return _compare(
        LabelField.BOTTLER,
        expected,
        found,
        cfr,
        _bottler_key,
        fuzz.WRatio,
        BOTTLER_REVIEW_SIMILARITY,
    )


def check_country(expected: str | None, found: str | None, *, cfr: str) -> FieldResult:
    """Country of origin: "Product of" style wording and accents are ignored."""
    return _compare(
        LabelField.COUNTRY,
        expected,
        found,
        cfr,
        _country_key,
        fuzz.ratio,
        COUNTRY_REVIEW_SIMILARITY,
    )


def _bottler_key(text: str) -> str:
    return _BOTTLED_BY.sub("", normalize_text(text))


def _country_key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _ORIGIN_WORDING.sub("", normalize_text(without_accents))


def _compare(
    field: LabelField,
    expected: str | None,
    found: str | None,
    cfr: str,
    key: Callable[[str], str],
    similarity: Similarity,
    review_at: float,
) -> FieldResult:
    result = FieldResult(field=field, status=Status.FAIL, cfr=cfr, expected=expected, found=found)
    if found is None or not found.strip():
        return result.model_copy(update={"notes": ("Not found on the label.",)})

    # Look-alike letters are compared as the Latin letters they imitate, so a spoofed name
    # can't fail its way past review, then flagged so it can never pass.
    lookalikes = lookalike_characters(found, allowed=expected or "")
    found_key = key(latinize(found))
    expected_key = key(expected) if expected else ""
    if not found_key:
        return result.model_copy(update={"notes": ("No letters or numbers were read here.",)})
    if not expected_key:
        return result.model_copy(
            update={"status": Status.REVIEW, "notes": ("The application has no value to compare.",)}
        )

    if expected is not None and found.strip() == expected.strip():
        result = _with(result, Status.PASS, "Matches the application exactly.")
    elif found_key == expected_key:
        same_letters = (
            expected is not None and found.strip().casefold() == expected.strip().casefold()
        )
        result = _with(
            result,
            Status.PASS,
            "Differs only in capitalization."
            if same_letters
            else "Differs only in capitalization, punctuation, spacing or common abbreviations.",
        )
    else:
        score = similarity(found_key, expected_key)
        if score >= review_at:
            result = _with(
                result,
                Status.REVIEW,
                f"Similar to the application but not the same ({score:.0f}% similar).",
            )
        else:
            result = _with(result, Status.FAIL, "Does not match the application.")

    if lookalikes:
        result = result.at_least(
            Status.REVIEW,
            "Contains characters from another alphabet that look like Latin letters: "
            f"{describe_all(lookalikes)}.",
        )
    return result


def _with(result: FieldResult, status: Status, note: str) -> FieldResult:
    return result.model_copy(update={"status": status, "notes": (*result.notes, note)})
