import logging
import time
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, Response
from pydantic import BaseModel, ConfigDict, ValidationError

from app.chef import ChefAssistant
from app.constants import CHEF_ERROR_FALLBACK_TEXT, NON_TEXT_REFUSAL_TEXT
from app.conversations import ConversationStore
from app.dedup import EventDedup
from app.enums import (
    LinqEventType,
    LinqMessageDirection,
    LinqMessagePartType,
    LinqWebhookHeader,
    Role,
)
from app.linq import LinqClient, is_timestamp_fresh, verify_webhook_signature

WEBHOOK_PATH = "/webhooks/linq"

logger = logging.getLogger(__name__)
router = APIRouter()


class _BaseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _LinqMessagePart(_BaseModel):
    type: str
    value: str | None = None


class _LinqSenderHandle(_BaseModel):
    handle: str


class _LinqChat(_BaseModel):
    id: str
    is_group: bool


class _LinqMessageReceivedData(_BaseModel):
    id: str
    direction: str
    sender_handle: _LinqSenderHandle
    chat: _LinqChat
    parts: list[_LinqMessagePart]


class _LinqEnvelope(_BaseModel):
    event_type: str
    event_id: str
    data: dict[str, Any]


def _send(linq: LinqClient, to: str, text: str, *, kind: str) -> bool:
    """Send via Linq with timing + structured logging. Returns True on success."""
    start = time.monotonic()
    try:
        linq.send_text(to, text)
    except Exception as exc:
        logger.warning(
            "linq_send_failed thread=%s kind=%s err=%s",
            to, kind, exc,
        )
        return False
    logger.info(
        "linq_send thread=%s kind=%s latency_ms=%d chars=%d",
        to, kind, int((time.monotonic() - start) * 1000), len(text),
    )
    return True


def _process_inbound(
    *,
    chef: ChefAssistant,
    linq: LinqClient,
    store: ConversationStore,
    thread_key: str,
    user_text: str,
) -> None:
    history = store.get(thread_key)
    chef_started = time.monotonic()
    try:
        reply = chef.reply(history, user_text)
    except Exception as exc:
        logger.warning(
            "chef_failed thread=%s err=%s",
            thread_key, exc,
        )
        _send(linq, thread_key, CHEF_ERROR_FALLBACK_TEXT, kind="fallback")
        return
    logger.info(
        "chef_reply thread=%s latency_ms=%d input_chars=%d output_chars=%d",
        thread_key,
        int((time.monotonic() - chef_started) * 1000),
        len(user_text),
        len(reply),
    )

    if not _send(linq, thread_key, reply, kind="reply"):
        return
    store.append(thread_key, Role.USER, user_text)
    store.append(thread_key, Role.ASSISTANT, reply)


def _send_non_text_refusal(*, linq: LinqClient, to: str) -> None:
    _send(linq, to, NON_TEXT_REFUSAL_TEXT, kind="non_text_refusal")


@router.post(WEBHOOK_PATH)
async def handle_linq_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    raw_body = await request.body()
    settings = request.app.state.settings

    signature = request.headers.get(LinqWebhookHeader.SIGNATURE)
    timestamp = request.headers.get(LinqWebhookHeader.TIMESTAMP)
    if not signature or not timestamp:
        return Response(status_code=HTTPStatus.UNAUTHORIZED)

    if not verify_webhook_signature(
        settings.linq_webhook_secret.get_secret_value(),
        raw_body,
        timestamp,
        signature,
    ):
        return Response(status_code=HTTPStatus.UNAUTHORIZED)

    if not is_timestamp_fresh(
        timestamp,
        settings.webhook_timestamp_tolerance_seconds,
        datetime.now(timezone.utc),
    ):
        return Response(status_code=HTTPStatus.UNAUTHORIZED)

    try:
        envelope = _LinqEnvelope.model_validate_json(raw_body)
    except ValidationError:
        return Response(status_code=HTTPStatus.BAD_REQUEST)

    dedup: EventDedup = request.app.state.event_dedup
    if dedup.is_duplicate(envelope.event_id):
        return Response(status_code=HTTPStatus.OK)

    if envelope.event_type != LinqEventType.MESSAGE_RECEIVED:
        return Response(status_code=HTTPStatus.OK)

    try:
        data = _LinqMessageReceivedData.model_validate(envelope.data)
    except ValidationError:
        return Response(status_code=HTTPStatus.BAD_REQUEST)

    if data.direction != LinqMessageDirection.INBOUND:
        return Response(status_code=HTTPStatus.OK)
    if data.chat.is_group:
        return Response(status_code=HTTPStatus.OK)

    thread_key = data.sender_handle.handle
    allowed = settings.linq_allowed_senders
    if allowed and thread_key not in allowed:
        return Response(status_code=HTTPStatus.OK)

    linq: LinqClient = request.app.state.linq

    text_parts = [
        p.value for p in data.parts
        if p.type == LinqMessagePartType.TEXT and p.value
    ]
    if not text_parts:
        background_tasks.add_task(_send_non_text_refusal, linq=linq, to=thread_key)
        return Response(status_code=HTTPStatus.OK)

    user_text = "\n".join(text_parts)
    if len(user_text) > settings.max_inbound_text_chars:
        user_text = user_text[: settings.max_inbound_text_chars]

    logger.info(
        "webhook_received event_id=%s thread=%s parts=%d input_chars=%d",
        envelope.event_id, thread_key, len(data.parts), len(user_text),
    )
    background_tasks.add_task(
        _process_inbound,
        chef=request.app.state.chef,
        linq=linq,
        store=request.app.state.conversation_store,
        thread_key=thread_key,
        user_text=user_text,
    )
    return Response(status_code=HTTPStatus.OK)
