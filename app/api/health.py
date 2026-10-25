"""GET /health — database and Ollama status for the UI's sidebar footer."""

import sqlite3

from fastapi import APIRouter

from app.api.deps import DbDep, OllamaDep, get_db, get_ollama  # noqa: F401 (tests override)
from app.config import get_settings
from app.db import db_status
from app.llm import LLMError
from app.models import DbHealth, Health, OllamaHealth
from app.settings_store import load as load_settings

router = APIRouter()


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
    app_settings = load_settings(db)
    llm, scoring = app_settings.model_name(), app_settings.scoring_model_name()
    ollama_health = OllamaHealth(
        ok=False,
        url=settings.ollama_url,
        llm_model=llm,
        scoring_model=scoring,
        embed_model=ollama.embed_model,
    )
    try:
        ollama_health.version = await ollama.version()
        installed = await ollama.list_models()
        ollama_health.llm_model_ready = _has_model(installed, llm)
        ollama_health.scoring_model_ready = _has_model(installed, scoring)
        ollama_health.embed_model_ready = _has_model(installed, ollama.embed_model)
        ollama_health.ok = True
        missing = [
            m
            for m, ready in (
                (llm, ollama_health.llm_model_ready),
                (scoring, ollama_health.scoring_model_ready),
                (ollama.embed_model, ollama_health.embed_model_ready),
            )
            if not ready
        ]
        if missing:
            ollama_health.error = f"model not pulled: {', '.join(dict.fromkeys(missing))}"
    except LLMError as e:
        ollama_health.error = str(e)

    healthy = (
        db_health.ok
        and ollama_health.ok
        and ollama_health.llm_model_ready
        and ollama_health.scoring_model_ready
        and ollama_health.embed_model_ready
    )
    return Health(status="ok" if healthy else "degraded", db=db_health, ollama=ollama_health)
