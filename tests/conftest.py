import os
import shutil
from collections.abc import Iterator

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
    """Skip OCR tests on a machine without Tesseract, but never in CI, where they must run."""
    if shutil.which("tesseract") or os.environ.get("CI") == "true":
        return
    skip = pytest.mark.skip(reason="Tesseract isn't installed (brew install tesseract)")
    for item in items:
        if "ocr" in item.keywords:
            item.add_marker(skip)
