"""Shared test data: the OLD TOM sample from the take-home brief, as each reader would see it."""

from app.domain.constants import HEALTH_WARNING
from app.domain.models import ApplicationData, BeverageType, ExtractedLabel

OLD_TOM_APPLICATION = ApplicationData(
    beverage_type=BeverageType.SPIRITS,
    brand_name="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol_content="45% Alc./Vol. (90 Proof)",
    net_contents="750 mL",
    bottler="Old Tom Distillery, Louisville, Kentucky",
)

OLD_TOM_READING = ExtractedLabel(
    brand_name="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol_content="45% Alc./Vol. (90 Proof)",
    net_contents="750 mL",
    bottler="Distilled and bottled by Old Tom Distillery, Louisville, Kentucky",
    health_warning=HEALTH_WARNING,
    warning_header_bold=True,
    warning_body_bold=False,
)

OLD_TOM_LABEL_LINES = (
    "OLD TOM DISTILLERY",
    "Kentucky Straight Bourbon Whiskey",
    "45% Alc./Vol. (90 Proof)",
    "750 mL",
    "Distilled and bottled by Old Tom Distillery, Louisville, Kentucky",
)
# The warning is kept on one line so tests can alter it with str.replace.
OLD_TOM_OCR_TEXT = "\n".join((*OLD_TOM_LABEL_LINES, HEALTH_WARNING))
