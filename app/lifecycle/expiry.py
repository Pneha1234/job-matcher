"""Keeping only active jobs active (docs/PLAN.md, Lifecycle):

- feed/ATS sources: missing from 2 consecutive complete listings -> expired
- scraped jobs older than 7 days: daily URL check (404/410, redirect to a generic careers
  page, "no longer accepting" text) -> expired
- past validThrough / "apply before" -> expired
- not confirmed for 45 days -> stale (hidden by default)

Expiry is a status change with a reason; a job that shows up again becomes active again.
"""

import re
import sqlite3
from datetime import date
from urllib.parse import urlparse

from app.sources.base import NotFound, PoliteClient, SourceBlocked
from app.util import days_ago, now_iso

MISSES_TO_EXPIRE = 2
STALE_DAYS = 45
URL_CHECK_AFTER_DAYS = 7
CLOSED_TEXT = re.compile(
    r"no longer (accepting|available|active)|position has been filled|job (has )?expired|"
    r"this job is closed|vacancy (is )?closed|applications? (are |is )?closed|"
    r"job you are looking for (is|was) (not|no longer)|stelle ist (nicht mehr|bereits) besetzt",
    re.I,
)


def _today() -> str:
    return date.today().strftime("%b %-d")


def record_listing(
    conn: sqlite3.Connection,
    source: str,
    label: str,
    complete_scopes: set[str],
    seen_ids: set[str],
    still_listed: set[str],
) -> int:
    """After a run: count misses in complete scopes, confirm still-listed ones, expire jobs
    with no listed source left. Returns how many jobs expired."""
    now = now_iso()
    with conn:
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _seen (id TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM _seen")
        conn.executemany(
            "INSERT OR IGNORE INTO _seen (id) VALUES (?)", [(i,) for i in seen_ids | still_listed]
        )
        if still_listed:
            conn.execute(
                "UPDATE job_sources SET last_seen_at = ?, missed_runs = 0 WHERE source = ? "
                "AND status = 'listed' AND source_job_id IN (SELECT id FROM _seen)",
                (now, source),
            )
            conn.execute(
                "UPDATE jobs SET last_seen_at = ? WHERE id IN (SELECT job_id FROM job_sources "
                "WHERE source = ? AND source_job_id IN (SELECT id FROM _seen))",
                (now, source),
            )
        for scope in complete_scopes:
            conn.execute(
                "UPDATE job_sources SET missed_runs = missed_runs + 1, status = CASE WHEN "
                "missed_runs + 1 >= ? THEN 'gone' ELSE status END WHERE source = ? AND scope = ? "
                "AND status = 'listed' AND source_job_id NOT IN (SELECT id FROM _seen)",
                (MISSES_TO_EXPIRE, source, scope),
            )
        cur = conn.execute(
            "UPDATE jobs SET status = 'expired', expired_reason = ?, updated_at = ? "
            "WHERE status IN ('active', 'stale') "
            "AND id IN (SELECT job_id FROM job_sources WHERE source = ? AND status = 'gone') "
            "AND NOT EXISTS (SELECT 1 FROM job_sources s WHERE s.job_id = jobs.id "
            "AND s.status = 'listed')",
            (f"Removed from {label} on {_today()}", now, source),
        )
    return cur.rowcount


def expire_deadlines(conn: sqlite3.Connection) -> int:
    with conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'expired', updated_at = ?, expired_reason = "
            "'Application deadline passed on ' || substr(valid_through, 1, 10) "
            "WHERE status IN ('active', 'stale') AND valid_through IS NOT NULL "
            "AND valid_through < ?",
            (now_iso(), now_iso()),
        )
    return cur.rowcount


def mark_stale(conn: sqlite3.Connection) -> int:
    with conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'stale', updated_at = ?, expired_reason = "
            "'Not seen on any source for 45 days' WHERE status = 'active' AND last_seen_at < ?",
            (now_iso(), days_ago(STALE_DAYS)),
        )
    return cur.rowcount


def _generic_page(url: str) -> bool:
    path = urlparse(url).path.rstrip("/").lower()
    return path in ("", "/careers", "/jobs", "/career", "/en/careers", "/en/jobs", "/search")


async def check_urls(
    conn: sqlite3.Connection, http: PoliteClient, scrape_sources: set[str], limit: int = 40
) -> dict:
    """Daily check of scraped jobs older than 7 days, oldest check first."""
    if not scrape_sources:
        return {"checked": 0, "expired": 0}
    marks = ",".join("?" * len(scrape_sources))
    rows = conn.execute(
        f"SELECT j.id, s.url, s.source FROM jobs j JOIN job_sources s ON s.job_id = j.id "
        f"WHERE j.status = 'active' AND s.source IN ({marks}) AND j.first_seen_at < ? "
        f"AND (j.last_checked_at IS NULL OR j.last_checked_at < ?) "
        f"GROUP BY j.id ORDER BY j.last_checked_at IS NOT NULL, j.last_checked_at LIMIT ?",
        (*scrape_sources, days_ago(URL_CHECK_AFTER_DAYS), days_ago(1), limit),
    ).fetchall()
    checked = expired = 0
    for row in rows:
        reason = None
        try:
            r = await http.request("GET", row["url"], cache_ttl_s=0)
            if _generic_page(str(r.url)) and not _generic_page(row["url"]):
                reason = f"Listing redirects to a general careers page since {_today()}"
            elif CLOSED_TEXT.search(r.text[:200_000]):
                reason = f"Posting says it is no longer accepting applications ({_today()})"
        except NotFound:
            reason = f"Listing returned 404 on {_today()}"
        except SourceBlocked:
            break  # never force past a block; try again tomorrow
        checked += 1
        with conn:
            if reason:
                expired += 1
                conn.execute(
                    "UPDATE jobs SET status = 'expired', expired_reason = ?, last_checked_at = ?, "
                    "updated_at = ? WHERE id = ?",
                    (reason, now_iso(), now_iso(), row["id"]),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET last_checked_at = ? WHERE id = ?", (now_iso(), row["id"])
                )
    return {"checked": checked, "expired": expired}
