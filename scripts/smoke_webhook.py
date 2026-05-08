"""Smoke test for the /webhooks/linq route using FastAPI TestClient.

No network calls — chef + linq are stubbed. Verifies:
- happy path: signed message.received → 200 + chef/linq invoked + history updated
- missing/invalid signature → 401
- stale timestamp → 401
- malformed JSON → 400
- unknown event_type → 200 no-op
- replayed event_id → 200 no-op (chef NOT re-invoked)
- group chat → 200 no-op
- non-text-only parts → 200 + polite refusal sent via linq, chef NOT invoked
"""

import hashlib
import hmac
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.constants import NON_TEXT_REFUSAL_TEXT
from app.conversations import InMemoryConversationStore
from app.dedup import InMemoryEventDedup
from app.enums import LLMProvider, LinqWebhookHeader, Role
from app.routes.webhook import WEBHOOK_PATH, router

WEBHOOK_SECRET = "test-webhook-secret"
SENDER = "+15555550123"
BOT_NUMBER = "+16462617385"


class StubChef:
    def __init__(self, reply_text: str = "fixed-reply") -> None:
        self.calls: list[tuple[list, str]] = []
        self._reply = reply_text

    def reply(self, history, user_text):
        self.calls.append((list(history), user_text))
        return self._reply


class StubLinq:
    def __init__(self) -> None:
        self.sends: list[tuple[str, str]] = []

    def send_text(self, to: str, text: str) -> None:
        self.sends.append((to, text))


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        linq_partner_token=SecretStr("partner-token"),
        linq_webhook_secret=SecretStr(WEBHOOK_SECRET),
        linq_from_number=BOT_NUMBER,
        llm_provider=LLMProvider.ANTHROPIC,
        anthropic_api_key=SecretStr("test"),
    )


def _make_app(chef: StubChef, linq: StubLinq):
    app = FastAPI()
    app.include_router(router)
    app.state.settings = _settings()
    app.state.chef = chef
    app.state.linq = linq
    app.state.conversation_store = InMemoryConversationStore(ttl_hours=24)
    app.state.event_dedup = InMemoryEventDedup(ttl_seconds=1800)
    return app


def _sign(timestamp: str, body: bytes) -> str:
    payload = timestamp.encode() + b"." + body
    return hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()


def _post(client: TestClient, body: dict, *, timestamp: str | None = None,
          signature: str | None = None, event: str = "message.received"):
    raw = json.dumps(body).encode()
    ts = timestamp if timestamp is not None else str(int(time.time()))
    sig = signature if signature is not None else _sign(ts, raw)
    return client.post(
        WEBHOOK_PATH,
        content=raw,
        headers={
            LinqWebhookHeader.SIGNATURE: sig,
            LinqWebhookHeader.TIMESTAMP: ts,
            LinqWebhookHeader.EVENT: event,
            "Content-Type": "application/json",
        },
    )


def _envelope(event_type: str, event_id: str, data: dict) -> dict:
    return {
        "api_version": "v3",
        "webhook_version": "2026-02-03",
        "event_type": event_type,
        "event_id": event_id,
        "created_at": "2026-05-07T12:00:00Z",
        "trace_id": "trace-1",
        "partner_id": "partner-1",
        "data": data,
    }


def _message_received_data(
    *, direction: str = "inbound", is_group: bool = False, parts: list | None = None
) -> dict:
    return {
        "id": "msg-1",
        "direction": direction,
        "sender_handle": {"handle": SENDER, "service": "iMessage"},
        "chat": {"id": "chat-1", "is_group": is_group},
        "parts": parts if parts is not None else [{"type": "text", "value": "hi chef"}],
        "sent_at": "2026-05-07T12:00:00Z",
    }


# ---------- tests ----------

def test_happy_path():
    chef = StubChef("chicken piccata\nchicken adobo")
    linq = StubLinq()
    app = _make_app(chef, linq)
    body = _envelope("message.received", "evt-1", _message_received_data())

    with TestClient(app) as client:
        r = _post(client, body)

    assert r.status_code == 200, r.text
    assert len(chef.calls) == 1
    history_seen, user_text = chef.calls[0]
    assert history_seen == []
    assert user_text == "hi chef"
    assert linq.sends == [(SENDER, "chicken piccata\nchicken adobo")]
    stored = app.state.conversation_store.get(SENDER)
    assert stored == [
        {"role": Role.USER, "content": "hi chef"},
        {"role": Role.ASSISTANT, "content": "chicken piccata\nchicken adobo"},
    ]
    print("happy path OK")


