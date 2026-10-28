"""Choosing the brand, fanciful name and bottler statement from what the label prints.

Real labels show several names (a house brand, a brewery, a vineyard) and several
name-and-address statements (the producer's and the importer's). The AI reader lists them all
without seeing the application, and this picks the one the application describes, by running
the same checks the verifier then runs. The choice is always text printed on the label.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.domain.models import ApplicationData, ExtractedLabel, FieldResult, LabelField, Status
from app.domain.normalize import normalize_text
from app.domain.rules.names import check_bottler, check_name

BRAND_ELSEWHERE = (
    'The application\'s brand, "{expected}", is printed on the label, but the most prominent '
    'name is "{main}". A person should check which is the brand.'
)
BRAND_UNMARKED = (
    "The application's brand, \"{expected}\", is printed on the label, but the AI reader didn't "
    "pick out any name as the brand. A person should check it."
)


@dataclass(frozen=True)
class Chosen:
    reading: ExtractedLabel
    doubts: dict[LabelField, str]  # field -> why it must go to a person


def choose_names(
    reading: ExtractedLabel,
    *,
    names: Sequence[str],
    statements: Sequence[str],
    application: ApplicationData,
    class_types: Sequence[str] = (),
) -> Chosen:
    """The reading with its brand, fanciful name, bottler and class/type taken from what the
    label prints, and doubts for any field a person must check.

    The brand is the most prominent name, as the reader judged it. If that doesn't match, the
    application's brand may still be among the other names, but then it goes to a person: a
    name found elsewhere, such as in the bottler line under a sticker, never passes on its own.
    Statements, the fanciful name and the class/type may come from anywhere on the label.
    """

    def check_brand(candidate: str) -> FieldResult:
        return check_name(LabelField.BRAND, application.brand_name, candidate, cfr="")

    def check_statement(candidate: str) -> FieldResult:
        return check_bottler(application.bottler, candidate, cfr="")

    def check_class(candidate: str) -> FieldResult:
        return check_name(LabelField.CLASS_TYPE, application.class_type, candidate, cfr="")

    doubts: dict[LabelField, str] = {}
    brand = reading.brand_name
    if brand is None or check_brand(brand).status is Status.FAIL:
        other = _best(application.brand_name, _with(None, names), check_brand)
        if other is not None and (brand is None or check_brand(other).status is not Status.FAIL):
            if brand is not None:
                doubts[LabelField.BRAND] = BRAND_ELSEWHERE.format(
                    expected=application.brand_name, main=brand
                )
            elif check_brand(other).status is not Status.FAIL:
                doubts[LabelField.BRAND] = BRAND_UNMARKED.format(expected=application.brand_name)
            brand = other

    bottler = _best(application.bottler, _with(reading.bottler, statements), check_statement)
    class_type = _best(application.class_type, _with(reading.class_type, class_types), check_class)

    fanciful = reading.fanciful_name
    if application.fanciful_name:
        expected = application.fanciful_name

        def check_fanciful(candidate: str) -> FieldResult:
            return check_name(LabelField.FANCIFUL, expected, candidate, cfr="")

        # Real labels often print the fanciful name inside another line, such as "BOURBON" in
        # "STRAIGHT BOURBON WHISKEY", so the words themselves are candidates too.
        inside = _within(expected, [*names, reading.class_type, *class_types, brand])
        fanciful = _best(expected, _with(reading.fanciful_name, [*names, *inside]), check_fanciful)

    updated = reading.model_copy(
        update={
            "brand_name": brand,
            "fanciful_name": fanciful,
            "bottler": bottler,
            "class_type": class_type,
        }
    )
    return Chosen(reading=updated, doubts=doubts)


def _with(own: str | None, candidates: Iterable[str]) -> list[str]:
    """The reader's own choice first, then the candidates, without repeats."""
    return list(dict.fromkeys([own, *candidates] if own is not None else candidates))


def _best(
    expected: str, candidates: Sequence[str], check: Callable[[str], FieldResult]
) -> str | None:
    """The candidate the check rates best, then the most similar; the first wins a tie."""
    if not candidates:
        return None
    key = normalize_text(expected)
    return min(
        candidates,
        key=lambda candidate: (
            check(candidate).status.severity,
            -fuzz.ratio(key, normalize_text(candidate)),
        ),
    )


def _within(expected: str, texts: Iterable[str | None]) -> list[str]:
    """The expected words wherever they appear, whole, inside the texts, as printed there."""
    words = re.findall(r"\w+", expected)
    if not words:
        return []
    pattern = re.compile(
        r"(?<!\w)" + r"\W+".join(re.escape(word) for word in words) + r"(?!\w)", re.IGNORECASE
    )
    return [match.group(0) for text in texts if text and (match := pattern.search(text))]
