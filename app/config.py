"""Runtime configuration, read from environment variables and an optional .env file."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExtractorMode(StrEnum):
    DUAL = "dual"  # vision LLM, cross-checked by OCR
    LLM = "llm"  # vision LLM only
    OCR = "ocr"  # offline OCR only (no outbound calls)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    extractor_mode: ExtractorMode = ExtractorMode.DUAL
    llm_api_key: SecretStr | None = None
    # Any OpenAI-compatible endpoint. Kimi is the default for cost; an agency would point this
    # at Azure OpenAI in its own tenant.
    llm_base_url: str = "https://api.moonshot.ai/v1"
    llm_model: str = Field(default="kimi-k2.6", min_length=1)
    # A call with no output by the first deadline is stuck in the provider's queue, and one
    # still running at the second is too slow; either way OCR reads the label instead.
    llm_first_token_timeout: float = Field(default=4.5, gt=0)
    llm_total_timeout: float = Field(default=10.0, gt=0)
    llm_image_max_side: int = Field(default=1100, ge=256, le=4096)
    # Kimi thinks by default, which takes over a minute per label. Azure OpenAI rejects the
    # parameter, so it is sent only when this is on.
    llm_disable_thinking: bool = True
    # Models that always think (Kimi's k3) refuse "thinking off" but take a reasoning effort.
    # When set, it is sent instead of the thinking switch.
    llm_reasoning_effort: Literal["low", "high", "max"] | None = None
    # Read the warning in its own call, alongside one for the other fields. Shorter replies
    # finish sooner: on real labels this cut the median from 7.8 s to 6.1 s.
    llm_split_warning: bool = True
    enable_docs: bool = False
    port: int = 8000
    forwarded_allow_ips: str = "127.0.0.1"

    @field_validator("llm_base_url")
    @classmethod
    def _https_only(cls, url: str) -> str:
        if not url.startswith("https://"):
            raise ValueError("must start with https://, so the API key is never sent in clear")
        return url

    @model_validator(mode="after")
    def _deadlines_in_order(self) -> Self:
        if self.llm_first_token_timeout > self.llm_total_timeout:
            raise ValueError("llm_first_token_timeout must not be later than llm_total_timeout")
        return self
