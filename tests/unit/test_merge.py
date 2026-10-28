"""Merging the readings of several images of one label (front, back, neck)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.constants import HEALTH_WARNING
from app.domain.merge import merge_readings
from app.domain.models import ExtractedLabel, LabelField
from tests.samples import OLD_TOM_READING

FRONT = ExtractedLabel(
    brand_name="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol_content="45% Alc./Vol. (90 Proof)",
    net_contents="750 mL",
)
BACK = ExtractedLabel(
    bottler="Distilled and bottled by Old Tom Distillery, Louisville, Kentucky",
    health_warning=HEALTH_WARNING,
    warning_header_bold=True,
    warning_body_bold=False,
)


def test_a_single_image_is_used_as_it_is() -> None:
    merged = merge_readings([OLD_TOM_READING])

    assert merged.reading == OLD_TOM_READING
    assert merged.conflicts == {}


def test_fields_from_different_images_are_combined() -> None:
    merged = merge_readings([FRONT, BACK])

    assert merged.reading == OLD_TOM_READING
    assert merged.conflicts == {}


def test_the_same_value_on_several_images_is_used_once() -> None:
    neck = ExtractedLabel(brand_name="Old Tom Distillery")

    merged = merge_readings([FRONT, BACK, neck])

    assert merged.reading.brand_name == "OLD TOM DISTILLERY"  # the first image's version
    assert merged.conflicts == {}


def test_different_values_on_two_images_are_a_conflict_listing_both() -> None:
    back = BACK.model_copy(update={"alcohol_content": "40% Alc./Vol. (80 Proof)"})

    merged = merge_readings([FRONT, back])

    assert merged.reading.alcohol_content == "45% Alc./Vol. (90 Proof)"
    assert merged.conflicts == {
        LabelField.ALCOHOL: ("45% Alc./Vol. (90 Proof)", "40% Alc./Vol. (80 Proof)")
    }


@pytest.mark.parametrize(
    ("field", "front", "back"),
    [
        ("alcohol_content", "Alc. 50% By Vol.", "50%vol"),
        ("net_contents", "750 mL", "75 cL"),
    ],
)
def test_the_same_number_written_two_ways_is_not_a_conflict(
    field: str, front: str, back: str
) -> None:
    merged = merge_readings(
        [
            ExtractedLabel.model_validate({field: front}),
            ExtractedLabel.model_validate({field: back}),
        ]
    )

    assert merged.conflicts == {}
    assert merged.reading.value(LabelField(field)) == front


def test_bold_comes_from_the_image_whose_warning_is_used() -> None:
    front = FRONT.model_copy(update={"warning_header_bold": False})  # no warning on the front

    merged = merge_readings([front, BACK])

    assert merged.reading.warning_header_bold is True
    assert merged.reading.warning_body_bold is False


def test_two_warnings_judged_differently_for_bold_are_a_conflict() -> None:
    other = BACK.model_copy(update={"warning_header_bold": None})

    merged = merge_readings([FRONT, BACK, other])

    assert LabelField.HEALTH_WARNING in merged.conflicts


def test_two_warnings_that_differ_in_wording_are_a_conflict() -> None:
    typo = BACK.model_copy(update={"health_warning": HEALTH_WARNING.replace("drink", "drinks")})

    merged = merge_readings([BACK, typo])

    assert merged.conflicts[LabelField.HEALTH_WARNING] == (
        HEALTH_WARNING,
        HEALTH_WARNING.replace("drink", "drinks"),
    )


def test_there_must_be_at_least_one_reading() -> None:
    with pytest.raises(ValueError, match="at least one"):
        merge_readings([])


@given(copies=st.integers(min_value=1, max_value=5))
def test_merging_identical_readings_changes_nothing(copies: int) -> None:
    merged = merge_readings([OLD_TOM_READING] * copies)

    assert merged.reading == OLD_TOM_READING
    assert merged.conflicts == {}
