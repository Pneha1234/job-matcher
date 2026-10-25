"""What the Sources page shows per source: health, last run, 7-run history, budget."""

import sqlite3
import statistics
from datetime import date

from app.sources.registry import SOURCES
from app.sources.runner import api_keys


def _health(
    state: dict | None, runs: list[sqlite3.Row], missing_key: str | None = None
) -> tuple[str, str | None]:
    if missing_key:
        return "needs_key", missing_key
    if state and state["status"] == "paused":
        return "paused", state["paused_reason"]
    if not runs:
        return "never", None
    last = runs[0]
    if last["status"] == "error":
        return "broken", last["error_text"]
    if last["status"] == "paused":
        return "paused", last["error_text"]
    if last["found"] == 0:
        earlier = [r["found"] for r in runs[1:] if r["status"] == "ok"]
        if len(runs) >= 3 and all(r["found"] == 0 for r in runs[:3]):
            return "broken", f"0 jobs for {min(len(runs), 7)} runs. Page layout likely changed."
        if any(earlier):
            return "broken", "0 jobs this run after finding jobs before."
        return "warn", last["error_text"] or "0 jobs returned"
    earlier = [r["found"] for r in runs[1:] if r["status"] == "ok" and r["found"]]
    if len(earlier) >= 2 and last["found"] < 0.5 * statistics.median(earlier):
        return "warn", "Returning far fewer jobs than usual"
    return "ok", last["error_text"]


def source_rows(conn: sqlite3.Connection, running: dict[str, int]) -> list[dict]:
    states = {r["source"]: dict(r) for r in conn.execute("SELECT * FROM source_state")}
    budget = {
        r["source"]: r["used"]
        for r in conn.execute(
            "SELECT source, used FROM source_budget WHERE day = ?", (date.today().isoformat(),)
        )
    }
    boards = {
        r["platform"]: r["n"]
        for r in conn.execute(
            "SELECT platform, COUNT(*) AS n FROM companies WHERE status = 'active' "
            "GROUP BY platform"
        )
    }
    keys = api_keys(conn)
    out = []
    for name, src in SOURCES.items():
        runs = conn.execute(
            "SELECT * FROM scrape_runs WHERE source = ? AND status != 'running' "
            "ORDER BY id DESC LIMIT 7",
            (name,),
        ).fetchall()
        missing = f"Free key: {src.key_help}" if src.key_help and name not in keys else None
        health, detail = _health(states.get(name), runs, missing)
        label = src.label
        if src.platform and src.platform != "jsonld":
            n = boards.get(src.platform, 0)
            label = f"{src.label} ({n} {'company' if n == 1 else 'companies'})"
        elif src.platform == "jsonld":
            n = boards.get("jsonld", 0)
            label = f"{src.label} ({n} {'site' if n == 1 else 'sites'})"
        last = runs[0] if runs else None
        out.append(
            {
                "name": name,
                "label": label,
                "via": src.via,
                "kind": src.kind,
                "group": src.group,
                "needs_searches": src.needs_searches,
                "key_help": src.key_help,
                "has_key": name in keys,
                "platform": src.platform,
                "health": health,
                "detail": detail,
                "paused": (states.get(name) or {}).get("status") == "paused",
                "paused_until": (states.get(name) or {}).get("paused_until"),
                "last_run_at": last["started_at"] if last else None,
                "found": last["found"] if last else None,
                "new": last["new"] if last else None,
                "history": [r["found"] for r in reversed(runs)],
                "budget_used": budget.get(name, 0),
                "budget": src.daily_budget,
                "running_task_id": running.get(name),
            }
        )
    return out
