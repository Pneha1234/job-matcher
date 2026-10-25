"""FastAPI entry point: ``uvicorn app.main:app``."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import scheduler
from app.api import (
    applications,
    digest,
    health,
    insights,
    jobs,
    profile,
    settings,
    sources,
    tasks,
)
from app.config import get_settings
from app.db import init_db
from app.llm import OllamaClient
from app.matching.service import start_rescore
from app.normalize.ingest import backfill_timezones
from app.seeds import seed
from app.tasks import TaskRunner


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = get_settings()
    app.state.db = init_db(cfg.db_path)
    app.state.ollama = OllamaClient()
    app.state.tasks = TaskRunner(app.state.db)
    seed(app.state.db)
    sched = None
    if cfg.scheduler:
        asyncio.create_task(scheduler.first_run_setup(app.state.db))
        backfill_timezones(app.state.db)
        sched = scheduler.start(app.state.db, app.state.ollama, app.state.tasks)
        # Pick up scoring a restart interrupted; it skips jobs already scored.
        start_rescore(app.state.db, app.state.ollama, app.state.tasks)
    try:
        yield
    finally:
        if sched:
            sched.shutdown(wait=False)
        await app.state.tasks.shutdown()
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
for module in (health, profile, jobs, applications, sources, settings, insights, tasks, digest):
    app.include_router(module.router)
