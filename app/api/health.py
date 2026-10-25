"""GET /health — database and Ollama status for the UI's sidebar footer."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.config import get_settings
from app.db import db_status
from app.llm import LLMError, OllamaClient
from app.models import DbHealth, Health, OllamaHealth

router = APIRouter()


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def get_ollama(request: Request) -> OllamaClient:
    return request.app.state.ollama


DbDep = Annotated[sqlite3.Connection, Depends(get_db)]
OllamaDep = Annotated[OllamaClient, Depends(get_ollama)]


def _has_model(installed: list[str], wanted: str) -> bool:
    # Ollama lists "bge-m3:latest" for a model pulled as "bge-m3".
    return wanted in installed or f"{wanted}:latest" in installed


@router.get("/health", response_model=Health)
async def health(db: DbDep, ollama: OllamaDep) -> Health:
    try:
        db_health = DbHealth(**db_status(db))
    except sqlite3.Error as e:
        db_health = DbHealth(ok=False, error=str(e))

    settings = get_settings()
    ollama_health = OllamaHealth(
        ok=False,
        url=settings.ollama_url,
        llm_model=ollama.model,
        embed_model=ollama.embed_model,
    )
    try:
        ollama_health.version = await ollama.version()
        installed = await ollama.list_models()
        ollama_health.llm_model_ready = _has_model(installed, ollama.model)
        ollama_health.embed_model_ready = _has_model(installed, ollama.embed_model)
        ollama_health.ok = True
        missing = [
            m
            for m, ready in (
                (ollama.model, ollama_health.llm_model_ready),
                (ollama.embed_model, ollama_health.embed_model_ready),
            )
            if not ready
        ]
        if missing:
            ollama_health.error = f"model not pulled: {', '.join(missing)}"
    except LLMError as e:
        ollama_health.error = str(e)

    healthy = (
        db_health.ok
        and ollama_health.ok
        and ollama_health.llm_model_ready
        and ollama_health.embed_model_ready
    )
    return Health(status="ok" if healthy else "degraded", db=db_health, ollama=ollama_health)
