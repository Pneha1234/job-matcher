"""FastAPI dependencies: the shared DB connection, Ollama client and task runner."""

import sqlite3
from typing import Annotated

from fastapi import Depends, Request

from app.llm import OllamaClient
from app.tasks import TaskRunner


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def get_ollama(request: Request) -> OllamaClient:
    return request.app.state.ollama


def get_tasks(request: Request) -> TaskRunner:
    return request.app.state.tasks


DbDep = Annotated[sqlite3.Connection, Depends(get_db)]
OllamaDep = Annotated[OllamaClient, Depends(get_ollama)]
TasksDep = Annotated[TaskRunner, Depends(get_tasks)]
