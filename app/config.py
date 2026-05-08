from typing import Annotated

from pydantic import BeforeValidator, SecretStr, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.constants import (
    DEFAULT_CONVERSATION_TTL_HOURS,
    DEFAULT_LINQ_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_MAX_INBOUND_TEXT_CHARS,
    DEFAULT_WEBHOOK_DEDUP_TTL_SECONDS,
    DEFAULT_WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
)
from app.enums import LLMProvider


def _split_comma_list(v: object) -> frozenset[str]:
    """Parse a comma-separated env-var string into a frozenset of trimmed,
    non-empty values. Pass-through for already-iterable inputs (e.g. tests
    constructing Settings(...) directly with a frozenset/list)."""
    if not v:
        return frozenset()
    if isinstance(v, str):
        return frozenset(s.strip() for s in v.split(",") if s.strip())
    return frozenset(v)  # type: ignore[arg-type]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    linq_partner_token: SecretStr
    linq_webhook_secret: SecretStr
    linq_from_number: str
    linq_base_url: str = DEFAULT_LINQ_BASE_URL

    llm_provider: LLMProvider = LLMProvider.ANTHROPIC
    llm_model: str = DEFAULT_LLM_MODEL

    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    conversation_ttl_hours: int = DEFAULT_CONVERSATION_TTL_HOURS
    webhook_timestamp_tolerance_seconds: int = DEFAULT_WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS
    webhook_dedup_ttl_seconds: int = DEFAULT_WEBHOOK_DEDUP_TTL_SECONDS
    max_inbound_text_chars: int = DEFAULT_MAX_INBOUND_TEXT_CHARS

    # Empty set (default) means "allow any sender". Populate to restrict.
    # NoDecode skips pydantic-settings' JSON pre-decode for set/list types so
    # _split_comma_list sees the raw env string instead of a JSONDecodeError.
    linq_allowed_senders: Annotated[
        frozenset[str], NoDecode, BeforeValidator(_split_comma_list)
    ] = frozenset()

    @model_validator(mode="after")
    def _require_active_provider_key(self) -> "Settings":
        if self.llm_provider is LLMProvider.ANTHROPIC and self.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        if self.llm_provider is LLMProvider.OPENAI and self.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return self


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
