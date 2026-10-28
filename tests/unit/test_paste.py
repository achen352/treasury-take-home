"""Filling the application form from pasted text: labeled lines in common wordings, or JSON."""

import pytest

from app.web.paste import MAX_PASTE_CHARS, PasteTooLong, parse_application_text

COLA_STYLE = """
TYPE OF PRODUCT: Distilled Spirits
SOURCE OF PRODUCT: Domestic
BRAND NAME: OLD TOM DISTILLERY
FANCIFUL NAME:
Class/Type: Kentucky Straight Bourbon Whiskey
Alcohol Content: 45% Alc./Vol. (90 Proof)
Net Contents: 750 mL
Name and Address of Applicant:
Old Tom Distillery
Louisville, Kentucky
"""


def test_labeled_lines_like_a_cola_application_fill_every_field() -> None:
    parsed = parse_application_text(COLA_STYLE)

    assert parsed.values == {
        "beverage_type": "spirits",
        "imported": "",
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "alcohol_content": "45% Alc./Vol. (90 Proof)",
        "net_contents": "750 mL",
        "bottler": "Old Tom Distillery, Louisville, Kentucky",
    }


@pytest.mark.parametrize(
    ("line", "field", "value"),
    [
        ("Brand: Stone's Throw", "brand_name", "Stone's Throw"),
        ("brand name - STONE'S THROW", "brand_name", "STONE'S THROW"),
        ("Class and type: Vodka", "class_type", "Vodka"),
        ("ABV: 40%", "alcohol_content", "40%"),
        ("Volume = 1 L", "net_contents", "1 L"),
        ("Bottled by: Acme Spirits, Austin, TX", "bottler", "Acme Spirits, Austin, TX"),
        (
            "Importer: Eastern Liquors USA, Westbury, NY",
            "bottler",
            "Eastern Liquors USA, Westbury, NY",
        ),
        ("Country of origin: Mexico", "country_of_origin", "Mexico"),
        ("Fanciful name: Beatrix", "fanciful_name", "Beatrix"),
        ("Product type: Wine", "beverage_type", "wine"),
        ("Type of product: Malt Beverage", "beverage_type", "beer"),
        ("Imported: yes", "imported", "on"),
        ("Source of product: Imported", "imported", "on"),
    ],
)
def test_common_wordings_are_recognised(line: str, field: str, value: str) -> None:
    assert parse_application_text(line).values[field] == value


def test_json_works_too_with_our_names_or_friendly_ones() -> None:
    parsed = parse_application_text(
        '{"Brand Name": "OLD TOM DISTILLERY", "class_type": "Bourbon", "imported": true,'
        ' "Country of Origin": "Scotland", "ABV": 43}'
    )

    assert parsed.values == {
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Bourbon",
        "imported": "on",
        "country_of_origin": "Scotland",
        "alcohol_content": "43",
    }


def test_it_says_what_it_filled_and_what_it_could_not_find() -> None:
    parsed = parse_application_text("Brand Name: OLD TOM\nSerial Number: 26-001\nColour: amber")

    assert parsed.filled == ["brand_name"]
    assert "class_type" in parsed.missing
    assert parsed.unrecognised == ["Serial Number", "Colour"]


def test_text_with_no_labels_fills_nothing() -> None:
    parsed = parse_application_text("Just some notes about a bourbon label.")

    assert parsed.values == {}


def test_broken_json_is_read_as_text_and_never_crashes() -> None:
    assert parse_application_text('{"Brand Name": "OLD TOM"').values == {}


def test_very_long_pastes_are_refused() -> None:
    with pytest.raises(PasteTooLong):
        parse_application_text("Brand: x\n" * (MAX_PASTE_CHARS // 4))
