"""The OCR reader: Tesseract, run directly, and finding label fields in what it reads.

Tesseract is the second, independent reader. It can't be talked into anything, and it runs on
the server, so it reads labels alone when the AI reader is unreachable. It returns every word
with its box, so each finding can be outlined on the label image.

The image goes to Tesseract on stdin and its TSV comes back on stdout, so nothing is written to
disk, and its environment carries no secrets.
"""

import io
import os
import shutil
import subprocess  # nosec B404 - Tesseract runs with fixed arguments and no shell
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from PIL import Image
from rapidfuzz import fuzz

from app.domain.crosscheck import warning_window
from app.domain.models import (
    MAX_WARNING,
    ApplicationData,
    Box,
    DiffOp,
    ExtractedLabel,
    LabelField,
    Location,
    Report,
)
from app.domain.normalize import normalize_text
from app.domain.rules.health_warning import join_tokens, tokenize
from app.readers.uploads import LabelImage

# Automatic page segmentation keeps a paragraph's lines in reading order, which the warning
# needs; the sparse-text mode reads labels' scattered words but interleaves columns.
PAGE_MODE = "3"
# Seconds per pass. Render's 0.1 CPU is about ten times slower than a laptop.
PASS_TIMEOUT = 15.0
SIDEWAYS = (90, 270)
# How closely (0-100) words must match. Reading a field offline can be loose, because the checks
# then judge what was found; placing an outline must be stricter, since a wrong box misleads.
FIND_SIMILARITY = 60
LOCATE_SIMILARITY = 80
HEADER_SIMILARITY = 85
_HEADER = "governmentwarning"


class OcrUnavailable(Exception):
    """Tesseract produced nothing. `reason` is a fixed code, safe to log."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Word:
    text: str
    confidence: float
    box: Box  # in the upright image's pixels
    line: tuple[int, int, int, int]  # (pass, block, paragraph, line), to rebuild the lines


@dataclass(frozen=True)
class OcrPage:
    """Everything OCR read on one of the label's images, upright and sideways passes together."""

    image: int
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        lines: list[list[str]] = []
        current: tuple[int, int, int, int] | None = None
        for word in self.words:
            if word.line != current:
                lines.append([])
                current = word.line
            lines[-1].append(word.text)
        return "\n".join(" ".join(line) for line in lines)


def read_page(label: LabelImage, index: int, *, angles: Sequence[int] = (0,)) -> OcrPage:
    """Read one image, turned by each angle in turn, with every box in upright coordinates."""
    words: list[Word] = []
    for pass_index, angle in enumerate(angles):
        image = label.image if angle == 0 else label.image.rotate(angle, expand=True)
        for word in run_tesseract(image, pass_index=pass_index):
            box = rotate_box_back(word.box, angle, label.image.size)
            words.append(replace(word, box=box))
    return OcrPage(image=index, words=tuple(words))


