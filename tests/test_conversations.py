from datetime import datetime, timedelta, timezone

import pytest

from app.conversations import InMemoryConversationStore
from app.enums import Role

THREAD = "+15555550100"
FIXED_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock():
    return {"now": FIXED_NOW}


@pytest.fixture
def store(clock):
    return InMemoryConversationStore(
        ttl_hours=24,
        max_messages=4,
        now_fn=lambda: clock["now"],
    )


def test_empty_thread_returns_empty_history(store):
    assert store.get(THREAD) == []


def test_append_then_get(store):
    store.append(THREAD, Role.USER, "what can i make with chicken")
    store.append(THREAD, Role.ASSISTANT, "chicken piccata\nchicken tikka")
    history = store.get(THREAD)
    assert len(history) == 2
    assert history[0] == {"role": Role.USER, "content": "what can i make with chicken"}


def test_message_cap_drops_oldest(store):
    # max_messages=4 — 5th append evicts the first.
    for i in range(5):
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        store.append(THREAD, role, f"msg-{i}")
    history = store.get(THREAD)
    assert len(history) == 4
    assert history[0]["content"] == "msg-1", "oldest (msg-0) should have been dropped"


def test_ttl_eviction_after_idle_window(store, clock):
    store.append(THREAD, Role.USER, "hi")
    clock["now"] = FIXED_NOW + timedelta(hours=25)
    assert store.get(THREAD) == []


def test_writing_after_eviction_starts_fresh(store, clock):
    store.append(THREAD, Role.USER, "hi")
    clock["now"] = FIXED_NOW + timedelta(hours=25)
    assert store.get(THREAD) == []
    store.append(THREAD, Role.USER, "hi again")
    assert len(store.get(THREAD)) == 1


def test_explicit_clear(store):
    store.append(THREAD, Role.USER, "hi")
    store.clear(THREAD)
    assert store.get(THREAD) == []
