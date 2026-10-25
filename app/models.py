"""Pydantic models shared by the API and the pipeline."""

from typing import Literal

from pydantic import BaseModel


class DbHealth(BaseModel):
    ok: bool
    sqlite_version: str | None = None
    sqlite_vec_version: str | None = None
    schema_version: int | None = None
    schema_latest: int | None = None
    error: str | None = None


class OllamaHealth(BaseModel):
    ok: bool
    url: str
    version: str | None = None
    llm_model: str
    embed_model: str
    llm_model_ready: bool = False
    embed_model_ready: bool = False
    error: str | None = None


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    db: DbHealth
    ollama: OllamaHealth
