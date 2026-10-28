"""The application form copes with how people actually type: misformatted data is tidied or
explained, never a crash and never a confusing result later."""

import pytest

from app.web.forms import read_application

GOOD = {
    "beverage_type": "spirits",
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
    "bottler": "Old Tom Distillery, Louisville, Kentucky",
}


def read(**changes: str) -> tuple[object, dict[str, str]]:
    return read_application({**GOOD, **changes})


def test_stray_spaces_tabs_line_breaks_and_invisible_characters_are_tidied() -> None:
    application, errors = read(
        brand_name="  OLD\tTOM \N{NO-BREAK SPACE}DISTILLERY\N{ZERO WIDTH SPACE} \n",
        bottler="Old Tom Distillery\nLouisville,   Kentucky",
    )

    assert errors == {}
    assert application.brand_name == "OLD TOM DISTILLERY"  # type: ignore[attr-defined]
    assert application.bottler == "Old Tom Distillery, Louisville, Kentucky"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("written", "meant"),
    [
        ("Distilled Spirits", "spirits"),
        ("SPIRITS", "spirits"),
        ("spirit", "spirits"),
        ("Wine", "wine"),
        ("Malt Beverage", "beer"),
        ("beer", "beer"),
    ],
)
def test_beverage_types_written_loosely_are_understood(written: str, meant: str) -> None:
    application, errors = read(beverage_type=written, alcohol_content="12%")

    assert errors == {}
    assert application.beverage_type == meant  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("written", "imported"),
    [
        ("Yes", True),
        ("Y", True),
        ("TRUE", True),
        ("1", True),
        ("Imported", True),
        ("on", True),
        ("No", False),
        ("n", False),
        ("false", False),
        ("Domestic", False),
        ("", False),
    ],
)
def test_yes_and_no_are_understood_in_any_form(written: str, imported: bool) -> None:
    application, errors = read(imported=written, country_of_origin="Mexico")

    assert errors == {}
    assert application.imported is imported  # type: ignore[attr-defined]


def test_an_answer_that_is_neither_yes_nor_no_is_explained() -> None:
    _, errors = read(imported="maybe")

    assert "yes or no" in errors["imported"]


def test_a_bare_number_for_alcohol_is_read_as_a_percentage() -> None:
    application, errors = read(alcohol_content="45")

    assert errors == {}
    assert application.alcohol_content == "45%"  # type: ignore[attr-defined]


@pytest.mark.parametrize("written", ["forty-five", "strong", "45 degrees"])
def test_alcohol_that_cannot_be_read_gets_a_clear_message(written: str) -> None:
    _, errors = read(alcohol_content=written)

    assert "For example: 45% Alc./Vol." in errors["alcohol_content"]


def test_net_contents_without_a_unit_ask_for_one() -> None:
    _, errors = read(net_contents="750")

    assert "unit" in errors["net_contents"]
    assert "750 mL" in errors["net_contents"]


@pytest.mark.parametrize("written", ["750ml", "750 ML", "1 liter", "25.4 fl oz", "1 PINT"])
def test_net_contents_in_any_common_form_are_accepted(written: str) -> None:
    assert read(net_contents=written)[1] == {}
