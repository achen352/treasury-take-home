"""Real approved labels from TTB's public COLA registry, with their ground truth."""

import json
from pathlib import Path

import pytest

from app.domain.models import BeverageType, Verdict
from scripts.fixtures import FIXTURES_ROOT, FixtureTruth, load_fixtures

COLA = load_fixtures(FIXTURES_ROOT / "cola")
PRODUCT_TYPES = {
    "Distilled Spirits": BeverageType.SPIRITS,
    "Wine": BeverageType.WINE,
    "Malt Beverage": BeverageType.BEER,
}


def fixture_id(item: tuple[Path, FixtureTruth]) -> str:
    return item[1].id


def registry(folder: Path) -> dict[str, object]:
    loaded: dict[str, object] = json.loads((folder / "registry.json").read_text(encoding="utf-8"))
    return loaded


def test_there_are_at_least_15_real_labels() -> None:
    assert len(COLA) >= 15


def test_the_set_covers_each_beverage_type_and_both_sources() -> None:
    kinds = {(truth.application.beverage_type, truth.application.imported) for _, truth in COLA}

    assert {beverage for beverage, _ in kinds} == set(BeverageType)
    assert {imported for _, imported in kinds} == {True, False}


@pytest.mark.parametrize("item", COLA, ids=fixture_id)
def test_each_label_records_where_it_came_from(item: tuple[Path, FixtureTruth]) -> None:
    folder, truth = item

    assert truth.cola is not None
    assert truth.cola.ttb_id == folder.name == truth.id.removeprefix("cola-")
    assert truth.cola.url.endswith(f"ttbid={truth.cola.ttb_id}")
    assert set(truth.cola.label_sizes) == set(truth.images)
    assert "cola" in truth.tags


@pytest.mark.parametrize("item", COLA, ids=fixture_id)
def test_application_data_agrees_with_the_registry(item: tuple[Path, FixtureTruth]) -> None:
    folder, truth = item
    record = registry(folder)

    assert record["status"] == "APPROVED"
    assert truth.application.brand_name == record["brand_name"]
    assert truth.application.beverage_type is PRODUCT_TYPES[str(record["product_type"])]
    assert truth.application.imported == (record["source"] == "Imported")
    if truth.application.imported:
        assert truth.application.country_of_origin == str(record["origin_code"]).title()


@pytest.mark.parametrize("item", COLA, ids=fixture_id)
def test_approved_labels_match_unless_a_deviation_is_documented(
    item: tuple[Path, FixtureTruth],
) -> None:
    _, truth = item
    if {"deviation", "uncertain-bold"} & set(truth.tags):
        # TTB approved the label, but something on it differs from 16.21 or can't be verified.
        assert Verdict.MATCHES not in truth.acceptable
        assert "Deviation:" in truth.description or "Uncertain:" in truth.description
    else:
        assert truth.acceptable == (Verdict.MATCHES,)


def test_aniche_records_beatrix_as_the_fanciful_name_not_the_brand() -> None:
    # The big name on the label is the fanciful name; the brand appears only in the bottler
    # statement. A reader that reports "Beatrix" as the brand fails the brand check.
    aniche = next(truth for _, truth in COLA if truth.id == "cola-26247001000534")

    assert aniche.application.brand_name == "ANICHE CELLARS"
    assert aniche.application.fanciful_name == "Beatrix"
    assert aniche.printed.fanciful_name == "Beatrix"
    assert "Beatrix" not in aniche.other_text
