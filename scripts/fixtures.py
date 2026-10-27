"""Ground truth for test labels: each fixture's application, what is legible on the label, and
which overall results are acceptable.

Every fixture lives in its own folder with a truth.json and its images (front first).
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.models import ApplicationData, ExtractedLabel, LabelField, Verdict

FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
TRUTH_FILE = "truth.json"


class ColaSource(BaseModel):
    """Where a real label came from in TTB's public COLA registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ttb_id: str = Field(pattern=r"^\d{14}$")
    url: str = Field(pattern=r"^https://ttbonline\.gov/")
    label_sizes: dict[str, str] = {}  # image file -> physical size, as the registry states it


class FixtureTruth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str
    images: tuple[str, ...] = Field(min_length=1)
    application: ApplicationData
    # What a careful person can read on the label (all images together). Text drawn but made
    # illegible, such as a warning wiped out by glare, is not here.
    printed: ExtractedLabel
    other_text: tuple[str, ...] = ()  # other legible text, such as an injection attempt
    hidden_text: tuple[str, ...] = ()  # in the file but invisible to a person
    acceptable: tuple[Verdict, ...] = Field(min_length=1)
    tags: tuple[str, ...] = ()
    cola: ColaSource | None = None

    @field_validator("acceptable", "tags", mode="after")
    @classmethod
    def _sorted_and_unique[T: str](cls, values: tuple[T, ...]) -> tuple[T, ...]:
        # Sets are stored sorted so that regenerating fixtures gives identical files.
        return tuple(sorted(set(values)))

    @property
    def never_matches(self) -> bool:
        return Verdict.MATCHES not in self.acceptable

    @property
    def visible_text(self) -> str:
        """Everything legible on the label, as a perfect OCR reader would return it."""
        fields = [self.printed.value(field) for field in LabelField]
        return "\n".join(text for text in (*fields, *self.other_text) if text)


def load_fixtures(folder: Path) -> list[tuple[Path, FixtureTruth]]:
    """Every fixture under `folder`, sorted by folder name."""
    if not folder.is_dir():
        return []
    return [
        (path.parent, FixtureTruth.model_validate(json.loads(path.read_text(encoding="utf-8"))))
        for path in sorted(folder.glob(f"*/{TRUTH_FILE}"))
    ]
