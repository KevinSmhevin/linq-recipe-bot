import hashlib
import hmac
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.constants import CHEF_ERROR_FALLBACK_TEXT, NON_TEXT_REFUSAL_TEXT
from app.conversations import InMemoryConversationStore
from app.dedup import InMemoryEventDedup
from app.enums import LLMProvider, LinqWebhookHeader, Role
from app.routes.webhook import WEBHOOK_PATH, router

WEBHOOK_SECRET = "test-webhook-secret"
SENDER = "+15555550123"
BOT_NUMBER = "+16462617385"


class StubChef:
    def __init__(self, reply_text: str = "fixed-reply", *, raise_on_call: bool = False) -> None:
        self.calls: list[tuple[list, str]] = []
        self._reply = reply_text
        self._raise = raise_on_call

    def reply(self, history, user_text):
        self.calls.append((list(history), user_text))
        if self._raise:
            raise RuntimeError("chef boom")
        return self._reply


class StubLinq:
    def __init__(self) -> None:
        self.sends: list[tuple[str, str]] = []

    def send_text(self, to: str, text: str) -> None:
        self.sends.append((to, text))


def _settings(*, allowed_senders: frozenset[str] = frozenset()) -> Settings:
    return Settings(  # type: ignore[call-arg]
        linq_partner_token=SecretStr("partner-token"),
        linq_webhook_secret=SecretStr(WEBHOOK_SECRET),
        linq_from_number=BOT_NUMBER,
        llm_provider=LLMProvider.ANTHROPIC,
        anthropic_api_key=SecretStr("test"),
        linq_allowed_senders=allowed_senders,
    )


def _make_app(chef: StubChef, linq: StubLinq, *, settings: Settings | None = None):
    app = FastAPI()
    app.include_router(router)
    app.state.settings = settings or _settings()
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


@pytest.fixture
def chef():
    return StubChef("chicken piccata\nchicken adobo")


@pytest.fixture
def linq():
    return StubLinq()


@pytest.fixture
def app(chef, linq):
    return _make_app(chef, linq)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


# ---------- happy path + history persistence ----------

def test_happy_path(app, chef, linq, client):
    body = _envelope("message.received", "evt-1", _message_received_data())
    r = _post(client, body)
    assert r.status_code == 200
    assert len(chef.calls) == 1
    history_seen, user_text = chef.calls[0]
    assert history_seen == []
    assert user_text == "hi chef"
    assert linq.sends == [(SENDER, "chicken piccata\nchicken adobo")]
    assert app.state.conversation_store.get(SENDER) == [
        {"role": Role.USER, "content": "hi chef"},
        {"role": Role.ASSISTANT, "content": "chicken piccata\nchicken adobo"},
    ]


# ---------- auth / parse failures ----------

def test_missing_signature_returns_401(client):
    r = client.post(WEBHOOK_PATH, content=b"{}", headers={"Content-Type": "application/json"})
    assert r.status_code == 401


def test_bad_signature_returns_401(chef, linq, client):
    body = _envelope("message.received", "evt-bad-sig", _message_received_data())
    r = _post(client, body, signature="0" * 64)
    assert r.status_code == 401
    assert chef.calls == [] and linq.sends == []


def test_stale_timestamp_returns_401(chef, linq, client):
    body = _envelope("message.received", "evt-stale", _message_received_data())
    stale_ts = str(int(time.time()) - 3600)
    r = _post(client, body, timestamp=stale_ts)
    assert r.status_code == 401
    assert chef.calls == [] and linq.sends == []


def test_malformed_json_returns_400(client):
    raw = b"{not json"
    ts = str(int(time.time()))
    sig = _sign(ts, raw)
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


# ---------- routing rules ----------

def test_unknown_event_type_is_200_noop(chef, linq, client):
    body = _envelope("message.delivered", "evt-2", _message_received_data())
    r = _post(client, body, event="message.delivered")
    assert r.status_code == 200
    assert chef.calls == [] and linq.sends == []


def test_replay_dedup(chef, linq, client):
    body = _envelope("message.received", "evt-replay", _message_received_data())
    r1 = _post(client, body)
    r2 = _post(client, body)
    assert r1.status_code == 200 and r2.status_code == 200
    assert len(chef.calls) == 1
    assert len(linq.sends) == 1


def test_group_chat_ignored(chef, linq, client):
    body = _envelope("message.received", "evt-group", _message_received_data(is_group=True))
    r = _post(client, body)
    assert r.status_code == 200
    assert chef.calls == [] and linq.sends == []


def test_outbound_direction_ignored(chef, linq, client):
    body = _envelope("message.received", "evt-outbound", _message_received_data(direction="outbound"))
    r = _post(client, body)
    assert r.status_code == 200
    assert chef.calls == [] and linq.sends == []


def test_non_text_part_triggers_polite_refusal(chef, linq, client):
    body = _envelope(
        "message.received",
        "evt-image",
        _message_received_data(parts=[{"type": "media", "id": "m1", "url": "https://x"}]),
    )
    r = _post(client, body)
    assert r.status_code == 200
    assert chef.calls == [], "chef should not be invoked for non-text"
    assert linq.sends == [(SENDER, NON_TEXT_REFUSAL_TEXT)]


# ---------- allowlist ----------

def test_disallowed_sender_is_silent_200():
    chef = StubChef()
    linq = StubLinq()
    settings = _settings(allowed_senders=frozenset({"+15550009999"}))
    app = _make_app(chef, linq, settings=settings)
    body = _envelope("message.received", "evt-disallowed", _message_received_data())
    with TestClient(app) as client:
        r = _post(client, body)
    assert r.status_code == 200
    assert chef.calls == [] and linq.sends == []


def test_allowed_sender_passes():
    chef = StubChef("ok")
    linq = StubLinq()
    settings = _settings(allowed_senders=frozenset({SENDER}))
    app = _make_app(chef, linq, settings=settings)
    body = _envelope("message.received", "evt-allowed", _message_received_data())
    with TestClient(app) as client:
        r = _post(client, body)
    assert r.status_code == 200
    assert len(chef.calls) == 1
    assert linq.sends == [(SENDER, "ok")]


# ---------- hardening: fallback + input cap ----------

def test_chef_failure_sends_fallback(app, linq):
    # Override the chef to raise; rebuild app since the fixture chef doesn't.
    chef = StubChef(raise_on_call=True)
    new_app = _make_app(chef, linq)
    body = _envelope("message.received", "evt-chef-fail", _message_received_data())
    with TestClient(new_app) as client:
        r = _post(client, body)
    assert r.status_code == 200
    assert len(chef.calls) == 1
    assert linq.sends == [(SENDER, CHEF_ERROR_FALLBACK_TEXT)]
    # history should not be appended on failure
    assert new_app.state.conversation_store.get(SENDER) == []


def test_input_length_cap(chef, linq, app, client):
    cap = app.state.settings.max_inbound_text_chars
    long_text = "x" * (cap + 500)
    body = _envelope(
        "message.received", "evt-long",
        _message_received_data(parts=[{"type": "text", "value": long_text}]),
    )
    r = _post(client, body)
    assert r.status_code == 200
    assert len(chef.calls) == 1
    _, seen_text = chef.calls[0]
    assert len(seen_text) == cap
