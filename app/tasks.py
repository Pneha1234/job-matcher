"""In-process background tasks with progress rows the UI can poll.

A single user on one machine needs no queue: each task is an asyncio task on the API's
event loop, so it shares the one SQLite connection with the request handlers. Blocking
work (PDF parsing, JobSpy) goes through ``asyncio.to_thread`` and never touches the DB.
"""

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

from app.util import dumps, loads, now_iso

log = logging.getLogger(__name__)


class TaskContext:
    def __init__(self, conn: sqlite3.Connection, task_id: int, steps: list[str]):
        self.conn = conn
        self.id = task_id
        self.progress = [{"step": s, "state": "pending"} for s in steps]

    def _write(self) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE tasks SET progress = ? WHERE id = ?", (dumps(self.progress), self.id)
            )

    def step(self, index: int, state: str = "running", detail: str | None = None) -> None:
        self.progress[index]["state"] = state
        if detail is not None:
            self.progress[index]["detail"] = detail
        self._write()

    def add_step(self, label: str, state: str = "pending") -> int:
        self.progress.append({"step": label, "state": state})
        self._write()
        return len(self.progress) - 1


TaskFn = Callable[[TaskContext], Awaitable[Any]]


class TaskRunner:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._running: dict[int, asyncio.Task] = {}
        with conn:
            # Tasks cut off by a restart would otherwise look like they run forever.
            conn.execute(
                "UPDATE tasks SET status = 'error', error = 'Interrupted by an API restart', "
                "finished_at = ? WHERE status IN ('queued', 'running')",
                (now_iso(),),
            )

    def start(self, kind: str, steps: list[str], fn: TaskFn) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO tasks (kind, status, progress) VALUES (?, 'running', ?)",
                (kind, dumps([{"step": s, "state": "pending"} for s in steps])),
            )
        task_id = cur.lastrowid
        ctx = TaskContext(self.conn, task_id, steps)
        self._running[task_id] = asyncio.create_task(self._run(ctx, fn))
        return task_id

    async def _run(self, ctx: TaskContext, fn: TaskFn) -> None:
        try:
            result = await fn(ctx)
        except Exception as e:  # surfaced to the UI as the task's error
            log.exception("task %s failed", ctx.id)
            for p in ctx.progress:
                if p["state"] == "running":
                    p["state"] = "error"
            with self.conn:
                self.conn.execute(
                    "UPDATE tasks SET status = 'error', error = ?, progress = ?, finished_at = ? "
                    "WHERE id = ?",
                    (str(e) or type(e).__name__, dumps(ctx.progress), now_iso(), ctx.id),
                )
        else:
            with self.conn:
                self.conn.execute(
                    "UPDATE tasks SET status = 'done', result = ?, progress = ?, finished_at = ? "
                    "WHERE id = ?",
                    (dumps(result), dumps(ctx.progress), now_iso(), ctx.id),
                )
        finally:
            self._running.pop(ctx.id, None)

    def is_running(self, kind: str) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM tasks WHERE kind = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
            (kind,),
        ).fetchone()
        return row["id"] if row and row["id"] in self._running else None

    async def wait(self, task_id: int) -> None:
        task = self._running.get(task_id)
        if task:
            await asyncio.shield(task)

    async def shutdown(self) -> None:
        for task in list(self._running.values()):
            task.cancel()
        await asyncio.gather(*self._running.values(), return_exceptions=True)


def get_task(conn: sqlite3.Connection, task_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "progress": loads(row["progress"], []),
        "result": loads(row["result"]),
        "error": row["error"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }
