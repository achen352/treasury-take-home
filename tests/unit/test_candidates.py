"""Choosing the brand, fanciful name and bottler statement from what the label prints.

Real labels show several names (house brand, brewery, vineyard) and several statements
(producer and importer). The AI lists them all without knowing the application; code picks the
one the application describes, by running the same checks the verifier runs.
"""

from hypothesis import given
from hypothesis import strategies as st

from app.domain.candidates import choose_names
from app.domain.models import ExtractedLabel, LabelField, Status, Verdict
from app.domain.verifier import verify
from tests.samples import OLD_TOM_APPLICATION, OLD_TOM_READING

ROYAL_STAG = OLD_TOM_APPLICATION.model_copy(
    update={
        "brand_name": "ROYAL STAG",
        "imported": True,
        "country_of_origin": "India",
        "bottler": "Eastern Liquors USA Inc, Westbury, NY",
    }
)


def test_the_most_prominent_name_is_kept_when_it_matches() -> None:
    chosen = choose_names(
        ExtractedLabel(brand_name="ROYAL STAG"),
        names=("SEAGRAM'S",),
        statements=(),
        application=ROYAL_STAG,
    )

    assert chosen.reading.brand_name == "ROYAL STAG"
    assert chosen.doubts == {}


def test_a_brand_found_only_among_the_other_names_is_used_but_sent_to_review() -> None:
    chosen = choose_names(
        ExtractedLabel(brand_name="SEAGRAM'S"),
        names=("ROYAL STAG",),
        statements=(),
        application=ROYAL_STAG,
    )

    assert chosen.reading.brand_name == "ROYAL STAG"
    assert "SEAGRAM'S" in chosen.doubts[LabelField.BRAND]


def test_a_sticker_over_the_brand_can_never_pass_on_a_name_from_elsewhere() -> None:
    # The sticker reads BLUE RIDGE SPIRITS; Old Tom Distillery is only in the bottler line.
    chosen = choose_names(
        ExtractedLabel(brand_name="BLUE RIDGE SPIRITS"),
        names=("Old Tom Distillery",),
        statements=(),
        application=OLD_TOM_APPLICATION,
    )
    report = verify(
        OLD_TOM_APPLICATION,
        OLD_TOM_READING.model_copy(update={"brand_name": chosen.reading.brand_name}),
        doubts=chosen.doubts,
    )

    assert next(r for r in report.results if r.field is LabelField.BRAND).status is Status.REVIEW
    assert report.verdict is Verdict.NEEDS_REVIEW


def test_a_brand_printed_in_both_scripts_is_kept_for_a_latin_application() -> None:
    application = OLD_TOM_APPLICATION.model_copy(update={"brand_name": "REA 25"})

    chosen = choose_names(
        ExtractedLabel(brand_name="려 REA 25"),
        names=("국순당",),
        statements=(),
        application=application,
    )

    assert chosen.reading.brand_name == "려 REA 25"
    assert chosen.doubts == {}


def test_with_no_good_match_the_closest_name_is_kept_for_the_check_to_judge() -> None:
    chosen = choose_names(
        ExtractedLabel(),
        names=("BLUE RIDGE SPIRITS", "OLD TOMS DISTILLERY"),
        statements=(),
        application=OLD_TOM_APPLICATION,
    )

    assert chosen.reading.brand_name == "OLD TOMS DISTILLERY"


def test_no_names_means_no_brand() -> None:
    chosen = choose_names(
        ExtractedLabel(), names=(), statements=(), application=OLD_TOM_APPLICATION
    )

    assert chosen.reading.brand_name is None


def test_the_importers_statement_is_chosen_when_the_application_names_the_importer() -> None:
    statements = (
        "BLENDED AND BOTTLED BY PERNOD RICARD INDIA PVT. LTD., GWALIOR",
        "IMPORTED BY : EASTERN LIQUORS USA INC WESTBURY NY 11590",
    )

    reading = choose_names(
        ExtractedLabel(), names=("ROYAL STAG",), statements=statements, application=ROYAL_STAG
    ).reading

    assert reading.bottler == statements[1]


