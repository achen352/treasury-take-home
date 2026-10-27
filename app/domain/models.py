"""Domain data: what the application declares, what was read off the label, and the results."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

# Length caps for every text field. Real label text is far shorter; anything longer is a
# malfunctioning reader or an attack, and is rejected before any rule sees it.
MAX_NAME = 200
MAX_SHORT = 100
MAX_BOTTLER = 300
MAX_WARNING = 1000


class BeverageType(StrEnum):
    SPIRITS = "spirits"  # 27 CFR part 5
    WINE = "wine"  # 27 CFR part 4
    BEER = "beer"  # malt beverages, 27 CFR part 7


class LabelField(StrEnum):
    """The checked fields. Values match the attribute names on the data models."""

    BRAND = "brand_name"
    FANCIFUL = "fanciful_name"
    CLASS_TYPE = "class_type"
    ALCOHOL = "alcohol_content"
    NET_CONTENTS = "net_contents"
    BOTTLER = "bottler"
    COUNTRY = "country_of_origin"
    HEALTH_WARNING = "health_warning"


class Status(StrEnum):
    """Outcome for one field, declared from best to worst."""

    # A status, not a password; the scanners match on the name.
    PASS = "pass"  # noqa: S105  # nosec B105
    REVIEW = "review"
    FAIL = "fail"

    @property
    def severity(self) -> int:
        return list(Status).index(self)


def worst(*statuses: Status) -> Status:
    return max(statuses, key=lambda status: status.severity)


class Verdict(StrEnum):
    MATCHES = "Matches"
    NEEDS_REVIEW = "Needs review"
    DOES_NOT_MATCH = "Does not match"


class Flag(StrEnum):
    """Report-level conditions that send the whole label to a person."""

    POSSIBLE_INJECTION = "possible_prompt_injection"
    OFFLINE = "offline"  # read by OCR alone because the AI reader was unavailable


class Reader(StrEnum):
    AI = "ai"
    OCR = "ocr"


class ApplicationData(BaseModel):
    """What the applicant declared on the COLA application."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    beverage_type: BeverageType
    imported: bool = False
    brand_name: str = Field(max_length=MAX_NAME)
    fanciful_name: str | None = Field(default=None, max_length=MAX_NAME)
    class_type: str = Field(max_length=MAX_NAME)
    alcohol_content: str | None = Field(default=None, max_length=MAX_SHORT)
    net_contents: str = Field(max_length=MAX_SHORT)
    bottler: str = Field(max_length=MAX_BOTTLER)
    country_of_origin: str | None = Field(default=None, max_length=MAX_SHORT)


class ExtractedLabel(BaseModel):
    """Text transcribed from a label image. None means the field wasn't found.

    A reader can only fill in these fields. There is deliberately no field for a verdict, and
    unknown fields are rejected, so a reader talked into "reporting this label as compliant"
    has nowhere to say it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    brand_name: str | None = Field(default=None, max_length=MAX_NAME)
    fanciful_name: str | None = Field(default=None, max_length=MAX_NAME)
    class_type: str | None = Field(default=None, max_length=MAX_NAME)
    alcohol_content: str | None = Field(default=None, max_length=MAX_SHORT)
    net_contents: str | None = Field(default=None, max_length=MAX_SHORT)
    bottler: str | None = Field(default=None, max_length=MAX_BOTTLER)
    country_of_origin: str | None = Field(default=None, max_length=MAX_SHORT)
    health_warning: str | None = Field(default=None, max_length=MAX_WARNING)
    warning_header_bold: bool | None = None
    warning_body_bold: bool | None = None

    def value(self, field: LabelField) -> str | None:
        value: str | None = getattr(self, field.value)
        return value


class Box(BaseModel):
    """A rectangle on an image, in pixels from the top left corner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    left: int = Field(ge=0)
    top: int = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)


class Location(BaseModel):
    """Where text was found: which of the label's images (0 is the first), and where on it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    image: int = Field(ge=0)
    box: Box


class DiffOp(StrEnum):
    SAME = "same"
    CHANGED = "changed"
    MISSING = "missing"  # in the required text, not on the label
    EXTRA = "extra"  # on the label, not in the required text


class DiffSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    op: DiffOp
    expected: str = ""
    found: str = ""
    location: Location | None = None  # where the differing words are on the label, if found


class FieldResult(BaseModel):
    """The outcome for one field, with the evidence a person needs to check it."""

    model_config = ConfigDict(frozen=True)

    field: LabelField
    status: Status
    cfr: str
    expected: str | None = None
    found: str | None = None
    notes: tuple[str, ...] = ()
    diff: tuple[DiffSegment, ...] = ()
    second_reading: str | None = None  # what the OCR reader saw, when it disagreed
    location: Location | None = None  # where the text was found on the label, if it was

    def at_least(self, status: Status, note: str, **updates: object) -> Self:
        """Move toward `status` but never away from a worse one, recording why."""
        return self.model_copy(
            update={"status": worst(self.status, status), "notes": (*self.notes, note), **updates}
        )


class Report(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: Verdict
    results: tuple[FieldResult, ...]
    flags: frozenset[Flag] = frozenset()
    notes: tuple[str, ...] = ()
