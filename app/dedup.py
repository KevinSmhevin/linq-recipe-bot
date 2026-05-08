from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol


class EventDedup(Protocol):
    def is_duplicate(self, event_id: str) -> bool: ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryEventDedup:
    """Tracks recently seen webhook event IDs so at-least-once duplicates are
    no-ops. Single-process only — swap to Redis for multi-instance deploys."""

    def __init__(
        self,
        ttl_seconds: int,
        now_fn: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._now = now_fn
        self._seen: dict[str, datetime] = {}

    def _evict_expired(self) -> None:
        cutoff = self._now() - self._ttl
        stale = [k for k, t in self._seen.items() if t < cutoff]
        for k in stale:
            del self._seen[k]

    def is_duplicate(self, event_id: str) -> bool:
        self._evict_expired()
        if event_id in self._seen:
            return True
        self._seen[event_id] = self._now()
        return False
