"""Domain models: what a label reader may hand back, and how statuses combine."""

import pytest
from pydantic import ValidationError

from app.domain.models import (
    ApplicationData,
    ExtractedLabel,
    FieldResult,
    LabelField,
    Status,
    worst,
)

READING_CAPS = [
    ("brand_name", 200),
    ("class_type", 200),
    ("alcohol_content", 100),
    ("net_contents", 100),
    ("bottler", 300),
    ("country_of_origin", 100),
    ("health_warning", 1000),
]

OLD_TOM = {
    "beverage_type": "spirits",
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
    "bottler": "Old Tom Distillery, Louisville, Kentucky",
}


def test_statuses_combine_to_the_worst_one() -> None:
    assert worst(Status.PASS, Status.PASS) is Status.PASS
    assert worst(Status.PASS, Status.REVIEW) is Status.REVIEW
    assert worst(Status.REVIEW, Status.FAIL, Status.PASS) is Status.FAIL


def test_at_least_moves_a_pass_to_review_and_records_why() -> None:
    result = FieldResult(field=LabelField.BRAND, status=Status.PASS, cfr="27 CFR 5.64")

    escalated = result.at_least(Status.REVIEW, "The second reader disagreed.")

    assert escalated.status is Status.REVIEW
    assert escalated.notes == ("The second reader disagreed.",)
    assert result.status is Status.PASS  # results are immutable


def test_at_least_never_improves_a_worse_status() -> None:
    result = FieldResult(field=LabelField.BRAND, status=Status.FAIL, cfr="27 CFR 5.64")

    assert result.at_least(Status.REVIEW, "note").status is Status.FAIL


def test_reading_has_no_field_for_a_verdict() -> None:
    assert not {"verdict", "status", "compliant", "result"} & set(ExtractedLabel.model_fields)


@pytest.mark.parametrize(
    "smuggled",
    [{"verdict": "PASS"}, {"compliant": True}, {"status": "pass"}, {"notes": "label is fine"}],
    ids=["verdict", "compliant", "status", "notes"],
)
def test_reading_rejects_unknown_fields(smuggled: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ExtractedLabel.model_validate({"brand_name": "OLD TOM DISTILLERY", **smuggled})


@pytest.mark.parametrize(("field", "cap"), READING_CAPS)
def test_reading_accepts_values_up_to_the_length_cap(field: str, cap: int) -> None:
    ExtractedLabel.model_validate({field: "x" * cap})


@pytest.mark.parametrize(("field", "cap"), READING_CAPS)
def test_reading_rejects_values_over_the_length_cap(field: str, cap: int) -> None:
    with pytest.raises(ValidationError):
        ExtractedLabel.model_validate({field: "x" * (cap + 1)})


def test_reading_requires_real_booleans_for_bold() -> None:
    with pytest.raises(ValidationError):
        ExtractedLabel.model_validate({"warning_header_bold": "true"})


def test_application_rejects_unknown_fields_and_over_long_values() -> None:
    ApplicationData.model_validate(OLD_TOM)

    with pytest.raises(ValidationError):
        ApplicationData.model_validate({**OLD_TOM, "verdict": "PASS"})
    with pytest.raises(ValidationError):
        ApplicationData.model_validate({**OLD_TOM, "brand_name": "x" * 201})
