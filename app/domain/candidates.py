"""Choosing the brand, fanciful name and bottler statement from what the label prints.

Real labels show several names (a house brand, a brewery, a vineyard) and several
name-and-address statements (the producer's and the importer's). The AI reader lists them all
without seeing the application, and this picks the one the application describes, by running
the same checks the verifier then runs. The choice is always text printed on the label.
"""

import re
from collections.abc import Callable, Iterable, Sequence

from rapidfuzz import fuzz

from app.domain.models import ApplicationData, ExtractedLabel, FieldResult, LabelField
from app.domain.normalize import normalize_text
from app.domain.rules.names import check_bottler, check_name


def choose_names(
    reading: ExtractedLabel,
    *,
    names: Sequence[str],
    statements: Sequence[str],
    application: ApplicationData,
) -> ExtractedLabel:
    """The reading with its brand, fanciful name and bottler taken from the label's candidates.

    A name the reader already put in a field is one more candidate, preferred on a tie.
    """

    def check_brand(candidate: str) -> FieldResult:
        return check_name(LabelField.BRAND, application.brand_name, candidate, cfr="")

    def check_statement(candidate: str) -> FieldResult:
        return check_bottler(application.bottler, candidate, cfr="")

    brand = _best(application.brand_name, _with(reading.brand_name, names), check_brand)
    bottler = _best(application.bottler, _with(reading.bottler, statements), check_statement)

    fanciful = reading.fanciful_name
    if application.fanciful_name:
        expected = application.fanciful_name

        def check_fanciful(candidate: str) -> FieldResult:
            return check_name(LabelField.FANCIFUL, expected, candidate, cfr="")

        # Real labels often print the fanciful name inside another line, such as "BOURBON" in
        # "STRAIGHT BOURBON WHISKEY", so the words themselves are candidates too.
        inside = _within(expected, [*names, reading.class_type, reading.brand_name])
        fanciful = _best(expected, _with(reading.fanciful_name, [*names, *inside]), check_fanciful)

    return reading.model_copy(
        update={"brand_name": brand, "fanciful_name": fanciful, "bottler": bottler}
    )


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
