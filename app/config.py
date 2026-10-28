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
    # Any OpenAI-compatible endpoint. The demo uses OpenAI; an agency would point this at Azure
    # OpenAI in its own tenant. Kimi (https://api.moonshot.ai/v1) also works.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = Field(default="gpt-5.4-mini", min_length=1)
    # A call with no output by the first deadline is stuck in the provider's queue, and one
    # still running at the second is too slow; either way OCR reads the label instead. Both
    # are generous safety nets: a label normally takes 2 to 5 seconds.
    llm_first_token_timeout: float = Field(default=15.0, gt=0)
    llm_total_timeout: float = Field(default=25.0, gt=0)
    llm_image_max_side: int = Field(default=1100, ge=256, le=4096)
    # Kimi's k2 models think by default, which takes over a minute per label; this sends
    # Kimi's "thinking off" switch. OpenAI rejects the parameter, so it is off by default.
    llm_disable_thinking: bool = False
    # Reasoning models (OpenAI's GPT-5 family, Kimi's k3) take a reasoning effort; "low" keeps
    # the reasoning short. When set, it is sent instead of the thinking switch.
    llm_reasoning_effort: Literal["low", "high", "max"] | None = "low"
    # Read the warning in its own call, alongside one for the other fields. Shorter replies
    # finish sooner: on real labels this cut the median from 7.8 s to 6.1 s.
    llm_split_warning: bool = True
    # The most a single request may carry: a label's images and its form, together.
    max_request_bytes: int = Field(default=30 * 1024 * 1024, gt=0)
    enable_docs: bool = False
    port: int = 8000
    forwarded_allow_ips: str = "127.0.0.1"

    @field_validator("llm_reasoning_effort", mode="before")
    @classmethod
    def _empty_is_none(cls, effort: object) -> object:
        return None if effort == "" else effort

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
