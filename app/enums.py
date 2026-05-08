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
    MEDIA = "media"
    LINK = "link"


class LinqEventType(StrEnum):
    """Linq webhook envelope `event_type` values v0 is aware of.

    Only MESSAGE_RECEIVED triggers the chef. All other events are 200-no-op.
    Unknown event types are also 200-no-op (Linq adds new ones; do not 4xx).
    """

    MESSAGE_RECEIVED = "message.received"


class LinqMessageDirection(StrEnum):
    """Direction of a Linq message inside the `message.received` payload."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class LinqWebhookHeader(StrEnum):
    """HTTP headers Linq sends on inbound webhook requests."""

    SIGNATURE = "x-webhook-signature"
    TIMESTAMP = "x-webhook-timestamp"
    EVENT = "x-webhook-event"
    SUBSCRIPTION_ID = "x-webhook-subscription-id"
