"""FastAPI entry point: ``uvicorn app.main:app``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.config import get_settings
from app.db import init_db
from app.llm import OllamaClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.db = init_db(settings.db_path)
    app.state.ollama = OllamaClient()
    try:
        yield
    finally:
        await app.state.ollama.aclose()
        app.state.db.close()


app = FastAPI(title="Job Matcher", lifespan=lifespan)
# The UI normally reaches the API through Next.js's /api rewrite; CORS covers direct calls.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().ui_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
