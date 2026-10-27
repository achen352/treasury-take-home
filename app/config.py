"""Runtime configuration, read from environment variables and an optional .env file."""

from enum import StrEnum

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExtractorMode(StrEnum):
    DUAL = "dual"  # vision LLM, cross-checked by OCR
    LLM = "llm"  # vision LLM only
    OCR = "ocr"  # offline OCR only (no outbound calls)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    extractor_mode: ExtractorMode = ExtractorMode.DUAL
    llm_api_key: SecretStr | None = None
    enable_docs: bool = False
    port: int = 8000
    forwarded_allow_ips: str = "127.0.0.1"
