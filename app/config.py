from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.constants import (
    DEFAULT_CONVERSATION_TTL_HOURS,
    DEFAULT_LINQ_BASE_URL,
    DEFAULT_LLM_MODEL,
)
from app.enums import LLMProvider


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

    @model_validator(mode="after")
    def _require_active_provider_key(self) -> "Settings":
        if self.llm_provider is LLMProvider.ANTHROPIC and self.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        if self.llm_provider is LLMProvider.OPENAI and self.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return self


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
