"""What the results page shows: a report and its label images, in plain words and outlines."""

import base64
import io
from collections.abc import Sequence
from dataclasses import dataclass, field

from PIL import Image

from app.domain.models import (
    DiffOp,
    FieldResult,
    Flag,
    LabelField,
    Location,
    Report,
    Status,
    Verdict,
)
from app.readers.uploads import LabelImage

# Images are shown back at most this wide, as JPEG, so a results page stays a few hundred KB.
DISPLAY_SIDE = 1600

FIELD_NAMES = {
    LabelField.BRAND: "Brand",
    LabelField.FANCIFUL: "Fanciful name",
    LabelField.CLASS_TYPE: "Class/type",
    LabelField.ALCOHOL: "Alcohol content",
    LabelField.NET_CONTENTS: "Net contents",
    LabelField.BOTTLER: "Bottler",
    LabelField.COUNTRY: "Country of origin",
    LabelField.HEALTH_WARNING: "Government warning",
}
STATUS_WORDS = {
    Status.PASS: "Matches",
    Status.REVIEW: "Needs review",
    Status.FAIL: "Does not match",
}
STATUS_GLYPHS = {
    Status.PASS: "\N{CHECK MARK}",
    Status.REVIEW: "!",
    Status.FAIL: "\N{MULTIPLICATION X}",
}
VERDICT_CLASSES = {
    Verdict.MATCHES: "matches",
    Verdict.NEEDS_REVIEW: "review",
    Verdict.DOES_NOT_MATCH: "fail",
}
DIFF_WORDS = {DiffOp.CHANGED: "Changed", DiffOp.MISSING: "Missing", DiffOp.EXTRA: "Added"}
NEXT_STEPS = {
    Verdict.MATCHES: "Everything checked agrees with the application. Look over the label as you "
    "normally would before deciding; this tool never approves a label.",
    Verdict.NEEDS_REVIEW: "Look at each item marked Needs review below and decide whether it is "
    "acceptable. The note under each one says why it was flagged.",
    Verdict.DOES_NOT_MATCH: "At least one item clearly differs from the application. The items "
    "marked Does not match say what is wrong.",
}


@dataclass(frozen=True)
class Outline:
    box: tuple[int, int, int, int]  # left, top, width, height, in the image's own pixels
    label: str
    css: str


@dataclass(frozen=True)
class ImageView:
    index: int
    data_url: str
    width: int
    height: int
    outlines: list[Outline] = field(default_factory=list)


@dataclass(frozen=True)
class DiffView:
    word: str  # "Changed", "Missing" or "Added"; empty for unchanged text
    expected: str
    found: str
    css: str


@dataclass(frozen=True)
class FieldView:
    name: str
    status: Status
    status_word: str
    status_css: str
    expected: str | None
    found: str | None
    notes: tuple[str, ...]
    cfr: str
    second_reading: str | None
    diff: list[DiffView]
    image: int | None
    box: str | None  # "left,top,width,height", for the zoom button
    sideways: bool


@dataclass(frozen=True)
class ResultsView:
    verdict: Verdict
    verdict_css: str
    summary: str  # "5 of 6 items match. 1 needs your review."
    next_step: str
    fields: list[FieldView]
    images: list[ImageView]
    offline_note: str | None
    injection_notes: list[str]
    other_notes: list[str]


def build_results(report: Report, images: Sequence[LabelImage]) -> ResultsView:
    views = [_image_view(index, image) for index, image in enumerate(images)]
    fields = []
    for result in report.results:
        fields.append(_field_view(result))
        if result.location is not None and result.location.image < len(views):
            views[result.location.image].outlines.append(
                Outline(
                    _box(result.location),
                    f"{STATUS_GLYPHS[result.status]} {FIELD_NAMES[result.field]}",
                    f"outline outline-{result.status.value}",
                )
            )
        for segment in result.diff:
            if segment.location is not None and segment.location.image < len(views):
                views[segment.location.image].outlines.append(
                    Outline(
                        _box(segment.location),
                        f"{DIFF_WORDS.get(segment.op, '')}: {segment.found}",
                        "outline outline-diff",
                    )
                )

    offline = Flag.OFFLINE in report.flags
    injection = [n for n in report.notes if "address an AI" in n or "addresses an AI" in n]
    others = [
        n for n in report.notes if n not in injection and not (offline and n is report.notes[0])
    ]
    return ResultsView(
        verdict=report.verdict,
        verdict_css=VERDICT_CLASSES[report.verdict],
        summary=_summary(report.results),
        next_step=NEXT_STEPS[report.verdict],
        fields=fields,
        images=views,
        offline_note=report.notes[0] if offline and report.notes else None,
        injection_notes=injection if Flag.POSSIBLE_INJECTION in report.flags else [],
        other_notes=others,
    )


def _summary(results: Sequence[FieldResult]) -> str:
    def count(status: Status) -> int:
        return sum(result.status is status for result in results)

    reviews, fails = count(Status.REVIEW), count(Status.FAIL)
    parts = [f"{count(Status.PASS)} of {len(results)} items match."]
    if reviews:
        parts.append(f"{reviews} {'needs' if reviews == 1 else 'need'} your review.")
    if fails:
        parts.append(f"{fails} {'does' if fails == 1 else 'do'} not match.")
    return " ".join(parts)


def _field_view(result: FieldResult) -> FieldView:
    location = result.location
    return FieldView(
        name=FIELD_NAMES[result.field],
        status=result.status,
        status_word=STATUS_WORDS[result.status],
        status_css=f"status-{result.status.value}",
        expected=result.expected,
        found=result.found,
        notes=result.notes,
        cfr=result.cfr,
        second_reading=result.second_reading,
        diff=[
            DiffView(
                DIFF_WORDS.get(segment.op, ""),
                segment.expected,
                segment.found,
                f"diff-{segment.op.value}",
            )
            for segment in result.diff
        ],
        image=location.image if location else None,
        box=",".join(str(n) for n in _box(location)) if location else None,
        sideways=bool(location and location.box.height > location.box.width * 1.5),
    )


def _box(location: Location) -> tuple[int, int, int, int]:
    box = location.box
    return box.left, box.top, box.width, box.height


def _image_view(index: int, label: LabelImage) -> ImageView:
    image = label.image
    shown = image.copy()
    shown.thumbnail((DISPLAY_SIDE, DISPLAY_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    shown.save(buffer, "JPEG", quality=85)
    data_url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    return ImageView(index=index, data_url=data_url, width=image.width, height=image.height)
