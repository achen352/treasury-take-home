"""When the AI and OCR readers disagree, results only ever move toward a person."""

import textwrap

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.constants import HEALTH_WARNING, WARNING_CFR
from app.domain.crosscheck import cross_check, offline_policy
from app.domain.models import FieldResult, LabelField, Status
from tests.samples import OLD_TOM_LABEL_LINES, OLD_TOM_OCR_TEXT


def passing(field: LabelField, found: str | None) -> FieldResult:
    return FieldResult(field=field, status=Status.PASS, cfr="27 CFR 5.64", found=found)


WARNING_PASS = FieldResult(
    field=LabelField.HEALTH_WARNING,
    status=Status.PASS,
    cfr=WARNING_CFR,
    expected=HEALTH_WARNING,
    found=HEALTH_WARNING,
)
OLD_TOM_RESULTS = [
    passing(LabelField.BRAND, "OLD TOM DISTILLERY"),
    passing(LabelField.CLASS_TYPE, "Kentucky Straight Bourbon Whiskey"),
    passing(LabelField.ALCOHOL, "45% Alc./Vol. (90 Proof)"),
    passing(LabelField.NET_CONTENTS, "750 mL"),
    passing(
        LabelField.BOTTLER, "Distilled and bottled by Old Tom Distillery, Louisville, Kentucky"
    ),
    WARNING_PASS,
]

results_strategy = st.lists(
    st.builds(
        FieldResult,
        field=st.sampled_from(LabelField),
        status=st.sampled_from(Status),
        cfr=st.just("27 CFR 5.64"),
        found=st.none() | st.text(max_size=80),
    ),
    max_size=8,
)


def test_agreement_leaves_every_result_unchanged() -> None:
    assert cross_check(OLD_TOM_RESULTS, OLD_TOM_OCR_TEXT) == OLD_TOM_RESULTS


def test_warning_wrapped_across_lines_by_ocr_is_still_confirmed() -> None:
    ocr = "\n".join((*OLD_TOM_LABEL_LINES, *textwrap.wrap(HEALTH_WARNING, width=40)))

    assert cross_check([WARNING_PASS], ocr) == [WARNING_PASS]


def test_warning_printed_in_all_caps_is_still_confirmed() -> None:
    ocr = OLD_TOM_OCR_TEXT.replace(HEALTH_WARNING, HEALTH_WARNING.upper())

    assert cross_check([WARNING_PASS], ocr) == [WARNING_PASS]


def test_small_ocr_noise_in_a_name_does_not_cause_a_review() -> None:
    ocr = OLD_TOM_OCR_TEXT.replace("Bourbon Whiskey", "Bourbon Whiskcy")
    [result] = cross_check(
        [passing(LabelField.CLASS_TYPE, "Kentucky Straight Bourbon Whiskey")], ocr
    )

    assert result.status is Status.PASS


def test_ai_warning_that_ocr_reads_differently_goes_to_review_with_both_readings() -> None:
    ocr = OLD_TOM_OCR_TEXT.replace("should not drink", "should avoid drinking")

    [result] = cross_check([WARNING_PASS], ocr)

    assert result.status is Status.REVIEW
    assert result.found == HEALTH_WARNING
    assert result.second_reading is not None
    assert "avoid drinking" in result.second_reading


def test_typo_the_ai_quietly_fixed_is_caught_even_though_it_is_one_letter() -> None:
    ocr = OLD_TOM_OCR_TEXT.replace("alcoholic beverages during", "alcholic beverages during")

    [result] = cross_check([WARNING_PASS], ocr)

    assert result.status is Status.REVIEW
    assert result.second_reading is not None
    assert "alcholic" in result.second_reading


def test_title_case_header_seen_only_by_ocr_goes_to_review() -> None:
    ocr = OLD_TOM_OCR_TEXT.replace("GOVERNMENT WARNING:", "Government Warning:")

    assert cross_check([WARNING_PASS], ocr)[0].status is Status.REVIEW


def test_warning_ocr_cannot_find_at_all_goes_to_review() -> None:
    ocr = "\n".join(OLD_TOM_LABEL_LINES)

    assert cross_check([WARNING_PASS], ocr)[0].status is Status.REVIEW


def test_value_ocr_cannot_find_goes_to_review() -> None:
    [result] = cross_check(
        [passing(LabelField.BRAND, "OLD TOM DISTILLERY")], "BLUE RIDGE SPIRITS 40% ALC/VOL 750 mL"
    )

    assert result.status is Status.REVIEW
    assert any("couldn't find" in note for note in result.notes)


def test_short_ocr_text_does_not_confirm_a_longer_reading() -> None:
    [result] = cross_check([passing(LabelField.BRAND, "OLD TOM DISTILLERY")], "OLD")

    assert result.status is Status.REVIEW


@pytest.mark.parametrize("ocr", ["", "   \n ", "@@@ --- ..."])
def test_ocr_that_read_nothing_confirms_nothing(ocr: str) -> None:
    checked = cross_check(OLD_TOM_RESULTS, ocr)

    assert all(result.status is Status.REVIEW for result in checked)


def test_results_with_nothing_read_are_left_alone() -> None:
    not_required = passing(LabelField.ALCOHOL, None)

    assert cross_check([not_required], "OLD TOM") == [not_required]
    assert cross_check([not_required], "") == [not_required]


@given(results_strategy, st.text(max_size=400))
def test_disagreement_never_improves_a_result(results: list[FieldResult], ocr: str) -> None:
    checked = cross_check(results, ocr)

    for before, after in zip(results, checked, strict=True):
        if before.status is Status.PASS:
            assert after.status in {Status.PASS, Status.REVIEW}
        else:
            assert after.status is before.status


# ---- offline: OCR is the only reader ----


def test_offline_fails_become_review_and_the_warning_is_never_a_pass() -> None:
    results = [
        FieldResult(field=LabelField.BRAND, status=Status.FAIL, cfr="x"),
        passing(LabelField.NET_CONTENTS, "750 mL"),
        WARNING_PASS,
        FieldResult(field=LabelField.CLASS_TYPE, status=Status.REVIEW, cfr="x"),
    ]

    adjusted = offline_policy(results)

    assert [result.status for result in adjusted] == [
        Status.REVIEW,
        Status.PASS,
        Status.REVIEW,
        Status.REVIEW,
    ]
    assert adjusted[0].notes
    assert adjusted[2].notes


@given(results_strategy)
def test_offline_never_fails_and_never_passes_the_warning(results: list[FieldResult]) -> None:
    for before, after in zip(results, offline_policy(results), strict=True):
        assert after.status is not Status.FAIL
        if before.status is Status.REVIEW:
            assert after.status is Status.REVIEW
        if after.field is LabelField.HEALTH_WARNING:
            assert after.status is Status.REVIEW
