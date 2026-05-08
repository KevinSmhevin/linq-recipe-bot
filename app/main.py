from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.chef import ChefAssistant
from app.config import Settings, get_settings
from app.conversations import InMemoryConversationStore
from app.llm import AISDKChatProvider


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    http_client = httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0))
    conversation_store = InMemoryConversationStore(
        ttl_hours=settings.conversation_ttl_hours
    )
    chat_provider = AISDKChatProvider(settings)
    chef = ChefAssistant(chat_provider)

    app.state.settings = settings
    app.state.http_client = http_client
    app.state.conversation_store = conversation_store
    app.state.chef = chef

    try:
        yield
    finally:
        http_client.close()


app = FastAPI(lifespan=lifespan, title="linq-recipe-bot")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
