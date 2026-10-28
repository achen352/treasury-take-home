import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip OCR and browser tests on a machine without Tesseract or Chromium, but never in CI,
    where they must run."""
    if os.environ.get("CI") == "true":
        return
    browsers = Path(__file__).resolve().parent.parent / ".venv" / "ms-playwright"
    missing = {
        "ocr": None if shutil.which("tesseract") else "Tesseract isn't installed",
        "e2e": None if browsers.is_dir() else "Chromium isn't installed (see CLAUDE.md)",
    }
    for item in items:
        for marker, reason in missing.items():
            if reason and marker in item.keywords:
                item.add_marker(pytest.mark.skip(reason=reason))
