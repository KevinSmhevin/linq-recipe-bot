import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.chef import ChefAssistant
from app.config import Settings, get_settings
from app.conversations import InMemoryConversationStore
from app.dedup import InMemoryEventDedup
from app.linq import LinqClient
from app.llm import AISDKChatProvider
from app.routes.webhook import router as webhook_router


def _configure_logging() -> None:
    # force=True overrides uvicorn's default handler so app.* INFO logs appear.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    settings: Settings = get_settings()
    http_client = httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0))
    conversation_store = InMemoryConversationStore(
        ttl_hours=settings.conversation_ttl_hours
    )
    chat_provider = AISDKChatProvider(settings)
    chef = ChefAssistant(chat_provider)
    linq = LinqClient(http_client, settings)
    event_dedup = InMemoryEventDedup(ttl_seconds=settings.webhook_dedup_ttl_seconds)

    app.state.settings = settings
    app.state.http_client = http_client
    app.state.conversation_store = conversation_store
    app.state.chef = chef
    app.state.linq = linq
    app.state.event_dedup = event_dedup

    try:
        yield
    finally:
        http_client.close()


app = FastAPI(lifespan=lifespan, title="linq-recipe-bot")
app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
