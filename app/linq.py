import httpx

from app.config import Settings
from app.enums import LinqMessagePartType

_OUTBOUND_PATH = "/api/partner/v3/chats"


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
