"""Brand, class/type, bottler and country of origin: text that must match the application."""

import pytest

from app.domain.models import FieldResult, LabelField, Status
from app.domain.rules.names import check_bottler, check_country, check_name

CYRILLIC_O = "\N{CYRILLIC CAPITAL LETTER O}"


def brand(expected: str, found: str | None) -> FieldResult:
    return check_name(LabelField.BRAND, expected, found, cfr="27 CFR 5.64")


# ---- brand and class/type ----


def test_exact_match_passes() -> None:
    result = brand("OLD TOM DISTILLERY", "OLD TOM DISTILLERY")

    assert result.status is Status.PASS
    assert result.cfr == "27 CFR 5.64"
    assert (result.expected, result.found) == ("OLD TOM DISTILLERY", "OLD TOM DISTILLERY")


def test_capitalization_only_difference_passes_with_a_note() -> None:
    result = brand("Stone's Throw", "STONE'S THROW")  # Dave's example

    assert result.status is Status.PASS
    assert any("capitalization" in note for note in result.notes)


@pytest.mark.parametrize(
    ("expected", "found"),
    [
        ("Stone's Throw", "STONE\N{RIGHT SINGLE QUOTATION MARK}S THROW"),
        ("Smith & Sons Co.", "SMITH AND SONS COMPANY"),
        ("Old Tom Distillery", "OLD TOM DISTILLERY."),
    ],
)
def test_punctuation_spacing_and_abbreviation_differences_pass_with_a_note(
    expected: str, found: str
) -> None:
    result = brand(expected, found)

    assert result.status is Status.PASS
    assert result.notes


def test_class_type_uses_the_same_matching() -> None:
    result = check_name(
        LabelField.CLASS_TYPE,
        "Kentucky Straight Bourbon Whiskey",
        "KENTUCKY STRAIGHT BOURBON WHISKEY",
        cfr="27 CFR 5.63",
    )

    assert result.status is Status.PASS
    assert result.field is LabelField.CLASS_TYPE


def test_near_miss_goes_to_review() -> None:
    result = brand("OLD TOM DISTILLERY", "OLD TOM DISTILLERS")

    assert result.status is Status.REVIEW
    assert any("similar" in note for note in result.notes)


@pytest.mark.parametrize("found", ["BLUE RIDGE SPIRITS", None, ""])
def test_different_or_missing_brand_fails(found: str | None) -> None:
    assert brand("OLD TOM DISTILLERY", found).status is Status.FAIL


@pytest.mark.parametrize(
    ("expected", "found"),
    [("!!!", "???"), ("", ""), ("   ", "   "), ("OLD TOM DISTILLERY", "...")],
)
def test_values_with_no_letters_or_numbers_never_match(expected: str, found: str) -> None:
    assert brand(expected, found).status is Status.FAIL


def test_unusable_application_value_goes_to_review_not_pass() -> None:
    assert brand("???", "OLD TOM DISTILLERY").status is Status.REVIEW


@pytest.mark.parametrize(
    "found",
    ["OLD TOM DISTILLERY RESERVE", "OLD TOM", "TOM OLD DISTILLERY", "DISTILLERY OLD TOM"],
    ids=["extra-word", "missing-word", "reordered", "rotated"],
)
def test_extra_missing_or_reordered_words_are_never_a_pass(found: str) -> None:
    assert brand("OLD TOM DISTILLERY", found).status is not Status.PASS


def test_lookalike_letter_from_another_alphabet_goes_to_review() -> None:
    result = brand("OLD TOM DISTILLERY", f"OLD T{CYRILLIC_O}M DISTILLERY")

    assert result.status is Status.REVIEW
    assert any("CYRILLIC CAPITAL LETTER O" in note for note in result.notes)


def test_lookalike_letters_never_rescue_a_mismatch() -> None:
    assert brand("OLD TOM DISTILLERY", f"BLUE RIDGE {CYRILLIC_O}").status is Status.FAIL


def test_abbreviation_is_not_confused_with_a_different_word() -> None:
    assert brand("Smith District", "Smith Dist.").status is not Status.PASS


# ---- bottler ----

BOTTLER = "Old Tom Distillery, Louisville, KY"


@pytest.mark.parametrize(
    "found",
    [
        "Old Tom Distillery, Louisville, KY",
        "Bottled by Old Tom Distillery, Louisville, KY",
        "DISTILLED AND BOTTLED BY OLD TOM DISTILLERY LOUISVILLE KY",
        "Old Tom Dist., Louisville, KY",
    ],
)
def test_bottler_ignores_bottled_by_phrasing_and_cosmetic_differences(found: str) -> None:
    assert check_bottler(BOTTLER, found, cfr="27 CFR 5.66-5.68").status is Status.PASS


def test_bottler_near_miss_goes_to_review() -> None:
    result = check_bottler(BOTTLER, "Old Tom Distillery, Louisville, Kentucky", cfr="x")

    assert result.status is Status.REVIEW


@pytest.mark.parametrize("found", ["Bottled by Smith Brewing, Denver, CO", None, ""])
def test_unrelated_or_missing_bottler_fails(found: str | None) -> None:
    assert check_bottler(BOTTLER, found, cfr="x").status is Status.FAIL


# ---- country of origin ----


@pytest.mark.parametrize(
    "found",
    [
        "Mexico",
        "Product of Mexico",
        "MADE IN MEXICO",
        "Hecho en M\N{LATIN SMALL LETTER E WITH ACUTE}xico",
    ],
)
def test_country_matches_with_or_without_the_usual_wording(found: str) -> None:
    assert check_country("Mexico", found, cfr="27 CFR 5.69").status is Status.PASS


@pytest.mark.parametrize("found", ["France", None, "", "Product of New Mexico"])
def test_wrong_or_missing_country_fails(found: str | None) -> None:
    assert check_country("Mexico", found, cfr="27 CFR 5.69").status is Status.FAIL


def test_application_without_a_country_goes_to_review() -> None:
    assert check_country(None, "Product of Mexico", cfr="27 CFR 5.69").status is Status.REVIEW


# ---- what real approved labels do ----


def test_names_that_differ_only_in_spacing_pass_with_a_note() -> None:
    result = brand("TERREPASSERI", "TERRE PASSERI")

    assert result.status is Status.PASS
    assert any("spacing" in note for note in result.notes)


@pytest.mark.parametrize(
    ("expected", "found"),
    [
        (
            "Switchback Brewing Co., Burlington, Vermont",
            "BREWED IN BURLINGTON, VERMONT BY SWITCHBACK BREWING CO.",
        ),
        (
            "Tox Brewing Co., New London, CT",
            "PROUDLY BREWED AND PACKAGED BY TOX BREWING CO. IN NEW LONDON, CT",
        ),
        (
            "Aniche Cellars, Cook, Washington USA",
            "Produced and bottled by Aniche Cellars in Cook, Washington USA",
        ),
    ],
    ids=["place-first", "proudly-and-in", "in-before-place"],
)
def test_bottler_words_in_any_order_pass(expected: str, found: str) -> None:
    assert check_bottler(expected, found, cfr="x").status is Status.PASS


@pytest.mark.parametrize(
    ("expected", "found"),
    [("Armenia", "Republic of Armenia"), ("Germany", "Product of the Federal Republic of Germany")],
)
def test_long_form_country_names_match(expected: str, found: str) -> None:
    assert check_country(expected, found, cfr="x").status is Status.PASS
