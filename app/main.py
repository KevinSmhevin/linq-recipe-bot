from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))

    app.state.settings = settings
    app.state.http_client = http_client

    try:
        yield
    finally:
        await http_client.aclose()


app = FastAPI(lifespan=lifespan, title="linq-recipe-bot")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
