"""Manual live smoke for ChefAssistant.

Skips with a clear message if no provider key is configured. When the active
provider's key is set in .env, runs one real round-trip and prints the reply.
"""

import sys

from app.chef import ChefAssistant
from app.config import get_settings
from app.enums import LLMProvider
from app.llm import AISDKChatProvider


def main() -> int:
    try:
        settings = get_settings()
    except Exception as exc:
        print(f"settings load failed: {exc}")
        return 0  # not a failure of the chef itself

    provider_label = settings.llm_provider.value
    print(f"provider={provider_label} model={settings.llm_model}")

    has_key = (
        settings.llm_provider is LLMProvider.ANTHROPIC and settings.anthropic_api_key
    ) or (settings.llm_provider is LLMProvider.OPENAI and settings.openai_api_key)
    if not has_key:
        print("skip: no provider key configured")
        return 0

    chef = ChefAssistant(AISDKChatProvider(settings))

    history = []
    user_text = "what can i make with chicken, lemon, and capers"
    print(f"\n> user: {user_text}")
    reply = chef.reply(history, user_text)
    print("\n< chef:")
    print(reply)

    if not reply.strip():
        print("\nFAIL: empty reply")
        return 1
    if any(line.lstrip().split(".", 1)[0].isdigit() for line in reply.splitlines()):
        print("\nWARN: reply contains numbered lines (system prompt forbids this)")

    print("\nchef smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
