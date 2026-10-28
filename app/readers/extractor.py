"""What every label reader provides, and how it says it couldn't read a label."""

from dataclasses import dataclass
from typing import Protocol

from app.domain.models import ExtractedLabel
from app.readers.uploads import LabelImage


@dataclass(frozen=True)
class ImageReading:
    """What a reader transcribed from one image: the label's fields, every prominent name and
    every name-and-address statement it prints (code picks the brand and bottler from these),
    and any text it saw addressing an AI."""

    label: ExtractedLabel
    instructions_seen: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    statements: tuple[str, ...] = ()


class ReaderUnavailable(Exception):
    """The reader produced no reading. `reason` is a fixed code, safe to log."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Extractor(Protocol):
    """Reads one label image. It is never given the application, only the image."""

    async def read(self, image: LabelImage) -> ImageReading: ...
