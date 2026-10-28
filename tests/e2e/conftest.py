"""A live server for browser tests, with scripted readers so results are always the same."""

import os
import socket
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
import uvicorn

from app.config import Settings
from app.domain.constants import HEALTH_WARNING
from app.domain.models import Box
from app.main import create_app
from app.readers.extractor import ImageReading
from app.readers.ocr import OcrPage, Word
from app.readers.uploads import LabelImage
from tests.fakes import FakeExtractor, words_page
from tests.samples import OLD_TOM_LABEL_LINES, OLD_TOM_READING

ROOT = Path(__file__).resolve().parents[2]
if (ROOT / ".venv" / "ms-playwright").is_dir():
    # Browsers live inside the project, not in the user's cache (see CLAUDE.md).
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".venv" / "ms-playwright"))


def sideways_warning_ocr(image: LabelImage, index: int, angles: Sequence[int]) -> OcrPage:
    """OLD TOM's lines across the top, and its warning as a tall column down the right side."""
    page = words_page(*OLD_TOM_LABEL_LINES, image=index)
    column = [
        Word(
            text=word,
            confidence=95.0,
            box=Box(left=1450, top=60 + 40 * n, width=60, height=38),
            line=(90, 1, 1, n),
        )
        for n, word in enumerate(HEALTH_WARNING.split())
    ]
    return OcrPage(image=index, words=(*page.words, *column) if 0 in angles else tuple(column))


@pytest.fixture(scope="session")
def live_server() -> Iterator[str]:
    settings = Settings(_env_file=None, rate_limit_per_minute=1000, rate_limit_per_day=10_000)  # type: ignore[call-arg]
    app = create_app(
        settings,
        extractor=FakeExtractor(ImageReading(OLD_TOM_READING)),
        ocr_reader=sideways_warning_ocr,
    )
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
