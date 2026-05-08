from typing import Protocol

from ai_sdk import anthropic, generate_text, openai
from ai_sdk.types import (
    CoreAssistantMessage,
    CoreMessage,
    CoreSystemMessage,
    CoreUserMessage,
    TextPart,
)

from app.config import Settings
from app.conversations import Message
from app.enums import LLMProvider


class ChatProvider(Protocol):
    def reply(self, system: str, history: list[Message], user_text: str) -> str: ...


def _build_messages(
    system: str, history: list[Message], user_text: str
) -> list[CoreMessage]:
    messages: list[CoreMessage] = [CoreSystemMessage(content=system)]
    for msg in history:
        part = TextPart(text=msg["content"])
        if msg["role"] == "user":
            messages.append(CoreUserMessage(content=[part]))
        else:
            messages.append(CoreAssistantMessage(content=[part]))
    messages.append(CoreUserMessage(content=[TextPart(text=user_text)]))
    return messages


def _build_model(settings: Settings):
    if settings.llm_provider is LLMProvider.ANTHROPIC:
        assert settings.anthropic_api_key is not None  # validated in Settings
        return anthropic(
            settings.llm_model,
            api_key=settings.anthropic_api_key.get_secret_value(),
        )
    if settings.llm_provider is LLMProvider.OPENAI:
        assert settings.openai_api_key is not None  # validated in Settings
        return openai(
            settings.llm_model,
            api_key=settings.openai_api_key.get_secret_value(),
        )
    raise ValueError(f"unknown LLM provider: {settings.llm_provider}")


class AISDKChatProvider:
    """Provider-agnostic chat layer backed by ai-sdk-python.

    `generate_text` is synchronous; callers must already be off the request
    event loop (e.g. inside FastAPI BackgroundTasks) before invoking reply().
    """

    def __init__(self, settings: Settings) -> None:
        self._model = _build_model(settings)

    def reply(self, system: str, history: list[Message], user_text: str) -> str:
        messages = _build_messages(system, history, user_text)
        result = generate_text(model=self._model, messages=messages)
        return result.text
