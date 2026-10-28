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


def test_ai_reader_defaults_suit_kimi() -> None:
    settings = make_settings()

    assert settings.llm_base_url == "https://api.moonshot.ai/v1"
    assert settings.llm_model == "kimi-k2.6"
    assert settings.llm_first_token_timeout == 4.5
    assert settings.llm_total_timeout == 10
    assert settings.llm_image_max_side == 1100
    assert settings.llm_disable_thinking is True
    assert settings.llm_split_warning is True


def test_ai_reader_settings_load_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://example.openai.azure.com/openai/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-label-reader")
    monkeypatch.setenv("LLM_FIRST_TOKEN_TIMEOUT", "3")
    monkeypatch.setenv("LLM_TOTAL_TIMEOUT", "6")
    monkeypatch.setenv("LLM_IMAGE_MAX_SIDE", "1400")
    monkeypatch.setenv("LLM_DISABLE_THINKING", "false")

    settings = make_settings()

    assert settings.llm_base_url == "https://example.openai.azure.com/openai/v1"
    assert settings.llm_model == "gpt-label-reader"
    assert (settings.llm_first_token_timeout, settings.llm_total_timeout) == (3, 6)
    assert settings.llm_image_max_side == 1400
    assert settings.llm_disable_thinking is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"llm_base_url": "http://api.moonshot.ai/v1"},  # the key would travel unencrypted
        {"llm_base_url": "ftp://api.moonshot.ai/v1"},
        {"llm_first_token_timeout": 0},
        {"llm_total_timeout": -1},
        {"llm_first_token_timeout": 11, "llm_total_timeout": 10},
        {"llm_image_max_side": 100},
        {"llm_image_max_side": 10_000},
        {"llm_model": ""},
    ],
    ids=[
        "plain-http",
        "not-http",
        "zero-first-token",
        "negative-total",
        "first-token-after-total",
        "image-too-small",
        "image-too-large",
        "empty-model",
    ],
)
def test_bad_ai_reader_settings_fail_fast(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)
