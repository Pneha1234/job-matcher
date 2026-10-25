"""Run one source: budget and pause checks, fetch, normalise + upsert, lifecycle, run log."""

import logging
import re
import sqlite3
from datetime import date, timedelta

import httpx

from app.config import get_settings
from app.lifecycle.expiry import record_listing
from app.normalize.ingest import Normaliser, upsert
from app.settings_store import load as load_settings
from app.sources import registry
from app.sources.ats import BOARD_PATTERNS
from app.sources.base import BudgetExhausted, FetchContext, PoliteClient, SourceBlocked
from app.util import loads, now_iso

log = logging.getLogger(__name__)


def saved_searches(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT filters FROM saved_searches WHERE is_archived = 0 ORDER BY position, id"
    ).fetchall()
    return [loads(r["filters"], {}) for r in rows]


def source_state(conn: sqlite3.Connection, name: str) -> dict:
    row = conn.execute("SELECT * FROM source_state WHERE source = ?", (name,)).fetchone()
    return dict(row) if row else {"source": name, "status": "active"}


def set_paused(conn: sqlite3.Connection, name: str, reason: str | None, until: str | None):
    with conn:
        conn.execute(
            "INSERT INTO source_state (source, status, paused_reason, paused_until, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (source) DO UPDATE SET status = excluded.status, "
            "paused_reason = excluded.paused_reason, paused_until = excluded.paused_until, "
            "updated_at = excluded.updated_at",
            (name, "paused" if reason else "active", reason, until, now_iso()),
        )


def _tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


def board_from_url(url: str) -> tuple[str, str] | None:
    for pattern, platform in BOARD_PATTERNS:
        if m := re.search(pattern, url, re.I):
            return platform, m.group(1).lower()
    if m := re.search(
        r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", url
    ):
        return "workday", f"{m.group(1)}|{m.group(2)}|{m.group(3)}"
    return None


def _grow_companies(conn: sqlite3.Connection, raws) -> int:
    """Self-growth: a scraped job that links to a company board adds that board."""
    added = 0
    for raw in raws:
        if raw.company_board:
            continue
        found = board_from_url(raw.url) or board_from_url(raw.extra.get("listing_url", ""))
        if not found:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO companies (name, platform, slug) VALUES (?, ?, ?)",
            (raw.company, *found),
        )
        added += cur.rowcount
    return added


async def run_source(
    conn: sqlite3.Connection, name: str, transport: httpx.AsyncBaseTransport | None = None
) -> dict:
    source = registry.get(name)
    settings = load_settings(conn)
    state = source_state(conn, name)
    if state["status"] == "paused":
        until = state.get("paused_until")
        if until and until <= date.today().isoformat():
            set_paused(conn, name, None, None)
        else:
            return {"source": name, "status": "paused", "reason": state.get("paused_reason")}

    with conn:
        run_id = conn.execute("INSERT INTO scrape_runs (source) VALUES (?)", (name,)).lastrowid
    cfg = get_settings()
    http = PoliteClient(
        name,
        conn,
        budget=source.daily_budget,
        delay=(cfg.scrape_delay_min, cfg.scrape_delay_max),
        transport=transport,
    )
    companies = []
    if source.platform:
        companies = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM companies WHERE platform = ? AND status = 'active'",
                (source.platform,),
            )
        ]
    ctx = FetchContext(
        conn=conn,
        http=http,
        searches=saved_searches(conn),
        target_countries=settings.target_countries,
        companies=companies,
    )
    status, error_text, result = "ok", None, None
    try:
        if source.needs_searches and not ctx.searches:
            status, error_text = "error", "Add a saved search in Settings first"
        elif source.platform and not companies:
            status, error_text = "ok", "No company boards on the crawl list yet"
        else:
            result = await source.fetch(ctx)
    except SourceBlocked as e:
        set_paused(conn, name, f"Blocked: {e}", None)
        status, error_text = "paused", f"{e}. Paused; resume it on the Sources page."
    except BudgetExhausted as e:
        set_paused(conn, name, str(e), _tomorrow())
        status, error_text = "paused", f"{e}. Paused until tomorrow."
    except (httpx.HTTPError, ValueError) as e:
        status, error_text = "error", f"{e.__class__.__name__}: {e}"[:500]
    except Exception as e:  # a broken scraper shows red on the Sources page
        log.exception("source %s failed", name)
        status, error_text = "error", f"{e.__class__.__name__}: {e}"[:500]
    finally:
        await http.aclose()

    found = new = expired = 0
    errors = 0
    if result is not None:
        normaliser = Normaliser(conn, settings)
        seen: set[str] = set()
        with conn:
            for raw in result.jobs:
                if raw.source_job_id in seen:
                    continue
                seen.add(raw.source_job_id)
                try:
                    _, created = upsert(conn, raw, normaliser.normalise(raw))
                except Exception:  # one odd posting must not sink the run
                    log.exception("could not store %s %s", name, raw.source_job_id)
                    errors += 1
                    continue
                found += 1
                new += int(created)
            _grow_companies(conn, result.jobs)
        expired = record_listing(
            conn, name, source.label, result.complete_scopes, seen, result.still_listed
        )
        errors += len(result.errors)
        if result.errors and not error_text:
            error_text = "; ".join(result.errors[:3])
        if found == 0 and status == "ok" and not error_text:
            error_text = "0 jobs returned. The site may have changed."

    with conn:
        conn.execute(
            "UPDATE scrape_runs SET finished_at = ?, status = ?, found = ?, new = ?, errors = ?, "
            "budget_used = ?, error_text = ? WHERE id = ?",
            (now_iso(), status, found, new, errors, http.requests, error_text, run_id),
        )
    return {
        "source": name,
        "run_id": run_id,
        "status": status,
        "found": found,
        "new": new,
        "expired": expired,
        "error": error_text,
    }
