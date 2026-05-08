import hashlib
import hmac
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.enums import LinqMessagePartType

_OUTBOUND_PATH = "/api/partner/v3/chats"


def verify_webhook_signature(
    secret: str,
    raw_body: bytes,
    timestamp_header: str,
    signature_header: str,
) -> bool:
    """Constant-time check of the X-Webhook-Signature header against
    HMAC-SHA256(secret, f"{timestamp}.{raw_body}") rendered as hex.

    `raw_body` MUST be the bytes pulled from `await request.body()` — do not
    re-serialize parsed JSON, or the HMAC will fail on field-order changes.
    """
    payload = timestamp_header.encode("utf-8") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def is_timestamp_fresh(
    timestamp_header: str,
    tolerance_seconds: int,
    now: datetime,
) -> bool:
    """True iff `timestamp_header` (Unix seconds string) is within
    `tolerance_seconds` of `now`. Replay protection for webhooks.

    Linq does not document a freshness window, so we enforce one ourselves.
    """
    try:
        sent_at = datetime.fromtimestamp(int(timestamp_header), tz=timezone.utc)
    except (ValueError, OSError):
        return False
    return abs((now - sent_at).total_seconds()) <= tolerance_seconds


class LinqAPIError(RuntimeError):
    """Raised when the Linq API returns a non-2xx response."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"Linq API error {status_code}: {body[:500]}")
        self.status_code = status_code
        self.body = body


class LinqClient:
    """Sync client for the Linq Partner API v3.
    Currently exposes outbound `send_text`. Inbound webhook parsing lives in
    `app/routes/webhook.py` once Phase 4 nails down the payload schema.
    """

    def __init__(self, http_client: httpx.Client, settings: Settings) -> None:
        self._http = http_client
        self._base_url = settings.linq_base_url.rstrip("/")
        self._token = settings.linq_partner_token.get_secret_value()
        self._from_number = settings.linq_from_number

    def send_text(self, to: str, text: str) -> None:
        response = self._http.post(
            f"{self._base_url}{_OUTBOUND_PATH}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            json={
                "from": self._from_number,
                "to": [to],
                "message": {
                    "parts": [{"type": LinqMessagePartType.TEXT, "value": text}]
                },
            },
        )
        if not response.is_success:
            raise LinqAPIError(response.status_code, response.text)
