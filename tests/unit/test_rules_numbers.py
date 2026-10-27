"""Alcohol content and net contents: numbers that must agree with the application."""

import pytest

from app.domain.models import BeverageType, FieldResult, Status
from app.domain.rules.alcohol import check_alcohol
from app.domain.rules.net_contents import check_net_contents

SPIRITS, WINE, BEER = BeverageType.SPIRITS, BeverageType.WINE, BeverageType.BEER


def spirits(expected: str | None, found: str | None) -> FieldResult:
    return check_alcohol(SPIRITS, expected, found, cfr="27 CFR 5.65")


def contents(expected: str | None, found: str | None) -> FieldResult:
    return check_net_contents(expected, found, cfr="27 CFR 5.70")


# ---- alcohol content ----


@pytest.mark.parametrize(
    ("expected", "found"),
    [
        ("45%", "45% Alc./Vol. (90 Proof)"),
        ("45% Alc./Vol.", "ALC. 45% BY VOL."),
        ("45.0%", "45% ALC/VOL"),
    ],
)
def test_same_abv_in_different_formats_passes(expected: str, found: str) -> None:
    result = spirits(expected, found)

    assert result.status is Status.PASS
    assert result.cfr == "27 CFR 5.65"


def test_different_abv_fails_and_says_both_values() -> None:
    result = spirits("45% Alc./Vol.", "40% Alc./Vol.")

    assert result.status is Status.FAIL
    assert any("40%" in note and "45%" in note for note in result.notes)


def test_decimal_point_matters() -> None:
    assert spirits("45%", "4.5% Alc./Vol.").status is Status.FAIL


def test_proof_must_be_twice_the_abv() -> None:
    assert spirits("45%", "45% Alc./Vol. (90 Proof)").status is Status.PASS
    assert spirits("45%", "45% Alc./Vol. (80 Proof)").status is Status.FAIL


def test_proof_without_a_percentage_fails() -> None:
    result = spirits("45%", "90 Proof")

    assert result.status is Status.FAIL
    assert any("percentage" in note for note in result.notes)


@pytest.mark.parametrize("found", [None, "", "   "])
def test_spirits_label_without_alcohol_content_fails(found: str | None) -> None:
    assert spirits("45%", found).status is Status.FAIL
    assert spirits(None, found).status is Status.FAIL


@pytest.mark.parametrize("beverage", [WINE, BEER])
def test_wine_or_beer_with_no_abv_on_either_side_passes(beverage: BeverageType) -> None:
    result = check_alcohol(beverage, None, None, cfr="x")

    assert result.status is Status.PASS
    assert result.notes


def test_wine_note_mentions_the_14_percent_rule() -> None:
    result = check_alcohol(WINE, None, None, cfr="27 CFR 4.36")

    assert any("14%" in note for note in result.notes)


def test_beer_whose_application_states_abv_fails_when_the_label_does_not() -> None:
    assert check_alcohol(BEER, "5% ABV", None, cfr="27 CFR 7.65").status is Status.FAIL


def test_label_abv_that_the_application_does_not_mention_goes_to_review() -> None:
    assert check_alcohol(BEER, None, "5% ABV", cfr="27 CFR 7.65").status is Status.REVIEW


@pytest.mark.parametrize(
    "found",
    [
        "forty-five percent",
        "45% Alc./Vol. ... 40% Alc./Vol.",
        "450% Alc./Vol.",
        "-5% Alc./Vol.",
    ],
    ids=["words", "two-abvs", "impossible-high", "negative"],
)
def test_unreadable_ambiguous_or_impossible_abv_goes_to_review(found: str) -> None:
    result = spirits("45%", found)

    assert result.status is Status.REVIEW
    assert result.notes


def test_decimal_comma_on_imported_wine_matches_a_decimal_point() -> None:
    assert check_alcohol(WINE, "13.5%", "13,5% vol", cfr="x").status is Status.PASS


def test_unreadable_application_abv_goes_to_review() -> None:
    assert spirits("strong", "45% Alc./Vol.").status is Status.REVIEW


# ---- net contents ----


@pytest.mark.parametrize("found", ["750 mL", "750ML", "75 cL", "0.75 L", "25.4 fl oz"])
def test_same_volume_in_any_unit_passes(found: str) -> None:
    result = contents("750 mL", found)

    assert result.status is Status.PASS
    assert result.cfr == "27 CFR 5.70"


@pytest.mark.parametrize("found", ["700 mL", "750 L", "1 L"])
def test_different_volume_fails(found: str) -> None:
    result = contents("750 mL", found)

    assert result.status is Status.FAIL
    assert result.notes


@pytest.mark.parametrize("found", ["750", "75O mL", "25.4 oz"])
def test_unreadable_or_ambiguous_volume_goes_to_review(found: str) -> None:
    assert contents("750 mL", found).status is Status.REVIEW


@pytest.mark.parametrize("found", [None, ""])
def test_missing_net_contents_fails(found: str | None) -> None:
    assert contents("750 mL", found).status is Status.FAIL


@pytest.mark.parametrize("expected", [None, "a bottle"])
def test_missing_or_unreadable_application_volume_goes_to_review(expected: str | None) -> None:
    assert contents(expected, "750 mL").status is Status.REVIEW
