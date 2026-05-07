from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol, TypedDict

Role = Literal["user", "assistant"]


class Message(TypedDict):
    role: Role
    content: str


class ConversationStore(Protocol):
    async def get(self, thread_key: str) -> list[Message]: ...
    async def append(self, thread_key: str, role: Role, content: str) -> None: ...
    async def clear(self, thread_key: str) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryConversationStore:
    """Per-thread message history with idle-TTL eviction. Single-process only."""

    def __init__(
        self,
        ttl_hours: int = 24,
        max_messages: int = 40,
        now_fn: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._ttl = timedelta(hours=ttl_hours)
        self._max_messages = max_messages
        self._now = now_fn
        self._threads: dict[str, list[Message]] = {}
        self._last_seen: dict[str, datetime] = {}

    def _evict_if_expired(self, thread_key: str) -> None:
        last = self._last_seen.get(thread_key)
        if last is None:
            return
        if (self._now() - last) > self._ttl:
            self._threads.pop(thread_key, None)
            self._last_seen.pop(thread_key, None)

    async def get(self, thread_key: str) -> list[Message]:
        self._evict_if_expired(thread_key)
        return list(self._threads.get(thread_key, ()))

    async def append(self, thread_key: str, role: Role, content: str) -> None:
        self._evict_if_expired(thread_key)
        history = self._threads.setdefault(thread_key, [])
        history.append({"role": role, "content": content})
        overflow = len(history) - self._max_messages
        if overflow > 0:
            del history[:overflow]
        self._last_seen[thread_key] = self._now()

    async def clear(self, thread_key: str) -> None:
        self._threads.pop(thread_key, None)
        self._last_seen.pop(thread_key, None)
