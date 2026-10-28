"""The sample labels the page offers, copied from the test fixtures by scripts/samples.py."""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.domain.models import ApplicationData

SAMPLES_ROOT = Path(__file__).resolve().parent.parent / "samples"


@dataclass(frozen=True)
class Sample:
    id: str
    title: str
    description: str
    application: ApplicationData
    images: tuple[Path, ...]


@cache
def load_samples() -> tuple[Sample, ...]:
    samples = []
    for record_path in sorted(SAMPLES_ROOT.glob("*/sample.json")):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        samples.append(
            Sample(
                id=record["id"],
                title=record["title"],
                description=record["description"],
                application=ApplicationData.model_validate(record["application"]),
                images=tuple(record_path.parent / name for name in record["images"]),
            )
        )
    return tuple(samples)


def find_sample(sample_id: str) -> Sample | None:
    """The sample with exactly this id. Ids are only ever compared, never used as paths."""
    return next((sample for sample in load_samples() if sample.id == sample_id), None)
