"""The application form: what the agent types, checked before any label is read."""

import re
import unicodedata
from collections.abc import Mapping

from pydantic import ValidationError

from app.domain.models import ApplicationData, BeverageType
from app.domain.normalize import parse_alcohol, parse_net_contents, strip_hidden

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
ALCOHOL_UNREADABLE = (
    "Couldn't read this as an alcohol content. For example: 45% Alc./Vol. (90 Proof)"
)
NET_UNREADABLE = "Couldn't read this as net contents. For example: 750 mL, 1 L or 12 fl oz"
TOO_LONG = "The {label} is too long."


def clean(value: str) -> str:
    """Typed or pasted text, tidied: invisible characters dropped, spaces, tabs and non-breaking
    spaces collapsed, and lines (as in a pasted address) joined with commas."""
    lines = []
    for line in unicodedata.normalize("NFC", value).splitlines():
        visible, _ = strip_hidden(line)  # line by line: line breaks count as hidden characters
        if tidied := " ".join(visible.split()):
            lines.append(tidied)
    joined = ""
    for line in lines:
        if not joined:
            joined = line
        else:
            joined += (" " if joined.endswith(",") else ", ") + line
    return joined


def beverage_from(value: str) -> str | None:
    """A beverage type however it was written: "Distilled Spirits", "SPIRITS", "Malt beverage"."""
    lowered = value.casefold()
    if "spirit" in lowered or "distilled" in lowered:
        return BeverageType.SPIRITS.value
    if "wine" in lowered:
        return BeverageType.WINE.value
    if any(word in lowered for word in ("malt", "beer", "ale", "lager")):
        return BeverageType.BEER.value
    return None


def yes_no(value: str) -> bool | None:
    """A yes or no answer in any common form; None if it is neither."""
    lowered = value.casefold().strip()
    if lowered in ("yes", "y", "true", "1", "on", "x", "imported", "import"):
        return True
    if lowered in ("", "no", "n", "false", "0", "off", "domestic"):
        return False
    return None


def read_application(values: Mapping[str, str]) -> tuple[ApplicationData | None, dict[str, str]]:
    """The application, or the errors to show next to each field."""
    text = {field: clean(values.get(field, "")) for field in FIELDS}
    errors: dict[str, str] = {}

    beverage = beverage_from(text["beverage_type"])
    if beverage is None:
        errors["beverage_type"] = "Choose the beverage type."
    for field in REQUIRED:
        if not text[field]:
            errors[field] = MISSING.format(label=LABELS[field].lower())
    imported = yes_no(text["imported"])
    if imported is None:
        errors["imported"] = "Answer yes or no for Imported."
    elif imported and not text["country_of_origin"]:
        errors["country_of_origin"] = "Enter the country of origin for an import."

    alcohol = text["alcohol_content"]
    if re.fullmatch(r"\d{1,3}(?:[.,]\d+)?", alcohol):
        alcohol += "%"  # a bare number in an alcohol field is a percentage
    if beverage == BeverageType.SPIRITS and not alcohol:
        errors["alcohol_content"] = "Enter the alcohol content; spirits must state it."
    elif alcohol:
        parsed = parse_alcohol(alcohol)
        if parsed.problem or (parsed.abv is None and parsed.proof is None):
            errors["alcohol_content"] = ALCOHOL_UNREADABLE
    net = text["net_contents"]
    if re.fullmatch(r"\d+(?:[.,]\d+)?", net):
        errors["net_contents"] = "Add the unit to the net contents, for example 750 mL."
    elif net and parse_net_contents(net).volume is None:
        errors["net_contents"] = NET_UNREADABLE
    if errors or beverage is None:
        return None, errors

    try:
        application = ApplicationData(
            beverage_type=BeverageType(beverage),
            imported=bool(imported),
            brand_name=text["brand_name"],
            fanciful_name=text["fanciful_name"] or None,
            class_type=text["class_type"],
            alcohol_content=alcohol or None,
            net_contents=net,
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
