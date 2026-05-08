"""Smoke test for LinqClient using httpx.MockTransport.

No network. Verifies the outbound request shape and error handling without
spending a real Linq SMS credit or needing a real partner token.
"""

import json

import httpx
from pydantic import SecretStr

from app.config import Settings
from app.enums import LLMProvider
from app.linq import LinqAPIError, LinqClient


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        linq_partner_token=SecretStr("test-token"),
        linq_webhook_secret=SecretStr("test-secret"),
        linq_from_number="+16462617385",
        linq_base_url="https://linq.test",
        llm_provider=LLMProvider.ANTHROPIC,
        anthropic_api_key=SecretStr("test-anthropic"),
    )


def _make_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def test_send_text_request_shape() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    http = _make_client(handler)
    linq = LinqClient(http, _settings())
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
    print("send_text request shape OK")


def test_non_2xx_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad token")

    http = _make_client(handler)
    linq = LinqClient(http, _settings())
    try:
        linq.send_text("+15555550123", "hi")
    except LinqAPIError as exc:
        assert exc.status_code == 401
        assert "bad token" in exc.body
        print("LinqAPIError on 401 OK")
        return
    raise AssertionError("expected LinqAPIError on 401")


def test_5xx_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream busy")

    http = _make_client(handler)
    linq = LinqClient(http, _settings())
    try:
        linq.send_text("+15555550123", "hi")
    except LinqAPIError as exc:
        assert exc.status_code == 503
        print("LinqAPIError on 503 OK")
        return
    raise AssertionError("expected LinqAPIError on 503")


def main() -> None:
    test_send_text_request_shape()
    test_non_2xx_raises()
    test_5xx_raises()
    print("\nlinq smoke OK")


if __name__ == "__main__":
    main()
