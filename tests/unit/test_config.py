"""Settings come from the environment / .env, keep secrets masked, and fail fast."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import ExtractorMode, Settings

FAKE_KEY = "sk-test-not-a-real-key-123456"


def make_settings(**overrides: object) -> Settings:
    # _env_file=None so a developer's real .env never leaks into tests.
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_loads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRACTOR_MODE", "ocr")
    monkeypatch.setenv("LLM_API_KEY", FAKE_KEY)

    settings = make_settings()

    assert settings.extractor_mode is ExtractorMode.OCR
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == FAKE_KEY


def test_loads_values_from_dotenv_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"EXTRACTOR_MODE=llm\nLLM_API_KEY={FAKE_KEY}\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]

    assert settings.extractor_mode is ExtractorMode.LLM
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == FAKE_KEY


def test_api_key_never_appears_when_settings_are_printed_or_serialized() -> None:
    settings = make_settings(llm_api_key=FAKE_KEY)

    for rendering in (repr(settings), str(settings), settings.model_dump_json()):
        assert FAKE_KEY not in rendering


def test_invalid_extractor_mode_fails_fast_with_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXTRACTOR_MODE", "banana")

    with pytest.raises(ValidationError) as excinfo:
        make_settings()

    assert "extractor_mode" in str(excinfo.value)


def test_secure_defaults() -> None:
    settings = make_settings()

    assert settings.extractor_mode is ExtractorMode.DUAL
    assert settings.enable_docs is False
    assert settings.llm_api_key is None
