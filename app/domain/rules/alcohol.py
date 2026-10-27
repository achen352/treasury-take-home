"""Alcohol content: the percentage must match the application, and any proof must be 2 x ABV."""

from app.domain.constants import ABV_REQUIRED
from app.domain.models import BeverageType, FieldResult, LabelField, Status
from app.domain.normalize import format_number, parse_alcohol


def check_alcohol(
    beverage_type: BeverageType, expected: str | None, found: str | None, *, cfr: str
) -> FieldResult:
    def result(status: Status, note: str) -> FieldResult:
        return FieldResult(
            field=LabelField.ALCOHOL,
            status=status,
            cfr=cfr,
            expected=expected,
            found=found,
            notes=(note,),
        )

    label_text = (found or "").strip()
    application_text = (expected or "").strip()

    if not label_text:
        if application_text:
            return result(Status.FAIL, "Not found on the label.")
        if beverage_type in ABV_REQUIRED:
            return result(Status.FAIL, "Distilled spirits labels must state the alcohol content.")
        note = "Not required, and neither the application nor the label states it."
        if beverage_type is BeverageType.WINE:
            note += " Wine above 14% alcohol must state it."
        return result(Status.PASS, note)

    label = parse_alcohol(label_text)
    if label.problem:
        return result(Status.REVIEW, label.problem)
    if label.abv is not None and label.abv_high is not None:
        stated = f"{format_number(label.abv)}% to {format_number(label.abv_high)}%"
        application_range = parse_alcohol(application_text)
        if (application_range.abv, application_range.abv_high) == (label.abv, label.abv_high):
            return result(Status.PASS, f"Same alcohol content range ({stated}).")
        return result(
            Status.REVIEW,
            f"The label states a range ({stated}); a person should compare it with the "
            "application.",
        )
    if label.abv is None:
        return result(
            Status.FAIL,
            "The label gives proof but not the percentage of alcohol by volume, which is required.",
        )
    abv = format_number(label.abv)
    if label.proof is not None and label.proof != 2 * label.abv:
        return result(
            Status.FAIL,
            f"Proof must be twice the alcohol by volume: {abv}% is "
            f"{format_number(2 * label.abv)} proof, but the label says "
            f"{format_number(label.proof)} proof.",
        )

    if not application_text:
        return result(
            Status.REVIEW, "The label states an alcohol content but the application doesn't."
        )
    application = parse_alcohol(application_text)
    if application.abv is None:
        detail = f": {application.problem}" if application.problem else "."
        return result(Status.REVIEW, f"Couldn't read the application's alcohol content{detail}")

    if label.abv == application.abv:
        if label_text == application_text:
            return result(Status.PASS, "Same alcohol content.")
        return result(Status.PASS, "Same alcohol content, written differently.")
    return result(
        Status.FAIL,
        f"The label says {abv}% but the application says {format_number(application.abv)}%.",
    )
