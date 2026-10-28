"""The dual reader: the AI and OCR read every image of a label at the same time.

The AI reads each image, and so does OCR: upright first, then sideways if the warning or a
field the AI read can't be found. Code merges the AI's readings, OCR confirms them, and the
checks decide. If the AI reader fails on any image, or runs out of time, OCR reads the label
alone, and the label can't come out as "Matches". OCR also gives each finding its place on the
label, for the outlines on the results page.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence

from app.config import ExtractorMode, Settings
from app.domain.candidates import choose_names
from app.domain.crosscheck import NOT_FOUND, WARNING_DIFFERS
from app.domain.merge import merge_readings
from app.domain.models import (
    ApplicationData,
    ExtractedLabel,
    Reader,
    Report,
    Status,
    Verdict,
)
from app.domain.verifier import verify
from app.readers.extractor import Extractor, ImageReading, ReaderUnavailable
from app.readers.ocr import (
    SIDEWAYS,
    OcrPage,
    OcrUnavailable,
    attach_locations,
    has_warning_header,
    read_page,
    reading_from_ocr,
)
from app.readers.uploads import LabelImage

logger = logging.getLogger(__name__)

OcrReader = Callable[[LabelImage, int, Sequence[int]], OcrPage]

# The AI reader keeps its own deadlines; this margin past them is only a backstop.
AI_BACKSTOP = 0.5

OFFLINE_NOTE = (
    "The AI reader didn't answer in time, so this label was read by OCR alone. OCR can misread "
    "labels and can't judge bold type, so a person should check it."
)
OCR_MODE_NOTE = (
    "This server reads labels by OCR alone, without the AI reader. OCR can misread labels and "
    "can't judge bold type, so a person should check it."
)
UNREAD_NOTE = (
    "The AI reader didn't answer and OCR is switched off on this server, so the label couldn't "
    "be read. A person should check it."
)
UNREAD = "This field couldn't be read."


def _tesseract(image: LabelImage, index: int, angles: Sequence[int]) -> OcrPage:
    return read_page(image, index, angles=angles)


async def check_label(
    images: Sequence[LabelImage],
    application: ApplicationData,
    settings: Settings,
    *,
    extractor: Extractor | None,
    ocr_reader: OcrReader = _tesseract,
) -> Report:
    """Read a label's images with both readers and check the result against the application."""
    mode = settings.extractor_mode
    ai: asyncio.Task[list[ImageReading] | None] | None = None
    if mode is not ExtractorMode.OCR and extractor is not None:
        ai = asyncio.create_task(_read_with_ai(extractor, images, settings))
    ocr = None if mode is ExtractorMode.LLM else _Ocr(images, ocr_reader)
    try:
        if ocr is not None:
            await ocr.read_upright()
        readings = await ai if ai is not None else None
    except BaseException:
        if ai is not None:
            ai.cancel()
        raise

    notes: tuple[str, ...] = ()
    if readings is not None:
        merged = merge_readings([reading.label for reading in readings])
        seen = tuple(dict.fromkeys(text for r in readings for text in r.instructions_seen))
        chosen = choose_names(
            merged.reading,
            names=tuple(dict.fromkeys(name for r in readings for name in r.names)),
            statements=tuple(dict.fromkeys(text for r in readings for text in r.statements)),
            application=application,
        )

        def run_checks() -> Report:
            return verify(
                application,
                chosen,
                read_by=Reader.AI,
                ocr_text=ocr.text if ocr is not None else None,
                conflicts=merged.conflicts,
                instructions_seen=seen,
            )

        report = run_checks()
        if ocr is not None and _unconfirmed(report) and await ocr.read_sideways():
            report = run_checks()
    elif ocr is not None:
        report = verify(
            application,
            reading_from_ocr(ocr.pages, application),
            read_by=Reader.OCR,
            ocr_text=ocr.text,
        )
        notes = (OCR_MODE_NOTE if mode is ExtractorMode.OCR else OFFLINE_NOTE,)
    else:
        report = _unread(application)
        notes = (UNREAD_NOTE,)

    if ocr is not None and ocr.pages:
        report = attach_locations(report, ocr.pages)
    return report.model_copy(update={"notes": (*notes, *report.notes)})


class _Ocr:
    """OCR of every image: upright, and sideways when something is missing."""

    def __init__(self, images: Sequence[LabelImage], reader: OcrReader) -> None:
        self._images = images
        self._reader = reader
        self.pages: list[OcrPage] = []
        self.failed = False
        self._sideways_done = False

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages)

    async def read_upright(self) -> None:
        try:
            self.pages = await self._read_all((0,))
        except OcrUnavailable as failure:
            logger.warning("OCR unavailable: %s", failure.reason)
            self.failed = True
            return
        if not has_warning_header(self.pages):  # often printed sideways on real labels
            await self.read_sideways()

    async def read_sideways(self) -> bool:
        """Add the sideways passes, once. Whether they were added."""
        if self.failed or self._sideways_done:
            return False
        self._sideways_done = True
        try:
            sideways = await self._read_all(SIDEWAYS)
        except OcrUnavailable as failure:
            logger.warning("OCR unavailable for the sideways passes: %s", failure.reason)
            return False
        self.pages = [
            OcrPage(image=page.image, words=page.words + extra.words)
            for page, extra in zip(self.pages, sideways, strict=True)
        ]
        return True

    async def _read_all(self, angles: Sequence[int]) -> list[OcrPage]:
        return list(
            await asyncio.gather(
                *(
                    asyncio.to_thread(self._reader, image, index, angles)
                    for index, image in enumerate(self._images)
                )
            )
        )


async def _read_with_ai(
    extractor: Extractor, images: Sequence[LabelImage], settings: Settings
) -> list[ImageReading] | None:
    """The AI's reading of every image, or None if it failed on any of them."""
    try:
        async with asyncio.timeout(settings.llm_total_timeout + AI_BACKSTOP):
            results = await asyncio.gather(
                *(extractor.read(image) for image in images), return_exceptions=True
            )
    except TimeoutError:
        logger.warning("AI reader unavailable: past the backstop deadline")
        return None
    readings = []
    for result in results:
        if isinstance(result, ReaderUnavailable):
            return None  # the reader has logged why
        if isinstance(result, BaseException):
            logger.error("AI reader failed unexpectedly: %s", type(result).__name__)
            return None
        readings.append(result)
    return readings


def _unconfirmed(report: Report) -> bool:
    """Whether OCR failed to find something the AI read."""
    return any(
        NOT_FOUND in result.notes or WARNING_DIFFERS in result.notes for result in report.results
    )


def _unread(application: ApplicationData) -> Report:
    """Every field to a person: nothing could read the label."""
    results = tuple(
        result.model_copy(update={"status": Status.REVIEW, "notes": (UNREAD,)})
        for result in verify(application, ExtractedLabel()).results
    )
    return Report(verdict=Verdict.NEEDS_REVIEW, results=results)
