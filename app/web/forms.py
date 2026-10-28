"""The application form: what the agent types, checked before any label is read."""

from collections.abc import Mapping

from pydantic import ValidationError

from app.domain.models import ApplicationData, BeverageType

FIELDS = (
    "beverage_type",
    "imported",
    "brand_name",
    "fanciful_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "bottler",
    "country_of_origin",
)
LABELS = {
    "beverage_type": "Beverage type",
    "imported": "Imported",
    "brand_name": "Brand name",
    "fanciful_name": "Fanciful name",
    "class_type": "Class/type",
    "alcohol_content": "Alcohol content",
    "net_contents": "Net contents",
    "bottler": "Bottler or importer (name and address)",
    "country_of_origin": "Country of origin",
}
REQUIRED = ("brand_name", "class_type", "net_contents", "bottler")
HINTS = {
    "brand_name": "As the application states it. For example: OLD TOM DISTILLERY",
    "fanciful_name": "A second product name, if the application gives one. For example: Beatrix",
    "class_type": "For example: Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "Required for distilled spirits. For example: 45% Alc./Vol. (90 Proof)",
    "net_contents": "For example: 750 mL",
    "bottler": "The name and address on the application. "
    "For example: Old Tom Distillery, Louisville, Kentucky",
    "country_of_origin": "For example: Mexico",
}
MISSING = "Enter the {label}."
TOO_LONG = "The {label} is too long."


def read_application(values: Mapping[str, str]) -> tuple[ApplicationData | None, dict[str, str]]:
    """The application, or the errors to show next to each field."""
    text = {field: values.get(field, "").strip() for field in FIELDS}
    errors: dict[str, str] = {}

    if text["beverage_type"] not in {member.value for member in BeverageType}:
        errors["beverage_type"] = "Choose the beverage type."
    for field in REQUIRED:
        if not text[field]:
            errors[field] = MISSING.format(label=LABELS[field].lower())
    imported = text["imported"] in ("on", "true", "1")
    if imported and not text["country_of_origin"]:
        errors["country_of_origin"] = "Enter the country of origin for an import."
    if text["beverage_type"] == BeverageType.SPIRITS and not text["alcohol_content"]:
        errors["alcohol_content"] = "Enter the alcohol content; spirits must state it."
    if errors:
        return None, errors

    try:
        application = ApplicationData(
            beverage_type=BeverageType(text["beverage_type"]),
            imported=imported,
            brand_name=text["brand_name"],
            fanciful_name=text["fanciful_name"] or None,
            class_type=text["class_type"],
            alcohol_content=text["alcohol_content"] or None,
            net_contents=text["net_contents"],
            bottler=text["bottler"],
            country_of_origin=(text["country_of_origin"] or None) if imported else None,
        )
    except ValidationError as error:
        for problem in error.errors():
            field = str(problem["loc"][0]) if problem["loc"] else "brand_name"
            errors[field] = TOO_LONG.format(label=LABELS.get(field, field).lower())
        return None, errors
    return application, {}


def form_values(application: ApplicationData) -> dict[str, str]:
    """An application as the form's field values, for pre-filling it from a sample."""
    return {
        "beverage_type": application.beverage_type.value,
        "imported": "on" if application.imported else "",
        "brand_name": application.brand_name,
        "fanciful_name": application.fanciful_name or "",
        "class_type": application.class_type,
        "alcohol_content": application.alcohol_content or "",
        "net_contents": application.net_contents,
        "bottler": application.bottler,
        "country_of_origin": application.country_of_origin or "",
    }
