"""Module-level constants used as defaults for `Settings` fields and as
named values elsewhere in the codebase. 
"""

DEFAULT_LINQ_BASE_URL = "https://api.linqapp.com"
DEFAULT_LLM_MODEL = "claude-haiku-4-5"
DEFAULT_CONVERSATION_TTL_HOURS = 24
DEFAULT_WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS = 300
DEFAULT_WEBHOOK_DEDUP_TTL_SECONDS = 1800

NON_TEXT_REFUSAL_TEXT = "i can only handle text right now. send a recipe question and i'll help."