def test_a_fanciful_name_among_the_names_is_chosen() -> None:
    application = OLD_TOM_APPLICATION.model_copy(update={"fanciful_name": "LIL' PINE IPA"})

    reading = choose_names(
        ExtractedLabel(),
        names=("SWITCHBACK", "Lil' Pine IPA"),
        statements=(),
        application=application,
    ).reading

    assert reading.fanciful_name == "Lil' Pine IPA"


def test_a_fanciful_name_printed_within_the_class_type_is_found_there() -> None:
    application = OLD_TOM_APPLICATION.model_copy(update={"fanciful_name": "BOURBON"})

    reading = choose_names(
        ExtractedLabel(class_type="STRAIGHT BOURBON WHISKEY"),
        names=("BELLE ISLE",),
        statements=(),
        application=application,
    ).reading

    assert reading.fanciful_name == "BOURBON"


def test_no_fanciful_name_is_chosen_when_the_application_has_none() -> None:
    reading = choose_names(
        ExtractedLabel(),
        names=("OLD TOM DISTILLERY", "Small Batch"),
        statements=(),
        application=OLD_TOM_APPLICATION,
    ).reading

    assert reading.fanciful_name is None


def test_a_reader_that_already_chose_is_one_more_candidate() -> None:
    reading = choose_names(
        ExtractedLabel(brand_name="OLD TOM DISTILLERY", bottler="Bottled by Old Tom Distillery"),
        names=("KENTUCKY RESERVE",),
        statements=(),
        application=OLD_TOM_APPLICATION,
    ).reading

    assert reading.brand_name == "OLD TOM DISTILLERY"
    assert reading.bottler == "Bottled by Old Tom Distillery"


def test_other_fields_are_left_as_they_were_read() -> None:
    original = ExtractedLabel(class_type="Kentucky Straight Bourbon Whiskey", net_contents="750 mL")

    reading = choose_names(
        original, names=("OLD TOM DISTILLERY",), statements=(), application=OLD_TOM_APPLICATION
    ).reading

    assert reading.class_type == original.class_type
    assert reading.net_contents == original.net_contents


@given(names=st.lists(st.text(max_size=30), max_size=6))
def test_the_chosen_brand_is_always_text_printed_on_the_label(names: list[str]) -> None:
    reading = choose_names(
        ExtractedLabel(), names=tuple(names), statements=(), application=OLD_TOM_APPLICATION
    ).reading

    assert reading.brand_name is None or reading.brand_name in names


def test_the_class_type_that_matches_the_application_is_used_when_images_differ() -> None:
    application = OLD_TOM_APPLICATION.model_copy(update={"class_type": "Chardonnay"})

    chosen = choose_names(
        ExtractedLabel(class_type="Chardonnay Vino varietale d'Italia"),
        names=(),
        statements=(),
        class_types=("Chardonnay Vino varietale d'Italia", "CHARDONNAY"),
        application=application,
    )

    assert chosen.reading.class_type == "CHARDONNAY"


def test_a_fanciful_name_the_reader_took_for_the_brand_is_found_there() -> None:
    application = OLD_TOM_APPLICATION.model_copy(
        update={"brand_name": "ADK FOX BREWING", "fanciful_name": "COOKED AT 70"}
    )

    chosen = choose_names(
        ExtractedLabel(brand_name="Cooked at 70"),
        names=("ADK FOX BREWING",),
        statements=(),
        application=application,
    )

    assert chosen.reading.fanciful_name == "Cooked at 70"
    assert chosen.reading.brand_name == "ADK FOX BREWING"


def test_a_country_named_only_in_an_address_is_found_there() -> None:
    application = OLD_TOM_APPLICATION.model_copy(
        update={"imported": True, "country_of_origin": "Republic of Armenia"}
    )
    statement = "Produced by: OHANYAN BRANDY COMPANY LLC Yerevan, Republic of Armenia, 0085"

    chosen = choose_names(
        ExtractedLabel(), names=(), statements=(statement,), application=application
    )

    assert chosen.reading.country_of_origin == "Republic of Armenia"


def test_a_country_already_read_is_kept() -> None:
    application = OLD_TOM_APPLICATION.model_copy(
        update={"imported": True, "country_of_origin": "Italy"}
    )

    chosen = choose_names(
        ExtractedLabel(country_of_origin="Product of Italy"),
        names=(),
        statements=("Bottled by Cantine Pirovano, Calco, Italia",),
        application=application,
    )

    assert chosen.reading.country_of_origin == "Product of Italy"
