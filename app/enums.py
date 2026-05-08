from enum import StrEnum


class LLMProvider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class Role(StrEnum):
    """Conversation message role. Mirrors the user/assistant split in chat APIs."""

    USER = "user"
    ASSISTANT = "assistant"


class LinqMessagePartType(StrEnum):
    """Discriminator for the `type` field inside Linq message parts."""

    TEXT = "text"
