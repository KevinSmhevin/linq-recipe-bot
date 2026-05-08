"""Manual smoke test for InMemoryConversationStore."""

from datetime import datetime, timedelta, timezone

from app.conversations import InMemoryConversationStore


def main() -> None:
    fixed = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    clock = {"now": fixed}
    store = InMemoryConversationStore(
        ttl_hours=24,
        max_messages=4,
        now_fn=lambda: clock["now"],
    )

    thread = "+15555550100"

    # empty thread → empty history
    assert store.get(thread) == []

    # append turns
    store.append(thread, "user", "what can i make with chicken")
    store.append(thread, "assistant", "chicken piccata\nchicken tikka\nchicken adobo")
    history = store.get(thread)
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "what can i make with chicken"}

    # message cap (max_messages=4): 5th append drops the oldest
    store.append(thread, "user", "ingredients for chicken piccata")
    store.append(thread, "assistant", "chicken, lemon, capers, butter, flour")
    store.append(thread, "user", "and the instructions")
    history = store.get(thread)
    assert len(history) == 4, f"expected 4, got {len(history)}"
    assert history[0]["content"] == "chicken piccata\nchicken tikka\nchicken adobo"

    # TTL: jump 25h forward → thread evicted
    clock["now"] = fixed + timedelta(hours=25)
    history = store.get(thread)
    assert history == [], f"expected eviction, got {history}"

    # writing after eviction starts a fresh thread
    store.append(thread, "user", "hi again")
    assert len(store.get(thread)) == 1

    # explicit clear
    store.clear(thread)
    assert store.get(thread) == []

    print("conversations smoke OK")


if __name__ == "__main__":
    main()
