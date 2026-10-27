"""Stand-in readers for tests: a scripted AI reader and a scripted OCR reader."""

import asyncio
import time
from collections.abc import Sequence

from app.domain.models import Box
from app.readers.extractor import ImageReading
from app.readers.ocr import OcrPage, OcrUnavailable, Word
from app.readers.uploads import LabelImage


def words_page(*lines: str, image: int = 0, angle: int = 0) -> OcrPage:
    """A page whose words sit on a grid: line n at y = 100 n, word m at x = 200 m."""
    words = [
        Word(
            text=text,
            confidence=95.0,
            box=Box(left=200 * m, top=100 * n, width=180, height=40),
            line=(angle, 1, 1, n),
        )
        for n, line_text in enumerate(lines)
        for m, text in enumerate(line_text.split())
    ]
    return OcrPage(image=image, words=tuple(words))


class FakeExtractor:
    """Answers each image in turn from a script; an exception in the script is raised."""

    def __init__(self, *script: ImageReading | Exception, delay: float = 0.0) -> None:
        self.script = script
        self.delay = delay
        self.images: list[LabelImage] = []

    async def read(self, image: LabelImage) -> ImageReading:
        index = len(self.images)
        self.images.append(image)
        await asyncio.sleep(self.delay)
        result = self.script[min(index, len(self.script) - 1)]
        if isinstance(result, Exception):
            raise result
        return result


class FakeOcr:
    """Reads scripted lines: `upright[i]` for image i, and `sideways[i]` on sideways passes."""

    def __init__(
        self,
        upright: Sequence[Sequence[str]],
        sideways: Sequence[Sequence[str]] = (),
        *,
        delay: float = 0.0,
        fails: bool = False,
    ) -> None:
        self.upright = upright
        self.sideways = sideways
        self.delay = delay
        self.fails = fails
        self.calls: list[tuple[int, tuple[int, ...]]] = []

    def __call__(self, image: LabelImage, index: int, angles: Sequence[int]) -> OcrPage:
        self.calls.append((index, tuple(angles)))
        time.sleep(self.delay)  # OCR runs in a worker thread, as Tesseract does
        if self.fails:
            raise OcrUnavailable("failed")
        words: list[Word] = []
        for angle in angles:
            lines = self.upright if angle == 0 else self.sideways
            if index < len(lines):
                words += words_page(*lines[index], image=index, angle=angle).words
        return OcrPage(image=index, words=tuple(words))