def run_tesseract(
    image: Image.Image, *, timeout: float = PASS_TIMEOUT, pass_index: int = 0
) -> list[Word]:
    found = shutil.which("tesseract")
    if found is None:
        raise OcrUnavailable("missing")
    buffer = io.BytesIO()
    image.save(
        buffer, "PNG", compress_level=1
    )  # Tesseract reads PNG from stdin far faster than PPM
    env = {"OMP_THREAD_LIMIT": "1", "PATH": os.environ.get("PATH", "")}
    if "TESSDATA_PREFIX" in os.environ:
        env["TESSDATA_PREFIX"] = os.environ["TESSDATA_PREFIX"]
    try:
        # Fixed arguments, no shell, and the image on stdin.
        done = subprocess.run(  # noqa: S603  # nosec B603
            [os.path.abspath(found), "stdin", "stdout", "--psm", PAGE_MODE, "-l", "eng", "tsv"],
            input=buffer.getvalue(),
            capture_output=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise OcrUnavailable("timeout") from None
    except OSError:
        raise OcrUnavailable("failed") from None
    if done.returncode != 0:
        raise OcrUnavailable("failed")
    return parse_tsv(done.stdout.decode("utf-8", errors="replace"), pass_index)


def parse_tsv(output: str, pass_index: int = 0) -> list[Word]:
    """Tesseract's TSV: one row per element; level 5 rows are words."""
    words = []
    for row in output.splitlines()[1:]:
        cells = row.split("\t")
        if len(cells) != 12 or cells[0] != "5":
            continue
        text = cells[11].strip()
        try:
            block, paragraph, line = int(cells[2]), int(cells[3]), int(cells[4])
            left, top, width, height = (int(cell) for cell in cells[6:10])
            confidence = float(cells[10])
            box = Box(left=left, top=top, width=width, height=height)
        except ValueError:
            continue
        if text and confidence >= 0:
            words.append(Word(text, confidence, box, (pass_index, block, paragraph, line)))
    return words


def rotate_box_back(box: Box, angle: int, size: tuple[int, int]) -> Box:
    """Map a box found on the image turned `angle` degrees counterclockwise back to the
    upright image, whose size is `size`."""
    width, height = size
    if angle == 0:
        return box
    if angle == 90:
        left, top = width - (box.top + box.height), box.left
    elif angle == 270:
        left, top = box.top, height - (box.left + box.width)
    else:
        raise ValueError(f"unsupported angle: {angle}")
    return Box(left=max(0, left), top=max(0, top), width=box.height, height=box.width)


def has_warning_header(pages: Sequence[OcrPage]) -> bool:
    """Whether "GOVERNMENT WARNING" appears, allowing for small misreads and lost spaces."""
    return any(
        fuzz.partial_ratio(_HEADER, _squashed(page.text)) >= HEADER_SIMILARITY for page in pages
    )


def reading_from_ocr(pages: Sequence[OcrPage], application: ApplicationData) -> ExtractedLabel:
    """A reading made from OCR alone, for when the AI reader is unavailable.

    Each field is the stretch of OCR text that best matches the application's value. The checks
    then judge it as usual, and the offline policy keeps the label from matching, so a value
    found this way can never pass a label on its own. OCR can't judge bold type.
    """

    def find(value: str | None) -> str | None:
        if not value:
            return None
        best: tuple[float, str] | None = None
        for page in pages:
            window = _best_window(value, page.words)
            if window is not None and (best is None or window[2] > best[0]):
                text = " ".join(word.text for word in page.words[window[0] : window[1]])
                best = (window[2], text)
        return best[1] if best is not None and best[0] >= FIND_SIMILARITY else None

    warning = None
    for page in pages:
        if has_warning_header([page]):
            window = warning_window(tokenize(page.text))
            if window:
                warning = join_tokens(window)[:MAX_WARNING]
                break

    return ExtractedLabel(
        brand_name=find(application.brand_name),
        fanciful_name=find(application.fanciful_name),
        class_type=find(application.class_type),
        alcohol_content=find(application.alcohol_content),
        net_contents=find(application.net_contents),
        bottler=find(application.bottler),
        country_of_origin=find(application.country_of_origin) if application.imported else None,
        health_warning=warning,
    )


def locate(
    text: str | None, pages: Sequence[OcrPage], *, within: Location | None = None
) -> Location | None:
    """Where `text` is on the label: the box around the words that match it best, or None."""
    if not text or not normalize_text(text):
        return None
    best: tuple[float, int, Sequence[Word]] | None = None
    for page in pages:
        if within is not None and page.image != within.image:
            continue
        words = (
            page.words
            if within is None
            else tuple(word for word in page.words if _centre_inside(word.box, within.box))
        )
        window = _best_window(text, words)
        if (
            window is not None
            and window[2] >= LOCATE_SIMILARITY
            and (best is None or window[2] > best[0])
        ):
            best = (window[2], page.image, words[window[0] : window[1]])
    if best is None:
        return None
    return Location(image=best[1], box=_union(word.box for word in best[2]))


def attach_locations(report: Report, pages: Sequence[OcrPage]) -> Report:
    """Give each result, and each differing word of the warning, the place OCR found it."""
    results = []
    for result in report.results:
        location = locate(result.found, pages)
        diff = result.diff
        if result.field is LabelField.HEALTH_WARNING and location is not None:
            diff = tuple(
                segment.model_copy(
                    update={"location": locate(segment.found, pages, within=location)}
                )
                if segment.op in (DiffOp.CHANGED, DiffOp.EXTRA) and segment.found
                else segment
                for segment in diff
            )
        results.append(result.model_copy(update={"location": location, "diff": diff}))
    return report.model_copy(update={"results": tuple(results)})


def _best_window(target: str, words: Sequence[Word]) -> tuple[int, int, float] | None:
    """The run of words most like `target`: (start, end, similarity 0-100)."""
    key = normalize_text(target)
    if not key or not words:
        return None
    length = len(target.split())
    best: tuple[int, int, float] | None = None
    for size in range(max(1, length - 2), length + 3):
        for start in range(len(words) - size + 1):
            candidate = normalize_text(" ".join(word.text for word in words[start : start + size]))
            if not candidate:
                continue
            score = fuzz.ratio(key, candidate)
            if best is None or score > best[2]:
                best = (start, start + size, score)
    return best


def _union(boxes: Iterable[Box]) -> Box:
    items = list(boxes)
    left = min(box.left for box in items)
    top = min(box.top for box in items)
    right = max(box.left + box.width for box in items)
    bottom = max(box.top + box.height for box in items)
    return Box(left=left, top=top, width=right - left, height=bottom - top)


def _centre_inside(box: Box, region: Box) -> bool:
    x, y = box.left + box.width / 2, box.top + box.height / 2
    return region.left <= x <= region.left + region.width and (
        region.top <= y <= region.top + region.height
    )


def _squashed(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())
