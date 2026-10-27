"""What happens when the two readers disagree.

The AI reader is accurate but can be talked into things; the OCR reader can't be talked into
anything but misreads stylized type. With two readers there is no majority, so disagreement
can only send a result toward a person: Pass becomes Review. Review and Fail are never changed
here, so the second reader can never turn a result into a pass.
"""

import re
from collections.abc import Sequence
from difflib import SequenceMatcher

from rapidfuzz import fuzz

from app.domain.models import FieldResult, LabelField, Status
from app.domain.normalize import normalize_text
from app.domain.rules.health_warning import (
    CANONICAL_TOKENS,
    contains_warning,
    join_tokens,
    tokenize,
)

# How closely (0-100) the AI's reading must appear somewhere in the OCR text to count as found.
GROUNDING_SIMILARITY = 90

NO_TEXT = "The second reader (OCR) found no text, so this reading couldn't be confirmed."
NOT_FOUND = (
    "The second reader (OCR) couldn't find this text on the label; the reading may be wrong."
)
WARNING_DIFFERS = (
    "The second reader (OCR) read the warning differently. Compare the two readings; the label "
    "may have a typo the AI reader corrected."
)
OFFLINE_MISMATCH = "Read by OCR only, which can misread labels; a person should confirm this."
OFFLINE_BOLD = "Bold type can't be checked without the AI reader."


def cross_check(results: Sequence[FieldResult], ocr_text: str) -> list[FieldResult]:
    """Confirm each passing AI reading against the OCR text, or send it to review."""
    if not re.search(r"\w", ocr_text):
        return [
            result.at_least(Status.REVIEW, NO_TEXT) if _confirmable(result) else result
            for result in results
        ]

    ocr_key = normalize_text(ocr_text)
    checked = []
    for result in results:
        if not _confirmable(result):
            checked.append(result)
        elif result.field is LabelField.HEALTH_WARNING:
            checked.append(_confirm_warning(result, ocr_text))
        else:
            checked.append(_confirm_found(result, ocr_key))
    return checked


def offline_policy(results: Sequence[FieldResult]) -> list[FieldResult]:
    """OCR was the only reader: its mismatches may be misreads, and it can't see bold type."""
    adjusted = []
    for result in results:
        if result.status is Status.FAIL:
            result = result.model_copy(
                update={"status": Status.REVIEW, "notes": (*result.notes, OFFLINE_MISMATCH)}
            )
        if result.field is LabelField.HEALTH_WARNING:
            result = result.at_least(Status.REVIEW, OFFLINE_BOLD)
        adjusted.append(result)
    return adjusted


def _confirmable(result: FieldResult) -> bool:
    return result.status is Status.PASS and bool(result.found)


def _confirm_found(result: FieldResult, ocr_key: str) -> FieldResult:
    found_key = normalize_text(result.found or "")
    if not found_key:
        return result
    # partial_ratio scores the best-matching stretch of the longer text, so a short OCR text
    # must not get to "contain" a longer reading.
    if len(found_key) <= len(ocr_key):
        score = fuzz.partial_ratio(found_key, ocr_key)
    else:
        score = fuzz.ratio(found_key, ocr_key)
    if score >= GROUNDING_SIMILARITY:
        return result
    return result.at_least(Status.REVIEW, NOT_FOUND)


def _confirm_warning(result: FieldResult, ocr_text: str) -> FieldResult:
    # Exact wording, by the same rules as the warning check (spacing, line-break hyphens and
    # body capitals don't matter). A one-letter difference is not forgiven as OCR noise.
    if contains_warning(ocr_text):
        return result
    window = warning_window(tokenize(ocr_text))
    return result.at_least(
        Status.REVIEW,
        WARNING_DIFFERS,
        second_reading=join_tokens(window) if window else None,
    )


def warning_window(tokens: Sequence[str]) -> list[str] | None:
    """The stretch of OCR tokens that lines up best with the required warning, if any."""
    canonical = [token.casefold() for token in CANONICAL_TOKENS]
    ocr = [token.casefold() for token in tokens]
    matcher = SequenceMatcher(None, canonical, ocr, autojunk=False)
    # Single-token matches are usually stray words like "of" elsewhere on the label.
    blocks = [block for block in matcher.get_matching_blocks() if block.size >= 2]
    if not blocks:
        return None
    first, last = blocks[0], blocks[-1]
    start = max(0, first.b - first.a)
    end = min(len(tokens), last.b + last.size + (len(canonical) - last.a - last.size))
    return list(tokens[start:end])
