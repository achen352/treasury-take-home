"""Merging the readings of a label's images (front, back, neck) into one reading.

Real labels spread their fields over several images: the brand on the front, the warning on
the back. A field found on one image is taken from it. The same value on several images, up to
case, punctuation and spacing, is taken once. Values that differ are a conflict: the first
image's value is checked, and the field goes to a person with every reading.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.domain.models import ExtractedLabel, LabelField
from app.domain.normalize import normalize_text


@dataclass(frozen=True)
class MergedReading:
    reading: ExtractedLabel
    conflicts: dict[LabelField, tuple[str, ...]]  # field -> each different reading, in order


def merge_readings(readings: Sequence[ExtractedLabel]) -> MergedReading:
    if not readings:
        raise ValueError("merge_readings needs at least one reading")
    values: dict[str, str | bool | None] = {}
    conflicts: dict[LabelField, tuple[str, ...]] = {}

    for field in LabelField:
        if field is LabelField.HEALTH_WARNING:
            continue
        found = [value for reading in readings if (value := reading.value(field)) is not None]
        distinct = _distinct(found, key=lambda value: normalize_text(value) or value)
        if distinct:
            values[field.value] = distinct[0]
        if len(distinct) > 1:
            conflicts[field] = tuple(distinct)

    # The bold judgments belong to the warning they were made on, so they travel with it.
    with_warning = [reading for reading in readings if reading.health_warning is not None]
    if with_warning:
        first = with_warning[0]
        values["health_warning"] = first.health_warning
        values["warning_header_bold"] = first.warning_header_bold
        values["warning_body_bold"] = first.warning_body_bold
        texts = _distinct(
            [reading.health_warning or "" for reading in with_warning],
            key=lambda text: " ".join(text.split()),  # the wording rules are strict; only spacing
        )
        bolds = _distinct([_describe_bold(reading) for reading in with_warning], key=str)
        if len(texts) > 1:
            conflicts[LabelField.HEALTH_WARNING] = tuple(texts)
        elif len(bolds) > 1:
            conflicts[LabelField.HEALTH_WARNING] = tuple(bolds)

    return MergedReading(reading=ExtractedLabel.model_validate(values), conflicts=conflicts)


def _distinct(values: Sequence[str], key: Callable[[str], str]) -> list[str]:
    """The values that differ by `key`, each in its first form, in order."""
    seen: dict[str, str] = {}
    for value in values:
        seen.setdefault(key(value), value)
    return list(seen.values())


def _describe_bold(reading: ExtractedLabel) -> str:
    def judged(bold: bool | None) -> str:
        return "unknown" if bold is None else ("yes" if bold else "no")

    return (
        f"header in bold: {judged(reading.warning_header_bold)}; "
        f"rest in bold: {judged(reading.warning_body_bold)}"
    )
