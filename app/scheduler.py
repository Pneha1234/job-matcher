"""Unattended runs (APScheduler, in-process). A tick every 10 minutes runs any source
group whose interval (Settings → Schedules) has passed, and the daily lifecycle pass."""

import logging
import sqlite3
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.lifecycle.expiry import check_urls, expire_deadlines, mark_stale
from app.llm import OllamaClient
from app.matching.service import start_rescore
from app.normalize import fx, geo
from app.settings_store import get_value, load, set_value
from app.sources import registry
from app.sources.base import PoliteClient
from app.sources.runner import run_source
from app.tasks import TaskRunner
from app.util import days_ago

log = logging.getLogger(__name__)


def due_groups(conn: sqlite3.Connection) -> list[str]:
    settings = load(conn)
    hours = settings.schedules.model_dump()
    due = []
    for group, interval in hours.items():
        if not interval:
            continue
        names = [n for n, s in registry.SOURCES.items() if s.group == group]
        if not names:
            continue
        marks = ",".join("?" * len(names))
        last = conn.execute(
            f"SELECT MAX(started_at) FROM scrape_runs WHERE source IN ({marks})", names
        ).fetchone()[0]
        if not last or last < days_ago(interval / 24):
            due.append(group)
    return due


async def run_group(conn, ollama: OllamaClient, tasks: TaskRunner, group: str) -> None:
    names = [n for n, s in registry.SOURCES.items() if s.group == group]

    async def run(ctx):
        new = 0
        for i, name in enumerate(names):
            ctx.step(i)
            result = await run_source(conn, name)
            new += result.get("new", 0)
            ctx.step(i, "done" if result["status"] == "ok" else "error",
                     result.get("reason") or f"{result.get('found', 0)} found")  # fmt: skip
        if new:
            start_rescore(conn, ollama, tasks)
        return {"group": group, "new": new}

    if not tasks.is_running(f"schedule:{group}"):
        tasks.start(f"schedule:{group}", [registry.get(n).label for n in names], run)


async def daily(conn: sqlite3.Connection) -> None:
    today = date.today().isoformat()
    if get_value(conn, "lifecycle_day") == today:
        return
    expire_deadlines(conn)
    mark_stale(conn)
    cfg = get_settings()
    http = PoliteClient("url_check", conn, budget=80, delay=(cfg.scrape_delay_min,
                                                             cfg.scrape_delay_max))  # fmt: skip
    try:
        scrape = {n for n, s in registry.SOURCES.items() if s.kind == "scrape"}
        await check_urls(conn, http, scrape)
    finally:
        await http.aclose()
    if fx.is_stale(conn):
        try:
            await fx.refresh(conn)
        except Exception:
            log.warning("FX refresh failed; salaries keep yesterday's rates", exc_info=True)
    set_value(conn, "lifecycle_day", today)


async def tick(conn, ollama: OllamaClient, tasks: TaskRunner) -> None:
    if not load(conn).scheduler_enabled:
        return
    try:
        for group in due_groups(conn):
            await run_group(conn, ollama, tasks, group)
        await daily(conn)
    except Exception:
        log.exception("scheduler tick failed")


async def first_run_setup(conn: sqlite3.Connection) -> None:
    """Free reference data the pipeline needs; failures leave the app usable."""
    try:
        if not geo.is_downloaded():
            await geo.download()
        if fx.is_stale(conn):
            await fx.refresh(conn)
    except Exception:
        log.warning("first-run download failed; retry from Settings", exc_info=True)


def start(conn, ollama: OllamaClient, tasks: TaskRunner) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(tick, "interval", minutes=10, args=[conn, ollama, tasks],
                      id="tick", max_instances=1, coalesce=True)  # fmt: skip
    scheduler.start()
    return scheduler