def test_missing_signature_401():
    app = _make_app(StubChef(), StubLinq())
    with TestClient(app) as client:
        r = client.post(WEBHOOK_PATH, content=b"{}", headers={"Content-Type": "application/json"})
    assert r.status_code == 401
    print("missing signature → 401 OK")


def test_bad_signature_401():
    chef = StubChef()
    linq = StubLinq()
    app = _make_app(chef, linq)
    body = _envelope("message.received", "evt-bad-sig", _message_received_data())
    with TestClient(app) as client:
        r = _post(client, body, signature="0" * 64)
    assert r.status_code == 401
    assert chef.calls == [] and linq.sends == []
    print("bad signature → 401 OK")


def test_stale_timestamp_401():
    chef = StubChef()
    linq = StubLinq()
    app = _make_app(chef, linq)
    body = _envelope("message.received", "evt-stale", _message_received_data())
    stale_ts = str(int(time.time()) - 3600)  # 1h old, well past 5-min tolerance
    with TestClient(app) as client:
        r = _post(client, body, timestamp=stale_ts)
    assert r.status_code == 401
    assert chef.calls == [] and linq.sends == []
    print("stale timestamp → 401 OK")


def test_malformed_json_400():
    app = _make_app(StubChef(), StubLinq())
    raw = b"{not json"
    ts = str(int(time.time()))
    sig = _sign(ts, raw)
    with TestClient(app) as client:
        r = client.post(
            WEBHOOK_PATH,
            content=raw,
            headers={
                LinqWebhookHeader.SIGNATURE: sig,
                LinqWebhookHeader.TIMESTAMP: ts,
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 400
    print("malformed JSON → 400 OK")


def test_unknown_event_type_200_noop():
    chef = StubChef()
    linq = StubLinq()
    app = _make_app(chef, linq)
    body = _envelope("message.delivered", "evt-2", _message_received_data())
    with TestClient(app) as client:
        r = _post(client, body, event="message.delivered")
    assert r.status_code == 200
    assert chef.calls == [] and linq.sends == []
    print("unknown event_type → 200 no-op OK")


def test_replay_dedup():
    chef = StubChef()
    linq = StubLinq()
    app = _make_app(chef, linq)
    body = _envelope("message.received", "evt-replay", _message_received_data())
    with TestClient(app) as client:
        r1 = _post(client, body)
        r2 = _post(client, body)  # same event_id
    assert r1.status_code == 200 and r2.status_code == 200
    assert len(chef.calls) == 1, f"expected 1 chef call, got {len(chef.calls)}"
    assert len(linq.sends) == 1
    print("replay dedup OK")


def test_group_chat_ignored():
    chef = StubChef()
    linq = StubLinq()
    app = _make_app(chef, linq)
    body = _envelope("message.received", "evt-group", _message_received_data(is_group=True))
    with TestClient(app) as client:
        r = _post(client, body)
    assert r.status_code == 200
    assert chef.calls == [] and linq.sends == []
    print("group chat ignored OK")


def test_non_text_part_refusal():
    chef = StubChef()
    linq = StubLinq()
    app = _make_app(chef, linq)
    body = _envelope(
        "message.received",
        "evt-image",
        _message_received_data(parts=[{"type": "media", "id": "m1", "url": "https://x"}]),
    )
    with TestClient(app) as client:
        r = _post(client, body)
    assert r.status_code == 200
    assert chef.calls == [], "chef should not be invoked for non-text"
    assert linq.sends == [(SENDER, NON_TEXT_REFUSAL_TEXT)]
    print("non-text refusal OK")


def test_outbound_direction_ignored():
    chef = StubChef()
    linq = StubLinq()
    app = _make_app(chef, linq)
    body = _envelope("message.received", "evt-outbound", _message_received_data(direction="outbound"))
    with TestClient(app) as client:
        r = _post(client, body)
    assert r.status_code == 200
    assert chef.calls == [] and linq.sends == []
    print("outbound direction ignored OK")


def main():
    test_happy_path()
    test_missing_signature_401()
    test_bad_signature_401()
    test_stale_timestamp_401()
    test_malformed_json_400()
    test_unknown_event_type_200_noop()
    test_replay_dedup()
    test_group_chat_ignored()
    test_non_text_part_refusal()
    test_outbound_direction_ignored()
    print("\nwebhook smoke OK")


if __name__ == "__main__":
    main()
