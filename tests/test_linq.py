import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.enums import LLMProvider
from app.linq import LinqAPIError, LinqClient


@pytest.fixture
def settings():
    return Settings(  # type: ignore[call-arg]
        linq_partner_token=SecretStr("test-token"),
        linq_webhook_secret=SecretStr("test-secret"),
        linq_from_number="+16462617385",
        linq_base_url="https://linq.test",
        llm_provider=LLMProvider.ANTHROPIC,
        anthropic_api_key=SecretStr("test-anthropic"),
    )


def _make_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_send_text_request_shape(settings):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    linq = LinqClient(_make_client(handler), settings)
    linq.send_text("+15555550123", "chicken piccata\nchicken tikka")

    assert captured["method"] == "POST"
    assert captured["url"] == "https://linq.test/api/partner/v3/chats"
    assert captured["auth"] == "Bearer test-token"
    assert captured["content_type"] == "application/json"
    assert captured["body"] == {
        "from": "+16462617385",
        "to": ["+15555550123"],
        "message": {"parts": [{"type": "text", "value": "chicken piccata\nchicken tikka"}]},
    }


def test_non_2xx_raises_linq_api_error(settings):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad token")

    linq = LinqClient(_make_client(handler), settings)
    with pytest.raises(LinqAPIError) as exc_info:
        linq.send_text("+15555550123", "hi")
    assert exc_info.value.status_code == 401
    assert "bad token" in exc_info.value.body


def test_5xx_raises_linq_api_error(settings):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream busy")

    linq = LinqClient(_make_client(handler), settings)
    with pytest.raises(LinqAPIError) as exc_info:
        linq.send_text("+15555550123", "hi")
    assert exc_info.value.status_code == 503
